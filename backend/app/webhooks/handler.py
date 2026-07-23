import hashlib
import hmac
import logging
from uuid import uuid4
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.schemas.issue import IssueClassification
from app.schemas.repository import CategorySummary, GitHubIssue
from app.services.issue_classifier import IssueClassifier
from app.storage import repository_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------

@dataclass
class WebhookEventRecord:
    """A single webhook event received from GitHub."""
    event_id: str
    event_type: str
    action: str
    repository: str
    issue_number: int
    issue_title: str = ""
    issue_state: str = "open"
    issue_labels: list[str] = field(default_factory=list)
    issue_author: str | None = None
    classification: IssueClassification | None = None
    is_read: bool = False
    is_deleted: bool = False
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict = field(default_factory=dict)


# Module-level in-memory store for webhook events.
# Follows the same simple-interface pattern as InMemoryRepositoryStore.
webhook_event_store: dict[str, WebhookEventRecord] = {}


def _persist_event(record: WebhookEventRecord) -> None:
    """Write a webhook event to the database when available."""
    engine = None
    try:
        from app.storage.database import webhook_events
        from app.core.config import settings
        from sqlalchemy import insert, select, update

        if not settings.database_url:
            return

        from app.storage.database import create_database_engine
        engine = create_database_engine()
        values = {
            "event_id": record.event_id,
            "event_type": record.event_type,
            "action": record.action,
            "repository": record.repository,
            "issue_number": record.issue_number,
            "issue_title": record.issue_title,
            "issue_state": record.issue_state,
            "issue_labels": record.issue_labels,
            "issue_author": record.issue_author,
            "classification_json": (
                record.classification.model_dump(mode="json")
                if record.classification else None
            ),
            "raw_payload": record.raw_payload,
            "is_read": record.is_read,
            "is_deleted": record.is_deleted,
            "received_at": record.received_at,
        }
        with engine.begin() as conn:
            existing = conn.execute(
                select(webhook_events.c.id).where(
                    webhook_events.c.event_id == record.event_id
                )
            ).first()
            if existing is None:
                conn.execute(insert(webhook_events).values(**values))
            else:
                update_values = {
                    key: value for key, value in values.items()
                    if key not in {"event_id", "is_read", "is_deleted"}
                }
                conn.execute(
                    update(webhook_events)
                    .where(webhook_events.c.event_id == record.event_id)
                    .values(**update_values)
                )
    except Exception as exc:
        logger.warning("Failed to persist webhook event %s: %s", record.event_id, exc)
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def verify_signature(payload: bytes, signature_header: str | None, secret: str | None) -> bool:
    """Verify the X-Hub-Signature-256 header against the raw request body.

    Returns True when:
    - No secret is configured (dev mode, skip verification).
    - The signature matches.
    Returns False when the header is missing or the digest does not match.
    """
    if not secret:
        return True  # dev mode — skip verification
    if not signature_header:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    expected_digest = signature_header[len(prefix):]
    computed_digest = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_digest, expected_digest)


# ---------------------------------------------------------------------------
# Event dispatch
# ---------------------------------------------------------------------------

async def dispatch_event(event: str, payload: dict, delivery_id: str | None = None) -> WebhookEventRecord | None:
    """Route a webhook event to the appropriate handler based on event type.

    Returns the WebhookEventRecord if the event was handled, None otherwise.
    """
    if event == "issues":
        return await handle_issue_event(payload, delivery_id)

    # Unknown event type — silently ignore (GitHub sends many event types).
    return None


# ---------------------------------------------------------------------------
# Issue event handler
# ---------------------------------------------------------------------------

async def handle_issue_event(payload: dict, delivery_id: str | None = None) -> WebhookEventRecord | None:
    """Process an 'issues' webhook event.

    Only acts on ``action == "opened"`` — classifies the issue using the
    rule-based classifier, records the event, and updates the in-memory
    repository snapshot if the repo has been synced.
    """
    action = payload.get("action", "")
    if action != "opened":
        return None

    issue_data = payload.get("issue", {})
    repo_data = payload.get("repository", {})
    issue_number = issue_data.get("number", 0)
    full_name = repo_data.get("full_name", "")

    if not full_name or not issue_number:
        return None

    title = issue_data.get("title") or ""
    body = issue_data.get("body")
    labels = [
        label["name"]
        for label in issue_data.get("labels", [])
        if isinstance(label, dict) and "name" in label
    ]

    # Classify via two-stage classifier: rules + LLM fallback.
    classifier = IssueClassifier()
    classification = await classifier.async_classify(title=title, body=body, labels=labels)

    issue_state = issue_data.get("state") or "open"
    issue_author = (
        issue_data.get("user", {}).get("login")
        if isinstance(issue_data.get("user"), dict) else None
    )

    # Record the event.
    event_id = delivery_id or f"local-{uuid4().hex}"
    record = WebhookEventRecord(
        event_id=event_id,
        event_type="issues",
        action=action,
        repository=full_name,
        issue_number=issue_number,
        issue_title=title,
        issue_state=issue_state,
        issue_labels=labels,
        issue_author=issue_author,
        classification=classification,
        received_at=datetime.now(timezone.utc),
        raw_payload=payload,
    )
    webhook_event_store[event_id] = record

    # Persist to database (if configured).
    _persist_event(record)

    # If the repository has already been synced, update its snapshot in place.
    if "/" in full_name:
        owner, name = full_name.split("/", 1)
        existing = repository_store.get(owner, name)
        if existing is not None:
            # Map the webhook issue to a GitHubIssue (mirrors RepositorySyncService._map_issue).
            new_issue = GitHubIssue(
                number=issue_number,
                title=title,
                state=issue_data.get("state") or "open",
                html_url=issue_data.get("html_url") or "",
                author=(issue_data.get("user") or {}).get("login") if isinstance(issue_data.get("user"), dict) else None,
                labels=labels,
                created_at=_parse_timestamp(issue_data.get("created_at")),
                updated_at=_parse_timestamp(issue_data.get("updated_at")),
                comments=issue_data.get("comments", 0),
                classification=classification,
            )

            # Avoid duplicates.
            existing_numbers = {i.number for i in existing.issues}
            if issue_number not in existing_numbers:
                existing.issues.append(new_issue)

            # Recalculate issue category summaries.
            categories = [i.classification.category for i in existing.issues]
            counter: Counter[str] = Counter()
            for cat in categories:
                counter[cat.value] += 1
            existing.issue_categories = [
                CategorySummary(category=c, count=n)
                for c, n in counter.most_common()
            ]
            # Note: InMemoryRepositoryStore saves by reference, so no explicit save needed
            # with the current implementation — but call it anyway for future DB compatibility.
            repository_store.save(existing)

    return record


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
