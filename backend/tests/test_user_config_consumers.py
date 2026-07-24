"""Verify runtime user configuration reaches its backend consumers."""

import pytest

from app.api.routes.users import update_system_config
from app.core.config import settings
from app.schemas.user import SystemConfigUpdate


@pytest.mark.asyncio
async def test_runtime_config_reaches_assistant_github_and_webhook(monkeypatch):
    monkeypatch.setattr("app.api.routes.users.persist_system_config", lambda: None)
    monkeypatch.setattr(settings, "llm_api_base_url", "https://initial.example.com/v1")
    monkeypatch.setattr(settings, "llm_model", "initial-model")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "github_token", None)
    monkeypatch.setattr(settings, "github_webhook_secret", None)

    public_config = await update_system_config(SystemConfigUpdate(
        llm_api_base_url="https://runtime.example.com/v1",
        llm_model="runtime-model",
        llm_api_key="runtime-llm-key",
        github_token="runtime-github-token",
        github_webhook_secret="runtime-webhook-secret",
    ))
    assert public_config.llm_api_key_configured is True
    assert public_config.github_token_configured is True
    assert public_config.github_webhook_secret_configured is True
    assert "runtime-llm-key" not in public_config.model_dump_json()

    assistant_client_args = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            assistant_client_args.update(kwargs)

    monkeypatch.setattr("app.assistant.harness.AsyncOpenAI", FakeAsyncOpenAI)
    from app.assistant.harness import AgentHarness

    AgentHarness()
    assert assistant_client_args == {
        "api_key": "runtime-llm-key",
        "base_url": "https://runtime.example.com/v1",
    }
    assert settings.llm_model == "runtime-model"

    github_client_args = {}

    class FakeHttpClient:
        def __init__(self, **kwargs):
            github_client_args.update(kwargs)

    monkeypatch.setattr("app.services.github_client.httpx.AsyncClient", FakeHttpClient)
    from app.services.github_client import GitHubClient

    GitHubClient()
    assert github_client_args["headers"]["Authorization"] == "Bearer runtime-github-token"

    # Webhook signature verification reads this same settings singleton per request.
    assert settings.github_webhook_secret == "runtime-webhook-secret"


def test_runtime_config_is_persisted_to_an_isolated_env_file(tmp_path, monkeypatch):
    from dotenv import dotenv_values

    from app.core.config import persist_system_config

    env_file = tmp_path / ".env"
    env_file.write_text("UNRELATED=value\n", encoding="utf-8")
    monkeypatch.setenv("ISSUESCOPE_RUNTIME_ENV_FILE", str(env_file))
    monkeypatch.setattr(settings, "llm_api_base_url", "https://persisted.example.com/v1")
    monkeypatch.setattr(settings, "llm_model", "persisted-model")
    monkeypatch.setattr(settings, "llm_api_key", "persisted-llm-key")
    monkeypatch.setattr(settings, "github_token", "persisted-github-token")
    monkeypatch.setattr(settings, "github_webhook_secret", "persisted-webhook-secret")

    persist_system_config()

    values = dotenv_values(env_file)
    assert values["UNRELATED"] == "value"
    assert values["LLM_API_BASE_URL"] == "https://persisted.example.com/v1"
    assert values["LLM_MODEL"] == "persisted-model"
    assert values["LLM_API_KEY"] == "persisted-llm-key"
    assert values["GITHUB_TOKEN"] == "persisted-github-token"
    assert values["GITHUB_WEBHOOK_SECRET"] == "persisted-webhook-secret"
