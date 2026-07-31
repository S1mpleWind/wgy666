"""Optional PostgreSQL storage integration test."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.issue import GitHubIssue, IssueCategory, IssueClassification
from app.schemas.repository import (
    CategorySummary,
    ClassifiedFile,
    CommitSummary,
    FileCategory,
    PullRequestSummary,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.storage.postgres import PostgresRepositoryStore


requires_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is required for PostgreSQL storage integration tests.",
)


@requires_database
def test_postgres_store_saves_and_loads_repository_snapshot():
    store = PostgresRepositoryStore()
    owner = f"db-test-{uuid4().hex[:8]}"
    snapshot = _make_snapshot(owner=owner, name="repo")

    store.save(snapshot)
    loaded = store.get(owner, "repo")

    assert loaded is not None
    assert loaded.identity.full_name == f"{owner}/repo"
    assert len(loaded.files) == 2
    assert len(loaded.issues) == 1
    assert len(loaded.pull_requests) == 1
    assert len(loaded.recent_commits) == 1
    assert any(item.full_name == f"{owner}/repo" for item in store.list())


def _make_snapshot(owner: str, name: str) -> RepositorySnapshot:
    classification = IssueClassification(
        category=IssueCategory.BUG,
        confidence=0.91,
        reason="sample bug signal",
        suggested_action="investigate startup path",
        signals=["bug:error"],
    )
    full_name = f"{owner}/{name}"
    return RepositorySnapshot(
        identity=RepositoryIdentity(
            owner=owner,
            name=name,
            full_name=full_name,
            html_url=f"https://github.com/{full_name}",
            default_branch="main",
        ),
        description="Database integration test repository.",
        stats=RepositoryStats(
            stars=1,
            forks=0,
            watchers=1,
            open_issues=1,
            size_kb=12,
            primary_language="Python",
            languages={"Python": 100},
        ),
        topics=["database", "test"],
        readme="# Demo\n\nPostgreSQL integration sample.",
        files=[
            ClassifiedFile(path="README.md", category=FileCategory.DOCUMENTATION, size=32),
            ClassifiedFile(path="app/main.py", category=FileCategory.SOURCE, size=128),
        ],
        file_categories=[
            CategorySummary(category="documentation", count=1),
            CategorySummary(category="source_code", count=1),
        ],
        issues=[
            GitHubIssue(
                number=1,
                title="Bug: sample issue",
                state="open",
                html_url=f"https://github.com/{full_name}/issues/1",
                author="tester",
                labels=["bug"],
                comments=0,
                classification=classification,
            )
        ],
        issue_categories=[CategorySummary(category="bug", count=1)],
        pull_requests=[
            PullRequestSummary(
                number=2,
                title="Sample PR",
                state="open",
                html_url=f"https://github.com/{full_name}/pull/2",
            )
        ],
        recent_commits=[
            CommitSummary(
                sha="abc123",
                message="sample commit",
                html_url=f"https://github.com/{full_name}/commit/abc123",
            )
        ],
        synced_at=datetime.now(timezone.utc),
    )
