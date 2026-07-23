"""Integration tests for the webhook HTTP endpoint."""

import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """FastAPI TestClient without webhook secret (dev mode)."""
    # Reset secret in case a previous fixture (e.g. secured_client) leaked.
    from app.core.config import settings
    settings.github_webhook_secret = None
    app = create_app()
    return TestClient(app)


@pytest.fixture
def clear_store():
    """Clear the in-memory webhook event store."""
    from app.webhooks.handler import webhook_event_store
    webhook_event_store.clear()
    yield
    webhook_event_store.clear()


# ---------------------------------------------------------------------------
# Dev mode (no secret)
# ---------------------------------------------------------------------------

def test_post_github_webhook_dev_mode(client):
    """Dev mode: no secret configured, any payload is accepted."""
    payload = {
        "action": "opened",
        "issue": {
            "title": "Bug: crash",
            "body": "traceback",
            "number": 1,
            "labels": [],
            "html_url": "https://github.com/owner/repo/issues/1",
            "state": "open",
            "user": {"login": "tester"},
            "comments": 0,
        },
        "repository": {"full_name": "other/repo"},
    }
    resp = client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "dev-001"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_webhook_missing_event_header(client):
    """Missing X-GitHub-Event header → 422 (FastAPI validation)."""
    resp = client.post("/api/webhooks/github", json={})
    assert resp.status_code == 422


def test_post_webhook_invalid_json(client):
    """Non-JSON body → 400."""
    resp = client.post(
        "/api/webhooks/github",
        content=b"not json",
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 400


def test_post_webhook_unknown_event(client):
    """Unknown event type is silently accepted (returns 200)."""
    payload = {"action": "opened", "issue": {"number": 1}}
    resp = client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "some_unknown_event", "X-GitHub-Delivery": "unk-001"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Production mode (with secret)
# ---------------------------------------------------------------------------

@pytest.fixture
def secured_client():
    """FastAPI TestClient with a configured webhook secret."""
    from app.core.config import settings
    old_secret = settings.github_webhook_secret
    settings.github_webhook_secret = "mysecret"
    app = create_app()
    yield TestClient(app)
    settings.github_webhook_secret = old_secret  # restore to not leak


def test_post_webhook_correct_signature(secured_client):
    """Valid HMAC-SHA256 signature → 200."""
    payload = b'{"action":"opened","issue":{"title":"Bug","body":"err","number":1},"repository":{"full_name":"o/r"}}'
    secret = "mysecret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    resp = secured_client.post(
        "/api/webhooks/github",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": f"sha256={digest}",
        },
    )
    assert resp.status_code == 200


def test_post_webhook_wrong_signature(secured_client):
    """Invalid HMAC-SHA256 signature → 400."""
    payload = b'{"action":"opened","issue":{"title":"Bug","body":"err","number":1},"repository":{"full_name":"o/r"}}'
    resp = secured_client.post(
        "/api/webhooks/github",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
        },
    )
    assert resp.status_code == 400


def test_post_webhook_missing_signature_with_secret(secured_client):
    """Secret configured but no signature header → 400."""
    payload = {"action": "opened", "issue": {"title": "Bug", "body": "err", "number": 1}}
    resp = secured_client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 400


def test_post_webhook_non_opened_issue_with_secret(secured_client):
    """Non-'opened' actions are accepted (200) but silently ignored."""
    payload = b'{"action":"closed","issue":{"title":"Fixed","body":"done","number":1},"repository":{"full_name":"o/r"}}'
    secret = "mysecret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    resp = secured_client.post(
        "/api/webhooks/github",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": f"sha256={digest}",
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Webhook events list
# ---------------------------------------------------------------------------

def test_list_events_empty(client, clear_store):
    """No events yet → returns an empty list."""
    resp = client.get("/api/webhooks/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_events_after_receiving_issue(client, clear_store):
    """After receiving an issue webhook, the event appears in the list."""
    payload = {
        "action": "opened",
        "issue": {
            "title": "Bug: crash when saving",
            "body": "Getting a traceback error",
            "number": 42,
            "labels": [{"name": "bug"}],
            "state": "open",
            "html_url": "https://github.com/o/r/issues/42",
            "user": {"login": "tester"},
            "created_at": "2026-07-09T10:00:00Z",
            "updated_at": "2026-07-09T10:00:00Z",
            "comments": 0,
        },
        "repository": {"full_name": "o/r"},
    }

    # Post the webhook event first.
    resp = client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "evt-001"},
    )
    assert resp.status_code == 200, f"POST failed: {resp.json()}"

    # Then check the events list.
    resp = client.get("/api/webhooks/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    latest = events[0]
    assert latest["event_id"] == "evt-001"
    assert latest["event_type"] == "issues"
    assert latest["action"] == "opened"
    assert latest["repository"] == "o/r"
    assert latest["issue_number"] == 42
    assert latest["classification"] is not None
    assert latest["classification"]["category"] == "bug"


def test_list_events_respects_limit(client, clear_store):
    """The limit parameter trims the result set."""
    for i in range(5):
        payload = {
            "action": "opened",
            "issue": {"title": f"Issue {i}", "body": "", "number": 100 + i, "labels": []},
            "repository": {"full_name": "o/r"},
        }
        resp = client.post(
            "/api/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": f"evt-limit-{i}"},
        )
        assert resp.status_code == 200, f"POST {i} failed: {resp.json()}"

    resp = client.get("/api/webhooks/events?limit=3")
    assert len(resp.json()) == 3


