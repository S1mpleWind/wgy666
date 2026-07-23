"""Repository isolation tests for FAQ and long-term fix memory."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from app.core.config import settings
from app.main import create_app
from app.services.faq_service import faq_match
from app.services.memory_service import get_similar_fixes, log_fix_memory
from app.storage.database import (
    create_database_engine,
    faq_entries,
    fix_memory_logs,
    initialize_database,
    repositories,
)


@pytest.fixture
def repository_database(tmp_path):
    previous_url = settings.database_url
    previous_llm_key = settings.llm_api_key
    settings.database_url = f"sqlite:///{tmp_path / 'faq-memory.sqlite'}"
    settings.llm_api_key = None

    engine = create_database_engine()
    initialize_database(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        for owner, name in (("team-a", "repo-a"), ("team-b", "repo-b")):
            connection.execute(
                insert(repositories).values(
                    owner=owner,
                    name=name,
                    full_name=f"{owner}/{name}",
                    html_url=f"https://github.com/{owner}/{name}",
                    default_branch="main",
                    description=None,
                    primary_language="Python",
                    stars=0,
                    forks=0,
                    watchers=0,
                    open_issues=0,
                    size_kb=1,
                    languages={"Python": 1},
                    topics=[],
                    synced_at=now,
                )
            )
    engine.dispose()

    yield TestClient(create_app())

    settings.database_url = previous_url
    settings.llm_api_key = previous_llm_key


def test_faq_crud_is_scoped_to_repository(repository_database):
    client = repository_database
    response = client.post(
        "/api/faq?owner=team-a&name=repo-a",
        json={
            "question": "How to configure the webhook secret?",
            "answer": "Set GITHUB_WEBHOOK_SECRET in the backend environment.",
        },
    )
    assert response.status_code == 201, response.text
    faq_id = response.json()["id"]

    list_a = client.get("/api/faq?owner=team-a&name=repo-a")
    list_b = client.get("/api/faq?owner=team-b&name=repo-b")
    assert [entry["id"] for entry in list_a.json()] == [faq_id]
    assert list_b.json() == []

    cross_repository_delete = client.delete(
        f"/api/faq/{faq_id}?owner=team-b&name=repo-b"
    )
    assert cross_repository_delete.status_code == 404


def test_faq_matching_does_not_cross_repositories(repository_database):
    client = repository_database
    response = client.post(
        "/api/faq?owner=team-a&name=repo-a",
        json={
            "question": "webhook secret configuration",
            "answer": "Configure the secret on the server.",
            "keywords": ["webhook", "secret", "configuration"],
        },
    )
    assert response.status_code == 201

    match_a = asyncio.run(
        faq_match("webhook secret configuration", None, "team-a", "repo-a")
    )
    match_b = asyncio.run(
        faq_match("webhook secret configuration", None, "team-b", "repo-b")
    )
    assert match_a is not None
    assert match_b is None


def test_fix_memory_is_persisted_and_scoped(repository_database):
    asyncio.run(
        log_fix_memory(
            owner="team-a",
            name="repo-a",
            issue_title="Crash during login",
            issue_category="bug",
            issue_body="Login raises an exception",
            files_changed=["app/login.py"],
            fix_summary="Validate the session before reading the user.",
        )
    )

    engine = create_database_engine()
    try:
        with engine.connect() as connection:
            rows = connection.execute(select(fix_memory_logs)).mappings().all()
        assert len(rows) == 1
        assert rows[0]["repository_id"] is not None
    finally:
        engine.dispose()

    matches_a = asyncio.run(
        get_similar_fixes("team-a", "repo-a", "Login crash", "exception")
    )
    matches_b = asyncio.run(
        get_similar_fixes("team-b", "repo-b", "Login crash", "exception")
    )
    assert len(matches_a) == 1
    assert matches_a[0]["files"] == ["app/login.py"]
    assert matches_b == []


def test_faq_rows_always_have_repository_id(repository_database):
    client = repository_database
    response = client.post(
        "/api/faq?owner=team-a&name=repo-a",
        json={"question": "Question", "answer": "Answer"},
    )
    assert response.status_code == 201

    engine = create_database_engine()
    try:
        with engine.connect() as connection:
            row = connection.execute(select(faq_entries)).mappings().one()
        assert row["repository_id"] is not None
    finally:
        engine.dispose()
