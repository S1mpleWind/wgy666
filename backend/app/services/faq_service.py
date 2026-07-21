"""FAQ knowledge base — match frequent issues, answer without LLM."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.embeddings import EmbeddingService


# Common stop words to ignore when building keyword sets.
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "this", "that", "it", "its", "and", "or", "not", "do", "does",
    "did", "will", "would", "could", "should", "may", "can",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
    "它", "们", "什么", "怎么", "如何", "为什么", "哪个", "吗", "吧",
}


async def faq_match(
    title: str,
    body: str | None,
    owner: str,
    name: str,
) -> dict | None:
    """Search the FAQ knowledge base for a matching entry.

    Returns the FAQ entry dict if a match is found, or None.

    Two-stage matching:
    1. Keyword overlap — fast pre-filter.
    2. Vector similarity — accurate re-rank.
    """
    from app.storage.database import faq_entries, create_database_engine
    from app.core.config import settings
    from sqlalchemy import select, text

    if not settings.database_url:
        return None

    text_content = f"{title} {body or ''}".lower()
    query_keywords = _extract_keywords(text_content)
    if not query_keywords:
        return None

    engine = create_database_engine()
    embedding = EmbeddingService().embed_query(text_content)

    try:
        with engine.connect() as conn:
            # Vector similarity search (PostgreSQL only).
            dialect = conn.dialect.name
            if dialect == "postgresql":
                rows = conn.execute(
                    text(
                        """
                        SELECT id, question, answer, hit_count,
                               1 - (embedding <=> CAST(:query AS vector)) AS score
                        FROM faq_entries
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> CAST(:query AS vector)
                        LIMIT 1
                        """
                    ),
                    {"query": "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"},
                ).mappings().all()

                if rows and rows[0]["score"] >= 0.8:
                    row = rows[0]
                    # Increment hit count.
                    conn.execute(
                        text("UPDATE faq_entries SET hit_count = hit_count + 1 WHERE id = :id"),
                        {"id": row["id"]},
                    )
                    conn.commit()
                    return {
                        "id": row["id"],
                        "question": row["question"],
                        "answer": row["answer"],
                        "score": float(row["score"]),
                        "source": "faq_vector",
                    }

            # Keyword fallback.
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
                overlap = len(query_keywords & entry_kws)
                if overlap >= 2 or (overlap >= 1 and len(query_keywords) <= 2):
                    conn.execute(
                        text("UPDATE faq_entries SET hit_count = hit_count + 1 WHERE id = :id"),
                        {"id": row["id"]},
                    )
                    conn.commit()
                    return {
                        "id": row["id"],
                        "question": row["question"],
                        "answer": row["answer"],
                        "score": overlap / max(len(entry_kws), 1),
                        "source": "faq_keyword",
                    }

    except Exception:
        return None
    finally:
        engine.dispose()

    return None


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text."""
    tokens = re.findall(r"[a-zA-Z0-9_\-.]+|[一-鿿]+", text.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOP_WORDS}
