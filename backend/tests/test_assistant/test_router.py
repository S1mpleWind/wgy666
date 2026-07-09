"""HTTP tests for the repository assistant endpoint."""

from datetime import datetime, timezone
import os

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
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
from app.storage import repository_store


def _save_sample_snapshot() -> None:
    classification = IssueClassification(
        category=IssueCategory.BUG,
        confidence=0.95,
        reason="Matched bug signal.",
        suggested_action="Investigate and fix.",
        signals=["bug:error"],
    )
    snapshot = RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="agent-test",
            name="repo",
            full_name="agent-test/repo",
            html_url="https://github.com/agent-test/repo",
            default_branch="main",
        ),
        description="A sample repository for assistant tests.",
        stats=RepositoryStats(
            stars=7,
            forks=2,
            open_issues=1,
            primary_language="Python",
            languages={"Python": 1000, "TypeScript": 300},
        ),
        topics=["assistant", "issues"],
        readme="# Sample\n\n## Install\n\nRun uv sync.\n\n## Test\n\nRun pytest.",
        files=[
            ClassifiedFile(path="backend/main.py", category=FileCategory.SOURCE),
            ClassifiedFile(path="backend/tests/test_main.py", category=FileCategory.TEST),
            ClassifiedFile(path="pyproject.toml", category=FileCategory.DEPENDENCY),
            ClassifiedFile(path="README.md", category=FileCategory.DOCUMENTATION),
        ],
        file_categories=[
            CategorySummary(category="source_code", count=1),
            CategorySummary(category="tests", count=1),
            CategorySummary(category="dependency", count=1),
            CategorySummary(category="documentation", count=1),
        ],
        issues=[
            GitHubIssue(
                number=42,
                title="Bug: crash on startup",
                state="open",
                html_url="https://github.com/agent-test/repo/issues/42",
                author="octo",
                labels=["bug"],
                comments=1,
                classification=classification,
            )
        ],
        issue_categories=[CategorySummary(category="bug", count=1)],
        pull_requests=[
            PullRequestSummary(
                number=9,
                title="Improve docs",
                state="open",
                html_url="https://github.com/agent-test/repo/pull/9",
            )
        ],
        recent_commits=[
            CommitSummary(
                sha="abc123",
                message="Initial agent harness",
                html_url="https://github.com/agent-test/repo/commit/abc123",
            )
        ],
        synced_at=datetime.now(timezone.utc),
    )
    repository_store.save(snapshot)


requires_llm_api = pytest.mark.skipif(
    not os.getenv("LLM_API_KEY"),
    reason="LLM_API_KEY is required for real assistant API integration tests.",
)


@requires_llm_api
def test_assistant_lists_bug_issues_from_cached_repository():
    _save_sample_snapshot()
    client = TestClient(create_app())

    response = client.post(
        "/api/assistant/chat",
        json={
            "owner": "agent-test",
            "name": "repo",
            "message": "最近有哪些 bug issue？",
            "freshness": "cache_first",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["repository"] == "agent-test/repo"
    assert payload["used_cached_data"] is True
    assert payload["answer"]
    assert any(tool["name"] == "list_issues" for tool in payload["tool_calls"])
    assert any(citation["type"] == "issue" for citation in payload["citations"])


@requires_llm_api
def test_assistant_returns_project_structure_tool_result():
    _save_sample_snapshot()
    client = TestClient(create_app())

    response = client.post(
        "/api/assistant/chat",
        json={
            "owner": "agent-test",
            "name": "repo",
            "message": "这个项目结构是什么？入口和测试在哪里？",
            "freshness": "cache_first",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    tool_names = [tool["name"] for tool in payload["tool_calls"]]
    assert payload["answer"]
    assert set(tool_names) & {"search_files", "project_structure"}


def test_repository_tool_endpoint_lists_files():
    _save_sample_snapshot()
    client = TestClient(create_app())

    response = client.get(
        "/api/repositories/agent-test/repo/tools/files",
        params={"category": "tests", "freshness": "cache_first"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["used_cached_data"] is True
    assert payload["files"][0]["path"] == "backend/tests/test_main.py"


@requires_llm_api
def test_assistant_chat_uses_real_llm_api_when_configured():
    _save_sample_snapshot()
    client = TestClient(create_app())

    response = client.post(
        "/api/assistant/chat",
        json={
            "owner": "agent-test",
            "name": "repo",
            "message": "这个仓库最近有哪些 bug issue？",
            "freshness": "cache_first",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["repository"] == "agent-test/repo"
    assert payload["tool_calls"]
    assert payload["citations"]
    assert payload["answer"]
