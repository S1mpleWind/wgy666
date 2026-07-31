"""Unit tests for active integration connectivity checks."""

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.core.effective_config import EffectiveConfig, reset_effective_config, set_effective_config
from app.schemas.user import IntegrationConnection, IntegrationStatus
from app.services import integration_health
from app.services import usage as usage_service
from app.storage.users import UserStore
from app.storage.database import metadata
from app.schemas.user import UserConfigUpdate


class FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._body


class FakeClient:
    def __init__(self, responses: dict[str, FakeResponse], **_kwargs):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **_kwargs):
        return self.responses[url]


@pytest.mark.asyncio
async def test_active_checks_report_connected(monkeypatch):
    config = EffectiveConfig(
        llm_api_base_url="https://llm.example/v1",
        llm_model="test-model",
        llm_api_key="llm-key",
        github_token="github-key",
    )
    token = set_effective_config(config)
    responses = {
        "https://llm.example/v1/models": FakeResponse(200, {"data": []}),
        "https://api.github.com/user": FakeResponse(200, {"login": "octocat"}),
    }
    monkeypatch.setattr(
        integration_health.httpx,
        "AsyncClient",
        lambda **kwargs: FakeClient(responses, **kwargs),
    )
    try:
        llm = await integration_health.check_llm_connection()
        github = await integration_health.check_github_connection()
    finally:
        reset_effective_config(token)

    assert llm.status == "connected"
    assert "test-model" in llm.message
    assert github.status == "connected"
    assert "octocat" in github.message


@pytest.mark.asyncio
async def test_active_checks_report_missing_credentials():
    token = set_effective_config(EffectiveConfig())
    try:
        llm = await integration_health.check_llm_connection()
        github = await integration_health.check_github_connection()
        webhook = integration_health.check_webhook_connection()
    finally:
        reset_effective_config(token)

    assert llm.status == "not_configured"
    assert github.status == "not_configured"
    assert webhook.status == "not_configured"


def test_usage_stats_are_accumulated_per_user():
    store = UserStore()
    first = store.create_user("Usage One", "usage1@example.com", "pw123456")
    second = store.create_user("Usage Two", "usage2@example.com", "pw123456")

    store.record_usage(first.id, "llm", prompt_tokens=120, completion_tokens=30, total_tokens=150)
    store.record_usage(first.id, "github")

    first_usage = store.get_usage(first.id)
    assert first_usage.llm_requests == 1
    assert first_usage.github_requests == 1
    assert first_usage.prompt_tokens == 120
    assert first_usage.completion_tokens == 30
    assert first_usage.total_tokens == 150
    assert first_usage.updated_at is not None

    second_usage = store.get_usage(second.id)
    assert second_usage.llm_requests == 0
    assert second_usage.github_requests == 0
    assert second_usage.total_tokens == 0


def test_usage_stats_persist_in_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    store = UserStore(engine)
    user = store.create_user("Persistent", "persistent@example.com", "pw123456")

    store.record_usage(user.id, "llm", prompt_tokens=10, completion_tokens=5, total_tokens=15)
    reloaded = UserStore(engine).get_usage(user.id)

    assert reloaded.llm_requests == 1
    assert reloaded.prompt_tokens == 10
    assert reloaded.completion_tokens == 5
    assert reloaded.total_tokens == 15
    engine.dispose()


def test_partial_user_config_keeps_unset_llm_fields_blank():
    store = UserStore()
    user = store.create_user("Partial", "partial@example.com", "pw123456")

    config = store.upsert_user_config(user.id, UserConfigUpdate(github_token="github-only"))

    assert config.llm_api_base_url == ""
    assert config.llm_model == ""
    assert config.llm_api_key_configured is False
    assert config.github_token_configured is True


def test_authenticated_github_client_requires_user_token():
    from app.services.github_client import GitHubClient, GitHubClientError

    token = set_effective_config(EffectiveConfig(user_id="00000000-0000-0000-0000-000000000001"))
    try:
        with pytest.raises(GitHubClientError, match="not configured") as error:
            GitHubClient()
    finally:
        reset_effective_config(token)

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_status_route_returns_all_integrations(monkeypatch):
    from app.api.routes.users import get_my_integration_status

    user = UserStore().create_user("Status", "status@example.com", "pw123456")
    checked_at = datetime.now(timezone.utc)

    async def fake_check_integrations():
        return IntegrationStatus(
            llm=IntegrationConnection(status="connected", message="LLM ok", checked_at=checked_at),
            github=IntegrationConnection(status="failed", message="GitHub bad", checked_at=checked_at),
            webhook=IntegrationConnection(status="configured", message="Webhook waiting", checked_at=checked_at),
        )

    monkeypatch.setattr(integration_health, "check_integrations", fake_check_integrations)
    result = await get_my_integration_status(user)

    assert result.llm.status == "connected"
    assert result.github.status == "failed"
    assert result.webhook.status == "configured"


@pytest.mark.asyncio
async def test_tracked_completion_records_returned_tokens(monkeypatch):
    recorded = []

    async def create(**_kwargs):
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=42, completion_tokens=8, total_tokens=50),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(
        usage_service,
        "record_integration_request",
        lambda service, **values: recorded.append((service, values)),
    )

    await usage_service.tracked_chat_completion(client, model="test", messages=[])

    assert recorded == [("llm", {
        "prompt_tokens": 42,
        "completion_tokens": 8,
        "total_tokens": 50,
    })]
