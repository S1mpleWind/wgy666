"""FAQ knowledge base management endpoints."""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.embeddings import EmbeddingService
from app.services.faq_service import _extract_keywords

router = APIRouter(prefix="/faq", tags=["faq"])
logger = logging.getLogger(__name__)


class FaqCreateRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)


class FaqUpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None
    keywords: list[str] | None = None


class FaqAutoGenerateResponse(BaseModel):
    created: int
    entries: list[dict]
    reason: str = ""


# ── List ───────────────────────────────────────────────────────────────

@router.get("")
async def list_faq(owner: str, name: str, confirmed: bool | None = None) -> list[dict]:
    """List FAQ entries for one repository."""
    from app.storage.database import faq_entries, create_database_engine, find_repository_id
    from sqlalchemy import select

    engine = create_database_engine()
    try:
        with engine.connect() as conn:
            repository_id = find_repository_id(conn, owner, name)
            if repository_id is None:
                raise HTTPException(status_code=404, detail="Repository not synced")
            query = select(
                faq_entries.c.id, faq_entries.c.question, faq_entries.c.answer,
                faq_entries.c.keywords, faq_entries.c.hit_count,
                faq_entries.c.is_confirmed, faq_entries.c.related_issue_ids,
                faq_entries.c.created_at,
            ).where(
                faq_entries.c.repository_id == repository_id
            ).order_by(faq_entries.c.hit_count.desc())

            if confirmed is not None:
                query = query.where(faq_entries.c.is_confirmed == confirmed)

            rows = conn.execute(query).mappings().all()
            return [dict(row) for row in rows]
    finally:
        engine.dispose()


# ── Create ─────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_faq(owner: str, name: str, payload: FaqCreateRequest) -> dict:
    """Add a new FAQ entry manually."""
    from app.storage.database import faq_entries, create_database_engine, find_repository_id
    from sqlalchemy import insert

    keywords = payload.keywords or sorted(_extract_keywords(payload.question))
    embedding = EmbeddingService().embed_query(payload.question)

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            repository_id = find_repository_id(conn, owner, name)
            if repository_id is None:
                raise HTTPException(status_code=404, detail="Repository not synced")
            result = conn.execute(
                insert(faq_entries).values(
                    repository_id=repository_id,
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
async def update_faq(faq_id: int, owner: str, name: str, action: str, body: FaqUpdateRequest | None = None) -> dict:
    """Update a FAQ entry (confirm, unconfirm, or edit)."""
    from app.storage.database import faq_entries, create_database_engine, find_repository_id
    from sqlalchemy import update

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            repository_id = find_repository_id(conn, owner, name)
            if repository_id is None:
                raise HTTPException(status_code=404, detail="Repository not synced")
            target = (
                faq_entries.c.id == faq_id
            ) & (
                faq_entries.c.repository_id == repository_id
            )
            if action == "confirm":
                result = conn.execute(
                    update(faq_entries).where(target)
                    .values(is_confirmed=True)
                )
            elif action == "unconfirm":
                result = conn.execute(
                    update(faq_entries).where(target)
                    .values(is_confirmed=False)
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid action")
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="FAQ entry not found")
            return {"status": "ok"}
    finally:
        engine.dispose()


# ── Delete ─────────────────────────────────────────────────────────────

@router.delete("/{faq_id}")
async def delete_faq(faq_id: int, owner: str, name: str) -> dict:
    """Delete a FAQ entry."""
    from app.storage.database import faq_entries, create_database_engine, find_repository_id
    from sqlalchemy import delete

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            repository_id = find_repository_id(conn, owner, name)
            if repository_id is None:
                raise HTTPException(status_code=404, detail="Repository not synced")
            result = conn.execute(
                delete(faq_entries).where(
                    faq_entries.c.id == faq_id,
                    faq_entries.c.repository_id == repository_id,
                )
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="FAQ entry not found")
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
    if not settings.llm_api_key:
        raise HTTPException(status_code=503, detail="LLM is not configured")

    # Group issues by category + keyword similarity.
    groups: dict[str, list[dict]] = {}
    for issue in snapshot.issues:
        if issue.state != "closed":
            continue
        text = issue.title.lower()
        kws = ",".join(sorted(_extract_keywords(text))[:3])
        if not kws:
            continue
        key = f"{issue.classification.category.value}:{kws}"
        groups.setdefault(key, []).append({
            "number": issue.number,
            "title": issue.title,
            "category": issue.classification.category.value,
        })

    # Pick groups with 2+ issues.
    candidates = [g for g in groups.values() if len(g) >= 2][:10]
    if not candidates:
        all_issues = len([i for i in snapshot.issues if i.state == "closed"])
        reason = f"仓库有 {all_issues} 个已关闭 Issue，但没有足够的相似 Issue 来聚类生成 FAQ（每组需 ≥ 2 个同类型 Issue）" if all_issues > 0 else "仓库暂无已关闭 Issue，无法自动生成 FAQ"
        return FaqAutoGenerateResponse(created=0, entries=[], reason=reason)

    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_api_base_url,
    )
    from app.storage.database import faq_entries, create_database_engine, find_repository_id
    from sqlalchemy import insert

    engine = create_database_engine()
    created = 0
    entries = []

    with engine.connect() as conn:
        repository_id = find_repository_id(conn, owner, name)
    if repository_id is None:
        engine.dispose()
        raise HTTPException(status_code=404, detail="Repository not synced")

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
                        repository_id=repository_id,
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
        except Exception as exc:
            logger.warning("Failed to generate FAQ entry for %s/%s: %s", owner, name, exc)
            continue

    engine.dispose()
    return FaqAutoGenerateResponse(created=created, entries=entries)
