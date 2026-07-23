import logging
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.issue import IssueClassification
from app.webhooks.handler import (
    WebhookEventRecord,
    dispatch_event,
    verify_signature,
    webhook_event_store,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


class ApprovedReplyRequest(BaseModel):
    reply_text: str = Field(min_length=1, max_length=10000)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
) -> dict[str, str]:
    """Receive GitHub webhook events.

    Verifies the HMAC-SHA256 signature if a webhook secret is configured,
    then dispatches the event to the appropriate handler.
    """
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    await dispatch_event(x_github_event, payload, delivery_id=x_github_delivery)

    # Auto-reply is not posted automatically; maintainers approve it first.

    return {"status": "ok"}


@router.get("/config")
async def webhook_config(request: Request) -> dict:
    """Return the webhook configuration for the frontend settings panel.

    The secret value is never returned to clients.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    webhook_url = f"{scheme}://{host}/api/webhooks/github"
    return {
        "url": webhook_url,
        "secret_configured": bool(settings.github_webhook_secret),
    }


@router.get("/events")
async def list_webhook_events(
    limit: int = 20,
    repository: str | None = None,
) -> list[dict]:
    """Return recent non-deleted webhook events, optionally by repository."""
    limit = max(1, min(limit, 100))
    events_by_id = {
        event.event_id: event
        for event in _load_database_events(repository, limit)
    }
    for event in webhook_event_store.values():
        if event.is_deleted:
            continue
        if repository and event.repository != repository:
            continue
        events_by_id[event.event_id] = event
    events = sorted(
        events_by_id.values(), key=lambda event: event.received_at, reverse=True,
    )[:limit]
    return [_event_summary(event) for event in events]


@router.get("/events/{event_id}")
async def get_webhook_event(event_id: str) -> dict:
    """Return full detail for a single webhook event."""
    record = _find_event(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # Extract additional issue data from the raw payload.
    issue_data = record.raw_payload.get("issue", {}) if record.raw_payload else {}

    return {
        "event_id": record.event_id,
        "event_type": record.event_type,
        "action": record.action,
        "repository": record.repository,
        "issue_number": record.issue_number,
        "issue_title": record.issue_title,
        "issue_state": record.issue_state,
        "issue_author": record.issue_author,
        "issue_labels": record.issue_labels,
        "issue_body": issue_data.get("body"),
        "issue_comments_count": issue_data.get("comments", 0),
        "issue_html_url": issue_data.get("html_url"),
        "classification": _classification_dict(record.classification),
        "is_read": record.is_read,
        "received_at": record.received_at.isoformat(),
    }


@router.patch("/events/{event_id}")
async def update_webhook_event(event_id: str, action: str) -> dict:
    """Mark a webhook event as read or deleted.

    Query params:
      action=read   — mark as read
      action=delete — mark as deleted (hidden from list)
    """
    record = _find_event(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")

    if action == "read":
        record.is_read = True
    elif action == "delete":
        record.is_deleted = True
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'read' or 'delete'.")

    # Also update database when available.
    try:
        from app.storage.database import webhook_events, create_database_engine
        from app.core.config import settings
        from sqlalchemy import update
        if settings.database_url:
            engine = create_database_engine()
            with engine.begin() as conn:
                if action == "delete":
                    conn.execute(
                        update(webhook_events).where(webhook_events.c.event_id == event_id)
                        .values(is_deleted=True)
                    )
                else:
                    conn.execute(
                        update(webhook_events).where(webhook_events.c.event_id == event_id)
                        .values(is_read=True)
                    )
            engine.dispose()
    except Exception as exc:
        logger.warning("Failed to update webhook event %s: %s", event_id, exc)

    return {"status": "ok"}


@router.post("/events/{event_id}/reply")
async def reply_to_webhook_event(
    event_id: str,
    payload: ApprovedReplyRequest | None = None,
) -> dict:
    """Post an approved draft, or generate a reply for legacy callers."""
    record = _find_event(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if not record.classification:
        raise HTTPException(status_code=400, detail="Event has no classification")

    owner, name = record.repository.split("/", 1)

    from app.assistant.harness import AgentHarness
    from app.services.github_client import GitHubClient
    from app.services.repository_url import parse_github_repository_url

    if payload is not None:
        reply_text = payload.reply_text.strip()
        ref = parse_github_repository_url(f"https://github.com/{record.repository}")
        async with GitHubClient() as gh:
            comment = await gh.comment_on_issue(ref, record.issue_number, reply_text)
        return {
            "status": "ok",
            "reply_text": reply_text,
            "comment_url": comment.get("html_url", ""),
            "event_id": event_id,
            "source": "approved_draft",
        }

    harness = AgentHarness()
    snapshot, _ = await harness.query.get_snapshot(owner, name, "cache_first")
    labels_str = ", ".join(record.issue_labels) if record.issue_labels else "(none)"
    body_str = (record.raw_payload.get("issue", {}).get("body")) or "(no body provided)"

    # ── Check FAQ first ──────────────────────────────────────────
    from app.services.faq_service import faq_match
    faq_result = await faq_match(
        record.issue_title, body_str, owner, name,
    )
    if faq_result and faq_result["answer"]:
        reply_text = f"{faq_result['answer']}\n\n---\n_🤖 此回复来自 FAQ 知识库（匹配度 {faq_result['score']:.0%}）_"
        ref = parse_github_repository_url(f"https://github.com/{record.repository}")
        async with GitHubClient() as gh:
            comment = await gh.comment_on_issue(ref, record.issue_number, reply_text)
        return {
            "status": "ok",
            "reply_text": reply_text,
            "comment_url": comment.get("html_url", ""),
            "event_id": event_id,
            "source": "faq",
        }

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful open-source project maintainer assistant. "
                "A user has filed an issue on the repository. "
                "Use the available tools to research the issue, then write "
                "a concise, friendly reply in Chinese. "
                "For questions, provide guidance from the codebase. "
                "For feature requests, acknowledge politely. "
                "Keep your reply under 200 words.\n\n"
                f"Repository: {snapshot.identity.full_name}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## Issue\n\n"
                f"**Title**: {record.issue_title}\n"
                f"**Body**: {body_str}\n"
                f"**Labels**: {labels_str}\n\n"
                "Research and reply to this issue."
            ),
        },
    ]
    reply_text, _ = await harness.run(messages, snapshot)

    if not reply_text:
        raise HTTPException(status_code=502, detail="Failed to generate reply")

    ref = parse_github_repository_url(f"https://github.com/{record.repository}")
    async with GitHubClient() as gh:
        comment = await gh.comment_on_issue(ref, record.issue_number, reply_text)

    return {
        "status": "ok",
        "reply_text": reply_text,
        "comment_url": comment.get("html_url", ""),
        "event_id": event_id,
    }


@router.post("/events/{event_id}/fix")
async def fix_webhook_event(event_id: str) -> dict:
    """Generate and submit an auto-fix PR for a bug issue using AgentHarness."""
    record = _find_event(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if not record.classification:
        raise HTTPException(status_code=400, detail="Event has no classification")

    from app.services.auto_fix import AutoFixService

    owner, name = record.repository.split("/", 1)
    fixer = AutoFixService()
    result = await fixer.fix_issue(
        owner=owner, name=name,
        issue_number=record.issue_number,
        issue_title=record.issue_title,
        issue_body=record.raw_payload.get("issue", {}).get("body"),
        labels=record.issue_labels,
    )

    if not result.success:
        raise HTTPException(status_code=502, detail=result.error or "Auto-fix failed")

    # Log fix into long-term memory.
    from app.services.memory_service import log_fix_memory
    await log_fix_memory(
        owner=owner, name=name,
        issue_title=record.issue_title,
        issue_category=record.classification.category.value,
        issue_body=record.raw_payload.get("issue", {}).get("body"),
        files_changed=result.files_changed,
        fix_summary=result.summary or f"Auto-fix for: {record.issue_title}",
    )

    return {
        "status": "ok",
        "pr_url": result.pr_url,
        "branch_name": result.branch_name,
        "event_id": event_id,
    }


def _load_database_events(
    repository: str | None,
    limit: int,
) -> list[WebhookEventRecord]:
    """Read persisted events; failures fall back to the in-memory store."""
    if not settings.database_url:
        return []

    from app.storage.database import create_database_engine, webhook_events
    from sqlalchemy import select

    engine = create_database_engine()
    try:
        statement = (
            select(webhook_events)
            .where(webhook_events.c.is_deleted.is_(False))
            .order_by(webhook_events.c.received_at.desc())
        )
        if repository:
            statement = statement.where(webhook_events.c.repository == repository)
        statement = statement.limit(limit)
        with engine.connect() as conn:
            rows = conn.execute(statement).mappings().all()
        return [_database_row_to_record(row) for row in rows]
    except Exception as exc:
        logger.warning("Failed to load webhook events: %s", exc)
        return []
    finally:
        engine.dispose()


def _find_event(event_id: str) -> WebhookEventRecord | None:
    record = webhook_event_store.get(event_id)
    if record is not None and not record.is_deleted:
        return record
    if not settings.database_url:
        return None

    from app.storage.database import create_database_engine, webhook_events
    from sqlalchemy import select

    engine = create_database_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                select(webhook_events).where(
                    webhook_events.c.event_id == event_id,
                    webhook_events.c.is_deleted.is_(False),
                )
            ).mappings().first()
        if row is None:
            return None
        record = _database_row_to_record(row)
        webhook_event_store[event_id] = record
        return record
    except Exception as exc:
        logger.warning("Failed to load webhook event %s: %s", event_id, exc)
        return None
    finally:
        engine.dispose()


def _database_row_to_record(row) -> WebhookEventRecord:
    classification = None
    if row.get("classification_json"):
        classification = IssueClassification.model_validate(row["classification_json"])
    return WebhookEventRecord(
        event_id=row["event_id"],
        event_type=row["event_type"],
        action=row["action"],
        repository=row["repository"],
        issue_number=row["issue_number"],
        issue_title=row["issue_title"],
        issue_state=row["issue_state"],
        issue_labels=row["issue_labels"] or [],
        issue_author=row["issue_author"],
        classification=classification,
        is_read=bool(row["is_read"]),
        is_deleted=bool(row["is_deleted"]),
        received_at=row["received_at"],
        raw_payload=row["raw_payload"] or {},
    )


def _event_summary(event: WebhookEventRecord) -> dict:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "action": event.action,
        "repository": event.repository,
        "issue_number": event.issue_number,
        "issue_title": event.issue_title,
        "issue_state": event.issue_state,
        "issue_author": event.issue_author,
        "issue_labels": event.issue_labels,
        "classification": _classification_dict(event.classification),
        "is_read": event.is_read,
        "received_at": event.received_at.isoformat(),
    }


def _classification_dict(c: IssueClassification | None) -> dict | None:
    """Convert an IssueClassification to a JSON-safe dict."""
    if c is None:
        return None
    return {
        "category": c.category.value,
        "confidence": c.confidence,
        "reason": c.reason,
        "suggested_action": c.suggested_action,
        "signals": c.signals,
        "auto_reply_draft": c.auto_reply_draft,
    }
