"""Unit tests for webhook handler functions."""

import asyncio
import hashlib
import hmac
from datetime import datetime, timezone

from app.webhooks.handler import (
    WebhookEventRecord,
    dispatch_event,
    handle_issue_event,
    verify_signature,
    webhook_event_store,
)


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------

def test_verify_signature_skipped_when_no_secret():
    """Dev mode: no secret configured → skip verification."""
    assert verify_signature(b"payload", "sha256:anything", secret=None) is True


def test_verify_signature_fails_without_header():
    """Secret is set but no signature header → reject."""
    assert verify_signature(b"payload", signature_header=None, secret="s3cret") is False


def test_verify_signature_wrong_prefix():
    """Header does not start with 'sha256=' → reject."""
    assert verify_signature(b"payload", "md5:abc123", secret="s3cret") is False


def test_verify_signature_correct():
    """Valid HMAC-SHA256 digest → accept."""
    payload = b'{"action":"opened"}'
    secret = "s3cret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    header = f"sha256={digest}"
    assert verify_signature(payload, header, secret) is True


def test_verify_signature_wrong():
    """Digest does not match → reject."""
    assert verify_signature(b"payload", "sha256=0000000000000000000000000000000000000000000000000000000000000000", secret="s3cret") is False


# ---------------------------------------------------------------------------
# handle_issue_event
# ---------------------------------------------------------------------------

def _make_issue_payload(
    action: str = "opened",
    number: int = 1,
    title: str = "Test issue",
    body: str | None = "Some body text",
    labels: list[str] | None = None,
    repo: str = "owner/repo",
) -> dict:
    return {
        "action": action,
        "issue": {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "html_url": f"https://github.com/{repo}/issues/{number}",
            "user": {"login": "testuser"},
            "labels": [{"name": label} for label in (labels or [])],
            "created_at": "2026-07-06T10:00:00Z",
            "updated_at": "2026-07-06T10:00:00Z",
            "comments": 0,
        },
        "repository": {"full_name": repo},
    }


def test_handle_bug_issue():
    """A bug report is correctly classified as BUG."""
    payload = _make_issue_payload(
        number=101,
        title="Crash when saving file",
        body="Getting an exception traceback when saving",
        labels=["bug"],
    )
    record = asyncio.run(handle_issue_event(payload, delivery_id="del-001"))
    assert record is not None
    assert record.event_id == "del-001"
    assert record.action == "opened"
    assert record.repository == "owner/repo"
    assert record.issue_number == 101
    assert record.classification is not None
    assert record.classification.category.value == "bug"
    assert record.classification.confidence >= 0.35


def test_handle_question_issue():
    """A usage question is correctly classified as QUESTION."""
    payload = _make_issue_payload(
        number=102,
        title="How to install this package?",
        body="I need help with setup",
        labels=["question"],
    )
    record = asyncio.run(handle_issue_event(payload, delivery_id="del-002"))
    assert record is not None
    assert record.classification is not None
    assert record.classification.category.value == "question"


def test_handle_issue_ignores_non_opened():
    """Only 'opened', 'closed', and 'reopened' are handled."""
    for action in ("edited", "labeled"):
        payload = _make_issue_payload(action=action, number=103)
        assert asyncio.run(handle_issue_event(payload)) is None, f"action={action} should be ignored"
    # reopened is fully handled (like opened), closed stores event.
    for action in ("closed", "reopened"):
        payload = _make_issue_payload(action=action, number=104)
        result = asyncio.run(handle_issue_event(payload))
        assert result is not None, f"action={action} should be handled"
        assert result.action == action


def test_handle_issue_missing_repo():
    """Missing repository info returns None."""
    payload = {"action": "opened", "issue": {"number": 1, "title": "x"}}
    assert asyncio.run(handle_issue_event(payload)) is None


def test_handle_issue_empty_body_gets_info_needed_boost():
    """An issue with no body and no matching keywords falls back to INFO_NEEDED."""
    payload = _make_issue_payload(
        number=104,
        title="Something is not right",
        body=None,
        labels=[],
    )
    record = asyncio.run(handle_issue_event(payload))
    assert record is not None
    # The classifier gives INFO_NEEDED a boost for empty body.
    assert record.classification is not None


def test_stores_event_in_memory():
    """Event is recorded in the module-level webhook_event_store."""
    prev_count = len(webhook_event_store)
    payload = _make_issue_payload(
        number=200,
        title="Feature: add dark mode",
        body="Would be great to have dark mode support",
        labels=["enhancement"],
    )
    asyncio.run(handle_issue_event(payload, delivery_id="del-store-200"))
    assert len(webhook_event_store) == prev_count + 1
    stored = webhook_event_store.get("del-store-200")
    assert stored is not None
    assert stored.issue_number == 200


# ---------------------------------------------------------------------------
# dispatch_event
# ---------------------------------------------------------------------------

def test_dispatch_issues_event():
    """dispatch_event routes 'issues' events correctly."""
    record = asyncio.run(dispatch_event("issues", _make_issue_payload(number=301), delivery_id="del-301"))
    assert record is not None
    assert record.issue_number == 301


def test_dispatch_unknown_event_returns_none():
    """Unknown event types are silently ignored."""
    for event in ("ping", "push", "pull_request", "star", "watch"):
        record = asyncio.run(dispatch_event(event, {}))
        assert record is None, f"event={event} should return None"


# ---------------------------------------------------------------------------
# WebhookEventRecord dataclass
# ---------------------------------------------------------------------------

def test_record_creation():
    """WebhookEventRecord can be created with minimal fields."""
    now = datetime.now(timezone.utc)
    record = WebhookEventRecord(
        event_id="e-001",
        event_type="issues",
        action="opened",
        repository="o/r",
        issue_number=1,
        classification=None,
        received_at=now,
    )
    assert record.event_id == "e-001"
    assert record.raw_payload == {}  # default factory
