"""Tests for the FAQ auto-generate endpoint response."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from app.core.config import settings
from app.schemas.issue import GitHubIssue, IssueCategory, IssueClassification
from app.schemas.repository import (
    ClassifiedFile, FileCategory, CategorySummary,
    RepositorySnapshot, RepositoryIdentity, RepositoryStats,
)
from app.storage import repository_store


def test_faq_generate_reason_no_issues():
    """Returns reason when no closed issues exist."""
    owner, name = "o", "r"
    snap = RepositorySnapshot(
        identity=RepositoryIdentity(
            owner=owner, name=name, full_name=f"{owner}/{name}",
            html_url=f"https://github.com/{owner}/{name}", default_branch="main",
        ),
        description="",
        stats=RepositoryStats(),
        files=[ClassifiedFile(path="a.py", category=FileCategory.SOURCE, size=10)],
        file_categories=[CategorySummary(category="source_code", count=1)],
        issues=[], pull_requests=[], recent_commits=[],
        synced_at=datetime.now(timezone.utc),
    )
    repository_store.save(snap)

    from app.api.routes.faq import auto_generate_faq
    result = asyncio.run(auto_generate_faq(owner, name))
    assert result.created == 0
    assert result.reason
    assert "暂无已关闭 Issue" in result.reason


def test_faq_generate_reason_insufficient():
    """Returns reason when closed issues are too few to cluster."""
    owner, name = "o2", "r2"
    c = IssueClassification(
        category=IssueCategory.BUG, confidence=0.9,
        reason="", suggested_action="", signals=[],
    )
    snap = RepositorySnapshot(
        identity=RepositoryIdentity(
            owner=owner, name=name, full_name=f"{owner}/{name}",
            html_url=f"https://github.com/{owner}/{name}", default_branch="main",
        ),
        description="",
        stats=RepositoryStats(),
        files=[ClassifiedFile(path="a.py", category=FileCategory.SOURCE, size=10)],
        file_categories=[CategorySummary(category="source_code", count=1)],
        issues=[
            GitHubIssue(number=1, title="Bug A", state="closed",
                        html_url=f"https://github.com/o2/r2/issues/1",
                        labels=[], classification=c),
            GitHubIssue(number=2, title="Feature B", state="closed",
                        html_url=f"https://github.com/o2/r2/issues/2",
                        labels=[], classification=c),
        ],
        pull_requests=[], recent_commits=[],
        synced_at=datetime.now(timezone.utc),
    )
    repository_store.save(snap)

    from app.api.routes.faq import auto_generate_faq
    result = asyncio.run(auto_generate_faq(owner, name))
    assert result.created == 0
    assert result.reason
