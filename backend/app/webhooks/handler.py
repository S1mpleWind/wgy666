import hashlib
import hmac
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.schemas.issue import IssueCategory, IssueClassification
from app.schemas.repository import CategorySummary, GitHubIssue
from app.services.issue_classifier import IssueClassifier
from app.storage import repository_store


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
    classification: IssueClassification | None
    received_at: datetime
    raw_payload: dict = field(default_factory=dict)


# Module-level in-memory store for webhook events.
# Follows the same simple-interface pattern as InMemoryRepositoryStore.
webhook_event_store: dict[str, WebhookEventRecord] = {}


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

def dispatch_event(event: str, payload: dict, delivery_id: str | None = None) -> WebhookEventRecord | None:
    """Route a webhook event to the appropriate handler based on event type.

    Returns the WebhookEventRecord if the event was handled, None otherwise.
    """
    if event == "issues":
        return handle_issue_event(payload, delivery_id)

    # Unknown event type — silently ignore (GitHub sends many event types).
    return None


# ---------------------------------------------------------------------------
# Issue event handler
# ---------------------------------------------------------------------------

def handle_issue_event(payload: dict, delivery_id: str | None = None) -> WebhookEventRecord | None:
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

    # Classify via the existing rule-based classifier.
    classifier = IssueClassifier()
    classification = classifier.classify(title=title, body=body, labels=labels)

    # Record the event.
    record = WebhookEventRecord(
        event_id=delivery_id or "",
        event_type="issues",
        action=action,
        repository=full_name,
        issue_number=issue_number,
        classification=classification,
        received_at=datetime.now(timezone.utc),
        raw_payload=payload,
    )
    webhook_event_store[delivery_id or str(issue_number)] = record

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
