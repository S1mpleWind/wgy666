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

    # GitHub expects a 2xx response within 10s — dispatch asynchronously.
    asyncio.create_task(dispatch_event(
        x_github_event, payload, delivery_id=x_github_delivery
    ))
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
    reply_text = await harness.generate_issue_reply(
        owner=owner,
        name=name,
        issue_title=record.issue_title,
        issue_body=record.raw_payload.get("issue", {}).get("body"),
        labels=record.issue_labels,
    )

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
