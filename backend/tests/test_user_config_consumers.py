"""Verify per-user effective config reaches backend consumers via ContextVar."""

import pytest

from app.core.effective_config import EffectiveConfig, get_effective_config, set_effective_config
from app.core.config import settings


class TestEffectiveConfig:
    """Test the ContextVar-based effective config module directly."""

    def test_default_falls_back_to_settings(self):
        """With no context set, get_effective_config returns server defaults."""
        cfg = get_effective_config()
        assert cfg.llm_api_base_url == settings.llm_api_base_url
        assert cfg.llm_model == settings.llm_model
        assert cfg.llm_api_key == settings.llm_api_key
        assert cfg.github_token == settings.github_token
        assert cfg.github_webhook_secret == settings.github_webhook_secret

    def test_set_and_get(self):
        """Setting a config via ContextVar returns the custom values."""
        custom = EffectiveConfig(
            llm_api_base_url="https://custom.example.com/v1",
            llm_model="custom-model",
            llm_api_key="custom-key",
            github_token="custom-token",
            github_webhook_secret="custom-secret",
        )
        set_effective_config(custom)
        cfg = get_effective_config()
        assert cfg.llm_api_base_url == "https://custom.example.com/v1"
        assert cfg.llm_model == "custom-model"
        assert cfg.llm_api_key == "custom-key"
        assert cfg.github_token == "custom-token"
        assert cfg.github_webhook_secret == "custom-secret"

    def test_none_values_preserved(self):
        """None values in EffectiveConfig should be preserved (not replaced with defaults)."""
        custom = EffectiveConfig(
            llm_api_base_url="https://custom.example.com/v1",
            llm_model="custom-model",
            llm_api_key=None,
            github_token=None,
            github_webhook_secret=None,
        )
        set_effective_config(custom)
        cfg = get_effective_config()
        assert cfg.llm_api_key is None
        assert cfg.github_token is None
        assert cfg.github_webhook_secret is None


@pytest.mark.asyncio
async def test_effective_config_reaches_assistant_and_github(monkeypatch):
    """When effective config is set, downstream consumers read from it."""
    custom = EffectiveConfig(
        llm_api_base_url="https://runtime.example.com/v1",
        llm_model="runtime-model",
        llm_api_key="runtime-llm-key",
        github_token="runtime-github-token",
        github_webhook_secret="runtime-webhook-secret",
    )
    set_effective_config(custom)

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

    github_client_args = {}

    class FakeHttpClient:
        def __init__(self, **kwargs):
            github_client_args.update(kwargs)

    monkeypatch.setattr("app.services.github_client.httpx.AsyncClient", FakeHttpClient)
    from app.services.github_client import GitHubClient

    GitHubClient()
    assert github_client_args["base_url"] == settings.github_api_base_url
    assert github_client_args["headers"]["Authorization"] == "Bearer runtime-github-token"
