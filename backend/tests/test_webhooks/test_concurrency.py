"""True asynchronous concurrency tests for webhook handling."""

import asyncio
import importlib
import os

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import create_app
from app.webhooks.handler import webhook_event_store


@pytest.fixture(autouse=True)
def _clear_store():
    webhook_event_store.clear()
    yield
    webhook_event_store.clear()


@pytest.fixture
def app_instance():
    from app.core.config import settings

    original_key = settings.llm_api_key
    original_secret = settings.github_webhook_secret
    original_database_url = settings.database_url
    settings.github_webhook_secret = None
    settings.database_url = None
    settings.llm_api_key = None
    os.environ.pop("DATABASE_URL", None)

    import app.storage

    importlib.reload(app.storage)
    application = create_app()
    yield application

    settings.llm_api_key = original_key
    settings.github_webhook_secret = original_secret
    settings.database_url = original_database_url


def _payload(number: int, repo: str = "owner/repo") -> dict:
    return {
        "action": "opened",
        "issue": {
            "title": f"T{number}",
            "body": f"B{number}",
            "number": number,
            "state": "open",
            "html_url": f"https://github.com/{repo}/issues/{number}",
            "user": {"login": "t"},
            "comments": 0,
        },
        "repository": {"full_name": repo},
    }


def _headers(delivery_id: str) -> dict[str, str]:
    return {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": delivery_id,
    }


@pytest.mark.asyncio
async def test_concurrent_webhooks_same_repo(app_instance):
    """Twenty requests sent together are all accepted and stored."""
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(*(
            client.post(
                "/api/webhooks/github",
                json=_payload(100 + index, "same/repo"),
                headers=_headers(f"same-{index}"),
            )
            for index in range(20)
        ))

        assert all(response.status_code == 200 for response in responses)
        response = await client.get("/api/webhooks/events?limit=30")

    same_repo = [event for event in response.json() if event["repository"] == "same/repo"]
    assert len(same_repo) == 20


@pytest.mark.asyncio
async def test_concurrent_reads_and_writes_do_not_conflict(app_instance):
    """Reads and writes may overlap without errors or missing final records."""
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        writes = [
            client.post(
                "/api/webhooks/github",
                json=_payload(200 + index, "inter/repo"),
                headers=_headers(f"inter-{index}"),
            )
            for index in range(10)
        ]
        reads = [client.get("/api/webhooks/events?limit=30") for _ in range(10)]
        responses = await asyncio.gather(*(writes + reads))

        assert all(response.status_code == 200 for response in responses)
        final_response = await client.get("/api/webhooks/events?limit=30")

    assert len(final_response.json()) == 10


@pytest.mark.asyncio
async def test_concurrent_duplicate_delivery_id_is_deduplicated(app_instance):
    """Concurrent retries with one delivery id produce one visible event."""
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = _payload(300, "dedup/repo")
        responses = await asyncio.gather(*(
            client.post(
                "/api/webhooks/github",
                json=payload,
                headers=_headers("duplicate-delivery"),
            )
            for _ in range(8)
        ))
        assert all(response.status_code == 200 for response in responses)
        response = await client.get("/api/webhooks/events?limit=20")

    duplicates = [event for event in response.json() if event["event_id"] == "duplicate-delivery"]
    assert len(duplicates) == 1


@pytest.mark.asyncio
async def test_webhook_requests_overlap_in_time(app_instance, monkeypatch):
    """Prove the ASGI route handles more than one in-flight request."""
    import app.webhooks.router as router_module

    active = 0
    peak = 0

    async def delayed_dispatch(*_args, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return None

    monkeypatch.setattr(router_module, "dispatch_event", delayed_dispatch)
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(*(
            client.post(
                "/api/webhooks/github",
                json=_payload(400 + index),
                headers=_headers(f"overlap-{index}"),
            )
            for index in range(12)
        ))

    assert all(response.status_code == 200 for response in responses)
    assert peak > 1


@pytest.mark.asyncio
async def test_missing_event_header_returns_422(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/webhooks/github", json={"action": "opened"})
    assert response.status_code == 422
