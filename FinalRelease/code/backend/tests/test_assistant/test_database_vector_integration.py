"""Optional end-to-end test for assistant database and vector-store access."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.assistant.tool_registry import RepositoryToolRegistry
from app.schemas.repository import (
    CategorySummary,
    ClassifiedFile,
    FileCategory,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.storage.postgres import PostgresRepositoryStore


requires_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is required for assistant database/vector integration tests.",
)


@requires_database
def test_assistant_reads_postgres_snapshot_and_vector_searches(monkeypatch):
    """Verify assistant tools can read stored source and query pgvector chunks."""
    store = PostgresRepositoryStore()
    owner = f"assistant-db-{uuid4().hex[:8]}"
    snapshot = _make_snapshot(owner)
    store.save(snapshot)

    loaded = store.get(owner, "repo")
    assert loaded is not None

    # The registry normally receives the process-wide store. Replace it here
    # so the test explicitly exercises this PostgreSQL adapter instance.
    import app.assistant.tools as assistant_tools

    monkeypatch.setattr(assistant_tools, "repository_store", store)
    registry = RepositoryToolRegistry()

    source_result = registry.execute(
        "read_file",
        {"path": "app/database.py", "start_line": 1, "end_line": 2},
        loaded,
    )
    vector_result = registry.execute(
        "vector_search",
        {"query": "database connection configuration", "limit": 3},
        loaded,
    )

    assert "DATABASE_URL" in source_result.content
    assert source_result.citations[0].path == "app/database.py"
    assert "database" in vector_result.content.lower()
    assert "No vector results." not in vector_result.content


def _make_snapshot(owner: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        identity=RepositoryIdentity(
            owner=owner,
            name="repo",
            full_name=f"{owner}/repo",
            html_url=f"https://github.com/{owner}/repo",
            default_branch="main",
        ),
        stats=RepositoryStats(primary_language="Python"),
        files=[
            ClassifiedFile(path="app/database.py", category=FileCategory.SOURCE, size=64),
        ],
        source_contents=[
            RepositoryFileContent(
                path="app/database.py",
                category=FileCategory.SOURCE,
                content="DATABASE_URL = 'postgresql://localhost'\nengine = create_engine(DATABASE_URL)",
                size=64,
            ),
        ],
        file_categories=[CategorySummary(category="source_code", count=1)],
        synced_at=datetime.now(timezone.utc),
    )
