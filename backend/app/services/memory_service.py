"""Long-term fix memory — log and retrieve historical fix patterns."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from collections import Counter


_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "this", "that", "it", "its", "and", "or", "not", "do", "does",
    "did", "will", "would", "could", "should", "may", "can",
}


async def log_fix_memory(
    owner: str,
    name: str,
    issue_title: str,
    issue_category: str,
    issue_body: str | None,
    files_changed: list[str],
    fix_summary: str,
) -> None:
    """Record a fix into long-term memory."""
    from app.storage.database import fix_memory_logs, create_database_engine
    from app.core.config import settings
    from sqlalchemy import insert

    if not settings.database_url:
        return

    text = f"{issue_title} {issue_body or ''}".lower()
    keywords = sorted(_extract_keywords(text))

    engine = create_database_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(fix_memory_logs).values(
                    repository_id=None,  # Will be resolved later
                    issue_title=issue_title,
                    issue_category=issue_category,
                    issue_keywords=keywords,
                    files_changed=files_changed,
                    fix_summary=fix_summary,
                    pattern_type=_infer_pattern(fix_summary),
                    pattern_detail=fix_summary,
                    created_at=datetime.now(timezone.utc),
                )
            )
    except Exception:
        pass
    finally:
        engine.dispose()


async def get_similar_fixes(
    owner: str,
    name: str,
    issue_title: str,
    issue_body: str | None,
    limit: int = 3,
) -> list[dict]:
    """Retrieve similar past fixes to inject into the LLM prompt."""
    from app.storage.database import fix_memory_logs, create_database_engine
    from app.core.config import settings
    from sqlalchemy import select, text

    if not settings.database_url:
        return []

    query_kws = _extract_keywords(f"{issue_title} {issue_body or ''}")
    if not query_kws:
        return []

    engine = create_database_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(
                    fix_memory_logs.c.issue_title,
                    fix_memory_logs.c.issue_category,
                    fix_memory_logs.c.issue_keywords,
                    fix_memory_logs.c.files_changed,
                    fix_memory_logs.c.fix_summary,
                    fix_memory_logs.c.pattern_type,
                ),
            ).mappings().all()

        scored = []
        for row in rows:
            entry_kws = set(row["issue_keywords"] or [])
            overlap = len(query_kws & entry_kws)
            if overlap > 0:
                scored.append((overlap, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "title": row["issue_title"],
                "category": row["issue_category"],
                "files": row["files_changed"],
                "summary": row["fix_summary"],
                "pattern": row["pattern_type"],
            }
            for _, row in scored[:limit]
        ]
    finally:
        engine.dispose()


def _extract_keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9_\-.]+|[一-鿿]+", text.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOP_WORDS}


def _infer_pattern(summary: str) -> str:
    """Rough pattern classification from fix summary text."""
    summary_lower = summary.lower()
    if any(w in summary_lower for w in ["null", "none", "empty", "optional"]):
        return "null_check"
    if any(w in summary_lower for w in ["try", "except", "catch", "error", "exception"]):
        return "error_handling"
    if any(w in summary_lower for w in ["import", "version", "deprecat"]):
        return "dependency_update"
    if any(w in summary_lower for w in ["perf", "slow", "cache", "timeout"]):
        return "performance"
    if any(w in summary_lower for w in ["refactor", "rename", "extract", "split"]):
        return "refactor"
    return "bugfix"