def test_list_events_ignores_non_issues(client):
    """Non-issue events are not stored (silently ignored)."""
    payload = {"action": "opened", "issue": {"number": 1, "title": "x"}, "repository": {"full_name": "o/r"}}

    # Unknown event → not recorded.
    client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "evt-push-1"},
    )

    resp = client.get("/api/webhooks/events")
    assert resp.json() == []


def test_list_events_non_opened_not_stored(client):
    """Non-'opened' issue actions are not stored."""
    payload = {
        "action": "edited",
        "issue": {"title": "Edited issue", "body": "", "number": 99, "labels": []},
        "repository": {"full_name": "o/r"},
    }
    client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "evt-edit-1"},
    )

    resp = client.get("/api/webhooks/events")
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Event detail endpoint
# ---------------------------------------------------------------------------

def test_get_event_detail_found(client, clear_store):
    """GET /events/{event_id} returns full detail for a stored event."""
    payload = {
        "action": "opened",
        "issue": {
            "title": "Bug: login crash",
            "body": "Error when logging in",
            "number": 7,
            "labels": [{"name": "bug"}],
            "state": "open",
            "html_url": "https://github.com/o/r/issues/7",
            "user": {"login": "testuser"},
            "comments": 3,
        },
        "repository": {"full_name": "o/r"},
    }
    client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "detail-evt-1"},
    )

    resp = client.get("/api/webhooks/events/detail-evt-1")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["event_id"] == "detail-evt-1"
    assert detail["issue_number"] == 7
    assert detail["issue_title"] == "Bug: login crash"
    assert detail["issue_state"] == "open"
    assert detail["issue_author"] == "testuser"
    assert detail["issue_labels"] == ["bug"]
    assert detail["issue_body"] == "Error when logging in"
    assert detail["issue_comments_count"] == 3
    assert detail["issue_html_url"] == "https://github.com/o/r/issues/7"
    assert detail["classification"] is not None
    assert detail["classification"]["category"] == "bug"


def test_get_event_detail_not_found(client, clear_store):
    """GET /events/{event_id} returns 404 for unknown ID."""
    resp = client.get("/api/webhooks/events/nonexistent-id")
    assert resp.status_code == 404


def test_get_event_detail_question_has_suggested_action(client, clear_store):
    """A question issue includes suggested_action and signals in detail."""
    payload = {
        "action": "opened",
        "issue": {
            "title": "How do I configure this?",
            "body": "I can't find the config",
            "number": 8,
            "labels": [{"name": "question"}],
            "state": "open",
            "html_url": "https://github.com/o/r/issues/8",
            "user": {"login": "asker"},
            "comments": 0,
        },
        "repository": {"full_name": "o/r"},
    }
    client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "detail-evt-q"},
    )

    resp = client.get("/api/webhooks/events/detail-evt-q")
    detail = resp.json()
    c = detail["classification"]
    assert c["category"] == "question"
    assert c["suggested_action"] is not None
    assert isinstance(c["signals"], list) and len(c["signals"]) > 0


# ---------------------------------------------------------------------------
# Events list includes new fields
# ---------------------------------------------------------------------------

def test_list_events_includes_title_and_labels(client, clear_store):
    """The events list endpoint now includes issue_title, issue_state, and labels."""
    payload = {
        "action": "opened",
        "issue": {
            "title": "Feature: add dark mode",
            "body": "Would love dark mode",
            "number": 9,
            "labels": [{"name": "enhancement"}],
            "state": "open",
            "html_url": "https://github.com/o/r/issues/9",
            "user": {"login": "user1"},
            "comments": 0,
        },
        "repository": {"full_name": "o/r"},
    }
    client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "title-evt-1"},
    )

    resp = client.get("/api/webhooks/events")
    assert resp.status_code == 200
    events = resp.json()
    matching = [e for e in events if e["event_id"] == "title-evt-1"]
    assert len(matching) == 1
    evt = matching[0]
    assert evt["issue_title"] == "Feature: add dark mode"
    assert evt["issue_state"] == "open"
    assert evt["issue_labels"] == ["enhancement"]
    assert evt["classification"]["suggested_action"] is not None


