"""FAQ knowledge base management endpoints."""

from datetime import datetime, timezone
from collections import Counter

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.embeddings import EmbeddingService
from app.services.faq_service import _extract_keywords

router = APIRouter(prefix="/faq", tags=["faq"])


class FaqCreateRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)


class FaqAutoGenerateResponse(BaseModel):
    created: int
    entries: list[dict]


# ── List ───────────────────────────────────────────────────────────────

@router.get("")
async def list_faq(confirmed: bool | None = None) -> list[dict]:
    """List all FAQ entries, optionally filtered by confirmed status."""
    from app.storage.database import faq_entries, create_database_engine
    from sqlalchemy import select

    engine = create_database_engine()
    try:
        with engine.connect() as conn:
            query = select(
                faq_entries.c.id, faq_entries.c.question, faq_entries.c.answer,
                faq_entries.c.keywords, faq_entries.c.hit_count,
                faq_entries.c.is_confirmed, faq_entries.c.related_issue_ids,
                faq_entries.c.created_at,
            ).order_by(faq_entries.c.hit_count.desc())

            if confirmed is not None:
                query = query.where(faq_entries.c.is_confirmed == confirmed)

            rows = conn.execute(query).mappings().all()
            return [dict(row) for row in rows]
    finally:
        engine.dispose()


# ── Create ─────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_faq(payload: FaqCreateRequest) -> dict:
    """Add a new FAQ entry manually."""
    from app.storage.database import faq_entries, create_database_engine
    from sqlalchemy import insert

    keywords = payload.keywords or sorted(_extract_keywords(payload.question))
    embedding = EmbeddingService().embed_query(payload.question)

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(
                insert(faq_entries).values(
                    question=payload.question,
                    answer=payload.answer,
                    keywords=keywords,
                    is_confirmed=True,
                    embedding="[" + ",".join(f"{v:.8f}" for v in embedding) + "]",
                    created_at=datetime.now(timezone.utc),
                )
            )
            return {"id": result.inserted_primary_key[0], "status": "created"}
    finally:
        engine.dispose()


# ── Update / Confirm ───────────────────────────────────────────────────

@router.patch("/{faq_id}")
async def update_faq(faq_id: int, action: str) -> dict:
    """Update a FAQ entry (confirm, unconfirm, or edit)."""
    from app.storage.database import faq_entries, create_database_engine
    from sqlalchemy import update

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            if action == "confirm":
                conn.execute(
                    update(faq_entries).where(faq_entries.c.id == faq_id)
                    .values(is_confirmed=True)
                )
            elif action == "unconfirm":
                conn.execute(
                    update(faq_entries).where(faq_entries.c.id == faq_id)
                    .values(is_confirmed=False)
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid action")
            return {"status": "ok"}
    finally:
        engine.dispose()


# ── Delete ─────────────────────────────────────────────────────────────

@router.delete("/{faq_id}")
async def delete_faq(faq_id: int) -> dict:
    """Delete a FAQ entry."""
    from app.storage.database import faq_entries, create_database_engine
    from sqlalchemy import delete

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            conn.execute(delete(faq_entries).where(faq_entries.c.id == faq_id))
            return {"status": "deleted"}
    finally:
        engine.dispose()


# ── Auto-generate from similar issues ─────────────────────────────────

@router.post("/generate")
async def auto_generate_faq(owner: str, name: str) -> FaqAutoGenerateResponse:
    """Analyse synced issues and auto-generate FAQ entries from duplicates."""
    from app.storage import repository_store
    from openai import AsyncOpenAI
    from app.core.config import settings

    snapshot = repository_store.get(owner, name)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Repository not synced")

    # Group issues by category + keyword similarity.
    groups: dict[str, list[dict]] = {}
    for issue in snapshot.issues:
        if issue.state != "closed":
            continue
        text = f"{issue.title} {issue.body or ''}".lower()
        kws = ",".join(sorted(_extract_keywords(text))[:5])
        key = f"{issue.classification.category.value}:{kws}"
        groups.setdefault(key, []).append({
            "number": issue.number,
            "title": issue.title,
            "category": issue.classification.category.value,
        })

    # Pick groups with 2+ issues.
    candidates = [g for g in groups.values() if len(g) >= 2][:10]
    if not candidates:
        return FaqAutoGenerateResponse(created=0, entries=[])

    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_api_base_url,
    )
    from app.storage.database import faq_entries, create_database_engine
    from sqlalchemy import insert

    engine = create_database_engine()
    created = 0
    entries = []

    for cluster in candidates:
        issues_text = "\n".join(
            f"- #{i['number']}: {i['title']}" for i in cluster[:5]
        )
        prompt = (
            f"以下是一组相似的 GitHub Issue，请总结一个 FAQ 条目。\n\n"
            f"{issues_text}\n\n"
            "以 JSON 格式输出：\n"
            '{"question": "...", "answer": "..."}\n'
            "回答简洁，用中文。"
        )

        try:
            completion = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system",
                     "content": "You are a FAQ generator. Summarise similar issues into one FAQ entry. Output JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            import json
            import re
            raw = completion.choices[0].message.content or ""
            json_match = re.search(r'\{.*"question".*"answer".*\}', raw, re.DOTALL)
            if not json_match:
                continue
            data = json.loads(json_match.group())
            question = data.get("question", "").strip()
            answer = data.get("answer", "").strip()
            if not question or not answer:
                continue

            keywords = sorted(_extract_keywords(question))
            embedding = EmbeddingService().embed_query(question)

            with engine.begin() as conn:
                result = conn.execute(
                    insert(faq_entries).values(
                        question=question,
                        answer=answer,
                        keywords=keywords,
                        related_issue_ids=[i["number"] for i in cluster[:10]],
                        is_confirmed=False,
                        embedding="[" + ",".join(f"{v:.8f}" for v in embedding) + "]",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                created += 1
                entries.append({
                    "id": result.inserted_primary_key[0],
                    "question": question,
                    "answer": answer,
                    "related_issues": [i["number"] for i in cluster[:10]],
                    "is_confirmed": False,
                })
        except Exception:
            continue

    engine.dispose()
    return FaqAutoGenerateResponse(created=created, entries=entries)
