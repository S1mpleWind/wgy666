import asyncio
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.schemas.issue import IssueClassification
from app.webhooks.handler import dispatch_event, verify_signature, webhook_event_store

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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

    record = await dispatch_event(x_github_event, payload, delivery_id=x_github_delivery)

    # NOTE: Auto-reply is not posted automatically — see /events/{id}/reply
    # TODO: For production, dispatch asynchronously via asyncio.create_task or
    # a task queue to avoid GitHub's 10s webhook timeout.

    return {"status": "ok"}


@router.get("/config")
async def webhook_config(request: Request) -> dict:
    """Return the webhook configuration for the frontend settings panel.

    Exposes the public URL and the configured secret so users can copy
    them into GitHub's Webhook settings page.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    webhook_url = f"{scheme}://{host}/api/webhooks/github"
    return {
        "url": webhook_url,
        "secret": settings.github_webhook_secret or "",
    }


@router.get("/events")
async def list_webhook_events(limit: int = 20) -> list[dict]:
    """Return recent webhook events from the in-memory store.

    Events are sorted newest-first. This endpoint is for the frontend
    notification inbox.

    TODO: Replace with database-backed query when webhook events are persisted.
    """
    events = sorted(
        webhook_event_store.values(),
        key=lambda e: e.received_at,
        reverse=True,
    )
    return [
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "action": e.action,
            "repository": e.repository,
            "issue_number": e.issue_number,
            "issue_title": e.issue_title,
            "issue_state": e.issue_state,
            "issue_author": e.issue_author,
            "issue_labels": e.issue_labels,
            "classification": _classification_dict(e.classification),
            "received_at": e.received_at.isoformat(),
        }
        for e in events[:limit]
    ]


@router.get("/events/{event_id}")
async def get_webhook_event(event_id: str) -> dict:
    """Return full detail for a single webhook event."""
    record = webhook_event_store.get(event_id)
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
        "received_at": record.received_at.isoformat(),
    }


@router.patch("/events/{event_id}")
async def update_webhook_event(event_id: str, action: str) -> dict:
    """Mark a webhook event as read or deleted.

    Query params:
      action=read   — mark as read
      action=delete — mark as deleted (hidden from list)
    """
    record = webhook_event_store.get(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")

    if action == "read":
        pass  # memory store doesn't have a read flag; frontend handles locally
    elif action == "delete":
        webhook_event_store.pop(event_id, None)
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
    except Exception:
        pass

    return {"status": "ok"}


@router.post("/events/{event_id}/reply")
async def reply_to_webhook_event(event_id: str) -> dict:
    """Generate and post an auto-reply for a webhook event using AgentHarness.

    The LLM uses the full tool-calling pipeline (searches files, README,
    knowledge graph) to research the issue before writing a reply.
    The reply is posted as a GitHub comment on the original issue.
    """
    record = webhook_event_store.get(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if not record.classification:
        raise HTTPException(status_code=400, detail="Event has no classification")

    owner, name = record.repository.split("/", 1)

    from app.assistant.harness import AgentHarness
    from app.services.github_client import GitHubClient
    from app.services.repository_url import parse_github_repository_url

    harness = AgentHarness()
    snapshot, _ = await harness.query.get_snapshot(owner, name, "cache_first")
    labels_str = ", ".join(record.issue_labels) if record.issue_labels else "(none)"
    body_str = (record.raw_payload.get("issue", {}).get("body")) or "(no body provided)"

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
    record = webhook_event_store.get(event_id)
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

    return {
        "status": "ok",
        "pr_url": result.pr_url,
        "branch_name": result.branch_name,
        "event_id": event_id,
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
