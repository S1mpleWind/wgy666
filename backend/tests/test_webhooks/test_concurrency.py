"""Concurrency and stress tests for webhook handling.

Uses rapid sequential requests via synchronous TestClient to simulate
concurrent load. All tests run against the in-memory store.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.webhooks.handler import webhook_event_store


@pytest.fixture(autouse=True)
def _clear_store():
    webhook_event_store.clear()
    yield
    webhook_event_store.clear()


@pytest.fixture
def client():
    from app.core.config import settings
    _key = settings.llm_api_key
    _secret = settings.github_webhook_secret
    _db = settings.database_url
    settings.github_webhook_secret = None
    settings.database_url = None
    settings.llm_api_key = None
    import os
    os.environ.pop("DATABASE_URL", None)
    import importlib
    import app.storage
    importlib.reload(app.storage)
    app = create_app()
    yield TestClient(app)
    settings.llm_api_key = _key
    settings.github_webhook_secret = _secret
    settings.database_url = _db


def _payload(number: int, repo: str = "owner/repo") -> dict:
    return {
        "action": "opened",
        "issue": {"title": f"T{number}", "body": f"B{number}",
                  "number": number, "state": "open",
                  "html_url": f"https://github.com/{repo}/issues/{number}",
                  "user": {"login": "t"}, "comments": 0},
        "repository": {"full_name": repo},
    }


def test_rapid_webhooks_same_repo(client):
    """10 rapid events for the same repo → no crash."""
    for i in range(10):
        resp = client.post(
            "/api/webhooks/github", json=_payload(100 + i, "same/repo"),
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": f"same-{i}"},
        )
        assert resp.status_code == 200

    resp = client.get("/api/webhooks/events?limit=20")
    events = resp.json()
    same = [e for e in events if e["repository"] == "same/repo"]
    assert len(same) == 10


def test_interleaved_read_write(client):
    """Reads interleaved with writes do not conflict."""
    for i in range(5):
        client.post(
            "/api/webhooks/github", json=_payload(200 + i, "inter/repo"),
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": f"int-{i}"},
        )
        resp = client.get("/api/webhooks/events?limit=10")
        assert resp.status_code == 200

    resp = client.get("/api/webhooks/events?limit=20")
    assert len(resp.json()) == 5


def test_dedup_by_delivery_id(client):
    """Same delivery_id overwrites, not duplicates."""
    p = _payload(300, "dedup/repo")
    h = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "dup-id"}
    assert client.post("/api/webhooks/github", json=p, headers=h).status_code == 200
    assert client.post("/api/webhooks/github", json=p, headers=h).status_code == 200

    resp = client.get("/api/webhooks/events?limit=10")
    dup = [e for e in resp.json() if e["event_id"] == "dup-id"]
    assert len(dup) == 1


def test_missing_event_header_422(client):
    """Missing X-GitHub-Event → 422."""
    resp = client.post("/api/webhooks/github", json={"action": "opened"})
    assert resp.status_code == 422
