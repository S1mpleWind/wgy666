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
        "issue": {"title": "Bug: crash", "body": "traceback", "number": 1, "labels": []},
        "repository": {"full_name": "owner/repo"},
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
