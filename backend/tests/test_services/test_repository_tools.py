"""Tests for the repository tool endpoints (file-contents, etc.)."""

from datetime import datetime, timezone

from app.schemas.repository import (
    CategorySummary,
    ClassifiedFile,
    FileCategory,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.storage import repository_store


def test_get_file_contents_empty_when_not_synced():
    """A repo that was never synced returns an empty list."""
    contents = repository_store.get_file_contents("nonexistent", "repo")
    assert contents == []


def test_get_file_contents_returns_source_files():
    """After sync with source_contents, get_file_contents returns them."""
    snapshot = _make_snapshot_with_contents()
    repository_store.save(snapshot)

    contents = repository_store.get_file_contents("owner", "repo")
    assert len(contents) == 2

    paths = [c["path"] for c in contents]
    assert "app/main.py" in paths
    assert "app/config.py" in paths

    main_content = next(c for c in contents if c["path"] == "app/main.py")
    assert "from fastapi import FastAPI" in main_content["content"]
    assert main_content["truncated"] is False


def test_get_file_content_by_path():
    """get_file_content returns a single file by path."""
    snapshot = _make_snapshot_with_contents()
    repository_store.save(snapshot)

    result = repository_store.get_file_content("owner", "repo", "app/config.py")
    assert result is not None
    assert "DATABASE_URL" in result["content"]


def test_get_file_content_nonexistent_path():
    """get_file_content returns None for a missing path."""
    snapshot = _make_snapshot_with_contents()
    repository_store.save(snapshot)

    result = repository_store.get_file_content("owner", "repo", "missing.py")
    assert result is None


def _make_snapshot_with_contents() -> RepositorySnapshot:
    return RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="owner",
            name="repo",
            full_name="owner/repo",
            html_url="https://github.com/owner/repo",
            default_branch="main",
        ),
        description="Test repo",
        stats=RepositoryStats(primary_language="Python"),
        files=[
            ClassifiedFile(path="app/main.py", category=FileCategory.SOURCE, size=60),
            ClassifiedFile(path="app/config.py", category=FileCategory.SOURCE, size=80),
        ],
        source_contents=[
            RepositoryFileContent(
                path="app/main.py",
                category=FileCategory.SOURCE,
                content="from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef read_root():\n    return {'hello': 'world'}",
                size=60,
                truncated=False,
            ),
            RepositoryFileContent(
                path="app/config.py",
                category=FileCategory.SOURCE,
                content="DATABASE_URL = 'postgresql://localhost'\nSECRET_KEY = 'secret'",
                size=80,
                truncated=False,
            ),
        ],
        file_categories=[CategorySummary(category="source_code", count=2)],
        issues=[],
        pull_requests=[],
        recent_commits=[],
        issue_categories=[],
        synced_at=datetime.now(timezone.utc),
    )