def test_list_events_non_opened_still_excluded(client, clear_store):
    """Non-'opened' events are still excluded from the list."""
    payload = {
        "action": "closed",
        "issue": {"title": "Already fixed", "body": "", "number": 99, "labels": []},
        "repository": {"full_name": "o/r"},
    }
    client.post(
        "/api/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "evt-closed-1"},
    )

    resp = client.get("/api/webhooks/events")
    ids = [e["event_id"] for e in resp.json()]
    assert "evt-closed-1" not in ids


def test_webhook_config_never_returns_secret(secured_client):
    response = secured_client.get("/api/webhooks/config")
    assert response.status_code == 200
    data = response.json()
    assert data["secret_configured"] is True
    assert "secret" not in data
    assert "mysecret" not in response.text


def test_events_can_be_filtered_and_marked_read(client, clear_store):
    for repository, delivery in (("o/a", "filter-a"), ("o/b", "filter-b")):
        response = client.post(
            "/api/webhooks/github",
            json={
                "action": "opened",
                "issue": {
                    "title": "Bug: crash",
                    "body": "error traceback",
                    "number": 11,
                    "labels": [{"name": "bug"}],
                },
                "repository": {"full_name": repository},
            },
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": delivery},
        )
        assert response.status_code == 200

    events = client.get("/api/webhooks/events?repository=o/a").json()
    assert [event["event_id"] for event in events] == ["filter-a"]
    assert events[0]["is_read"] is False

    response = client.patch("/api/webhooks/events/filter-a?action=read")
    assert response.status_code == 200
    events = client.get("/api/webhooks/events?repository=o/a").json()
    assert events[0]["is_read"] is True


def test_missing_delivery_header_still_gets_usable_event_id(client, clear_store):
    response = client.post(
        "/api/webhooks/github",
        json={
            "action": "opened",
            "issue": {
                "title": "Question about setup",
                "body": "How to install?",
                "number": 12,
                "labels": [{"name": "question"}],
            },
            "repository": {"full_name": "o/r"},
        },
        headers={"X-GitHub-Event": "issues"},
    )
    assert response.status_code == 200
    event = client.get("/api/webhooks/events?repository=o/r").json()[0]
    assert event["event_id"].startswith("local-")
    assert client.get(f"/api/webhooks/events/{event['event_id']}").status_code == 200


def test_approved_reply_is_posted_without_regeneration(client, clear_store, monkeypatch):
    response = client.post(
        "/api/webhooks/github",
        json={
            "action": "opened",
            "issue": {
                "title": "How to configure this?",
                "body": "Please help with configuration",
                "number": 13,
                "labels": [{"name": "question"}],
            },
            "repository": {"full_name": "o/r"},
        },
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "reply-exact"},
    )
    assert response.status_code == 200

    posted: list[str] = []

    async def fake_comment(self, ref, issue_number, body):
        posted.append(body)
        return {"html_url": "https://github.com/o/r/issues/13#comment"}

    from app.services.github_client import GitHubClient
    monkeypatch.setattr(GitHubClient, "comment_on_issue", fake_comment)

    approved = "这是维护者已经检查并确认的回复。"
    response = client.post(
        "/api/webhooks/events/reply-exact/reply",
        json={"reply_text": approved},
    )
    assert response.status_code == 200, response.text
    assert posted == [approved]
    assert response.json()["reply_text"] == approved
    assert response.json()["source"] == "approved_draft"


def test_event_list_recovers_persisted_rows_after_memory_is_cleared(tmp_path):
    from app.core.config import settings
    from app.storage.database import create_database_engine, initialize_database
    from app.webhooks.handler import webhook_event_store

    previous_url = settings.database_url
    previous_llm_key = settings.llm_api_key
    settings.database_url = f"sqlite:///{tmp_path / 'webhooks.sqlite'}"
    settings.llm_api_key = None
    engine = create_database_engine()
    initialize_database(engine)
    engine.dispose()

    try:
        local_client = TestClient(create_app())
        response = local_client.post(
            "/api/webhooks/github",
            json={
                "action": "opened",
                "issue": {
                    "title": "Bug persisted event",
                    "body": "error",
                    "number": 21,
                    "labels": [{"name": "bug"}],
                },
                "repository": {"full_name": "persisted/repo"},
            },
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "persisted-1"},
        )
        assert response.status_code == 200
        webhook_event_store.clear()

        events = local_client.get(
            "/api/webhooks/events?repository=persisted/repo"
        ).json()
        assert [event["event_id"] for event in events] == ["persisted-1"]
        detail = local_client.get("/api/webhooks/events/persisted-1")
        assert detail.status_code == 200
        assert detail.json()["issue_number"] == 21
    finally:
        webhook_event_store.clear()
        settings.database_url = previous_url
        settings.llm_api_key = previous_llm_key
