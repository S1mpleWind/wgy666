from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from app.services.auto_fix import AutoFixService
from app.webhooks.auto_reply import IssueAutoReplyService
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

    # ── Auto-reply (non-blocking, best-effort) ───────────────────────
    if record and record.classification:
        category = record.classification.category.value
        # Only auto-reply to question / info_needed / documentation issues
        if category in {"question", "info_needed", "documentation", "feature_request"}:
            try:
                auto_reply = IssueAutoReplyService()
                result = await auto_reply.generate_reply(
                    owner=record.repository.split("/")[0],
                    name=record.repository.split("/")[1],
                    issue_title=record.issue_title,
                    issue_body=record.raw_payload.get("issue", {}).get("body"),
                    labels=record.issue_labels,
                )
                if result and result.used_llm:
                    from app.services.github_client import GitHubClient
                    from app.services.repository_url import parse_github_repository_url
                    ref = parse_github_repository_url(
                        f"https://github.com/{record.repository}"
                    )
                    async with GitHubClient() as gh:
                        await gh.comment_on_issue(ref, record.issue_number, result.reply_text)
            except Exception:
                # Auto-reply is best-effort; never break the webhook flow.
                pass

    # ── Auto-fix for bug issues (non-blocking, best-effort) ─────────
    if record and record.classification:
        category = record.classification.category.value
        if category == "bug":
            try:
                fixer = AutoFixService()
                result = await fixer.fix_issue(
                    owner=record.repository.split("/")[0],
                    name=record.repository.split("/")[1],
                    issue_number=record.issue_number,
                    issue_title=record.issue_title,
                    issue_body=record.raw_payload.get("issue", {}).get("body"),
                    labels=record.issue_labels,
                )
                if result.success:
                    from app.services.github_client import GitHubClient
                    from app.services.repository_url import parse_github_repository_url
                    ref = parse_github_repository_url(
                        f"https://github.com/{record.repository}"
                    )
                    async with GitHubClient() as gh:
                        await gh.comment_on_issue(
                            ref, record.issue_number,
                            f"🤖 自动修复 PR 已创建: {result.pr_url}",
                        )
            except Exception:
                # Auto-fix is best-effort; never break the webhook flow.
                pass

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
            "issue_title": e.issue_title,
            "issue_state": e.issue_state,
            "issue_author": e.issue_author,
            "issue_labels": e.issue_labels,
            "classification": {
                "category": e.classification.category.value if e.classification else None,
                "confidence": e.classification.confidence if e.classification else None,
                "reason": e.classification.reason if e.classification else None,
                "suggested_action": e.classification.suggested_action if e.classification else None,
                "signals": e.classification.signals if e.classification else None,
            },
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
        "classification": {
            "category": record.classification.category.value if record.classification else None,
            "confidence": record.classification.confidence if record.classification else None,
            "reason": record.classification.reason if record.classification else None,
            "suggested_action": record.classification.suggested_action if record.classification else None,
            "signals": record.classification.signals if record.classification else [],
        },
        "received_at": record.received_at.isoformat(),
    }
