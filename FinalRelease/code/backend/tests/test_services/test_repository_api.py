"""Public repository API response tests."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.repository import (
    ClassifiedFile,
    FileCategory,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.storage import repository_store


def test_cached_snapshot_response_does_not_include_source_bodies():
    snapshot = RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="api-response",
            name="repo",
            full_name="api-response/repo",
            html_url="https://github.com/api-response/repo",
            default_branch="main",
        ),
        stats=RepositoryStats(primary_language="Python"),
        files=[
            ClassifiedFile(path="app.py", category=FileCategory.SOURCE, size=14),
        ],
        source_contents=[
            RepositoryFileContent(
                path="app.py",
                category=FileCategory.SOURCE,
                content="SECRET_SOURCE_BODY",
                size=18,
            ),
        ],
        synced_at=datetime.now(timezone.utc),
    )
    repository_store.save(snapshot)

    response = TestClient(create_app()).get(
        "/api/repositories/api-response/repo"
    )
    assert response.status_code == 200
    assert "source_contents" not in response.json()
    assert "SECRET_SOURCE_BODY" not in response.text
    assert response.json()["files"][0]["path"] == "app.py"
