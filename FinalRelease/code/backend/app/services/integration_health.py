"""Connectivity checks for user-configured external integrations."""

import asyncio
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.schemas.user import IntegrationConnection, IntegrationStatus
from app.services.usage import record_integration_request


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def check_llm_connection() -> IntegrationConnection:
    """Validate the configured OpenAI-compatible endpoint and API key."""
    cfg = get_effective_config()
    if not cfg.llm_api_key or not cfg.llm_api_base_url or not cfg.llm_model:
        return IntegrationConnection(
            status="not_configured", message="请配置完整的 API 地址、模型和 API Key。", checked_at=_now(),
        )

    record_integration_request("llm")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{cfg.llm_api_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {cfg.llm_api_key}"},
            )
        if response.is_success:
            return IntegrationConnection(
                status="connected", message=f"API 可访问，模型配置为 {cfg.llm_model}。", checked_at=_now(),
            )
        if response.status_code in {401, 403}:
            message = "API Key 无效或没有访问权限。"
        else:
            message = f"API 返回 HTTP {response.status_code}。"
        return IntegrationConnection(status="failed", message=message, checked_at=_now())
    except httpx.HTTPError as exc:
        return IntegrationConnection(
            status="failed", message=f"无法连接 LLM API：{exc.__class__.__name__}", checked_at=_now(),
        )


async def check_github_connection() -> IntegrationConnection:
    """Validate the configured GitHub token against the authenticated-user API."""
    cfg = get_effective_config()
    if not cfg.github_token:
        return IntegrationConnection(
            status="not_configured", message="尚未配置 GitHub Token。", checked_at=_now(),
        )

    record_integration_request("github")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.github_api_base_url.rstrip('/')}/user",
                headers={
                    "Authorization": f"Bearer {cfg.github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": settings.github_api_version,
                    "User-Agent": "wgy666-github-issue-analysis-platform",
                },
            )
        if response.is_success:
            login = response.json().get("login", "当前用户")
            return IntegrationConnection(
                status="connected", message=f"已连接 GitHub：{login}", checked_at=_now(),
            )
        if response.status_code in {401, 403}:
            message = "GitHub Token 无效、已过期或权限不足。"
        else:
            message = f"GitHub 返回 HTTP {response.status_code}。"
        return IntegrationConnection(status="failed", message=message, checked_at=_now())
    except (httpx.HTTPError, ValueError) as exc:
        return IntegrationConnection(
            status="failed", message=f"无法连接 GitHub：{exc.__class__.__name__}", checked_at=_now(),
        )


def latest_webhook_received_at() -> datetime | None:
    """Return the newest webhook timestamp from memory or persistent storage."""
    from app.webhooks.handler import webhook_event_store

    timestamps = [event.received_at for event in webhook_event_store.values()]
    if settings.database_url:
        try:
            from sqlalchemy import select
            from app.storage.database import create_database_engine, webhook_events

            engine = create_database_engine()
            try:
                with engine.connect() as conn:
                    row = conn.execute(
                        select(webhook_events.c.received_at)
                        .order_by(webhook_events.c.received_at.desc())
                        .limit(1)
                    ).first()
                if row is not None:
                    timestamps.append(row.received_at)
            finally:
                engine.dispose()
        except Exception:
            pass
    return max(timestamps) if timestamps else None


def check_webhook_connection() -> IntegrationConnection:
    """Report webhook readiness and whether an event has reached this service."""
    cfg = get_effective_config()
    checked_at = _now()
    if not cfg.github_webhook_secret:
        return IntegrationConnection(
            status="not_configured", message="尚未配置 Webhook Secret。", checked_at=checked_at,
        )
    last_received_at = latest_webhook_received_at()
    if last_received_at is None:
        return IntegrationConnection(
            status="configured",
            message="Secret 已配置，尚未收到 GitHub Webhook。",
            checked_at=checked_at,
        )
    return IntegrationConnection(
        status="connected",
        message="Webhook 已联通并成功接收过事件。",
        checked_at=checked_at,
        last_received_at=last_received_at,
    )


async def check_integrations() -> IntegrationStatus:
    """Run active checks concurrently and combine them with webhook readiness."""
    llm, github = await asyncio.gather(check_llm_connection(), check_github_connection())
    return IntegrationStatus(llm=llm, github=github, webhook=check_webhook_connection())
