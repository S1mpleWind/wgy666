"""FAQ knowledge base — match frequent issues, answer without full LLM agent."""

from __future__ import annotations

import re
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.services.embeddings import EmbeddingService

# Common stop words to ignore when building keyword sets.
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "this", "that", "it", "its", "and", "or", "not", "do", "does",
    "did", "will", "would", "could", "should", "may", "can",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
    "它", "们", "什么", "怎么", "如何", "为什么", "哪个", "吗", "吧",
})


async def faq_match(
    title: str,
    body: str | None,
    owner: str,
    name: str,
) -> dict | None:
    """Search the FAQ knowledge base. Returns a matching entry or None.

    Three-stage pipeline:
    1. Vector similarity — fetch candidates (PostgreSQL only).
    2. LLM judgement — ask a lightweight LLM call if the issue matches.
    3. Keyword fallback — when vector is unavailable or LLM fails.
    """
    from app.storage.database import faq_entries, create_database_engine
    from sqlalchemy import select, text

    if not settings.database_url:
        return None

    text_content = f"{title} {body or ''}".lower()
    engine = create_database_engine()

    try:
        with engine.connect() as conn:
            dialect = conn.dialect.name
            candidates: list[dict] = []

            # ── Stage 1: vector candidates ────────────────────────────
            if dialect == "postgresql":
                embedding = EmbeddingService().embed_query(text_content)
                rows = conn.execute(
                    text(
                        """SELECT id, question, answer, hit_count,
                                  1 - (embedding <=> CAST(:q AS vector)) AS score
                           FROM faq_entries
                           WHERE embedding IS NOT NULL AND is_confirmed = TRUE
                           ORDER BY embedding <=> CAST(:q AS vector)
                           LIMIT 3"""
                    ),
                    {"q": "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"},
                ).mappings().all()
                for r in rows:
                    if float(r["score"]) >= 0.7:
                        candidates.append(dict(r))

            # ── Stage 2: LLM judgement on candidates ──────────────────
            if candidates and settings.llm_api_key:
                match = await _llm_confirm(text_content, candidates)
                if match:
                    _hit(conn, match["id"])
                    conn.commit()
                    engine.dispose()
                    return match

            # ── Stage 3: keyword fallback ─────────────────────────────
            query_kws = _extract_keywords(text_content)
            if query_kws:
                all_entries = conn.execute(
                    select(
                        faq_entries.c.id, faq_entries.c.question,
                        faq_entries.c.answer, faq_entries.c.keywords,
                        faq_entries.c.hit_count,
                    ).where(faq_entries.c.is_confirmed == True)  # noqa: E712
                ).mappings().all()

                for row in all_entries:
                    entry_kws = set(row["keywords"] or [])
                    if not entry_kws:
                        continue
                    overlap = len(query_kws & entry_kws)
                    if overlap >= 2 or (overlap >= 1 and len(query_kws) <= 2):
                        _hit(conn, row["id"])
                        conn.commit()
                        engine.dispose()
                        return {
                            "id": row["id"],
                            "question": row["question"],
                            "answer": row["answer"],
                            "score": overlap / max(len(entry_kws), 1),
                            "source": "faq_keyword",
                        }

    except Exception:
        pass
    finally:
        engine.dispose()

    return None


async def _llm_confirm(query: str, candidates: list[dict]) -> dict | None:
    """Ask the LLM whether any FAQ candidate matches the incoming issue."""
    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_api_base_url,
    )
    items = "\n".join(
        f"FAQ #{i+1}: {c['question']}" for i, c in enumerate(candidates)
    )
    prompt = (
        f"新 Issue: {query[:200]}\n\n"
        f"已有的 FAQ 条目:\n{items}\n\n"
        "这个新 Issue 和上面哪个 FAQ 是同一个问题？"
        "如果匹配，回答 ONLY 编号 (1,2,3)；如果不匹配，回答 'none'。"
    )

    try:
        completion = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": "You match FAQ entries. Reply with only '1', '2', '3', or 'none'."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=10,
        )
        answer = (completion.choices[0].message.content or "").strip().lower()
        if answer in ("1", "2", "3"):
            idx = int(answer) - 1
            if idx < len(candidates):
                return {
                    "id": candidates[idx]["id"],
                    "question": candidates[idx]["question"],
                    "answer": candidates[idx]["answer"],
                    "score": float(candidates[idx]["score"]),
                    "source": "faq_llm",
                }
    except Exception:
        pass
    return None


def _hit(conn, faq_id: int) -> None:
    """Increment hit count for a FAQ entry."""
    from sqlalchemy import text
    conn.execute(
        text("UPDATE faq_entries SET hit_count = hit_count + 1 WHERE id = :id"),
        {"id": faq_id},
    )


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text."""
    tokens = re.findall(r"[a-zA-Z0-9_\-.]+|[一-鿿]+", text.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOP_WORDS}
