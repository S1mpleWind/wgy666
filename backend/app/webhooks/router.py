from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
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

    dispatch_event(x_github_event, payload, delivery_id=x_github_delivery)

    # GitHub expects a 2xx response quickly.
    return {"status": "ok"}


@router.get("/config")
async def webhook_config(request: Request) -> dict:
    """Return the webhook configuration for the frontend settings panel.

    Exposes the public URL and the configured secret so users can copy
    them into GitHub's Webhook settings page.
    """
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    public_url = f"{scheme}://{host}/api/webhooks/github"
    return {
        "url": public_url,
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
            "classification": {
                "category": e.classification.category.value if e.classification else None,
                "confidence": e.classification.confidence if e.classification else None,
                "reason": e.classification.reason if e.classification else None,
            },
            "received_at": e.received_at.isoformat(),
        }
        for e in events[:limit]
    ]
