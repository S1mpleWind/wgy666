"""Request-level coverage for loading per-user integration configuration."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest

from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.core.security import AuthMiddleware, create_access_token
from app.schemas.user import User, UserConfig


@pytest.mark.asyncio
async def test_authenticated_request_uses_user_config_and_then_resets(monkeypatch):
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    user = User(
        id=user_id,
        name="Config User",
        email="config@example.com",
        created_at=now,
        updated_at=now,
    )

    class FakeUserStore:
        def get_user(self, requested_id):
            return user if requested_id == user_id else None

        def get_user_config(self, requested_id):
            assert requested_id == user_id
            return UserConfig(
                llm_api_base_url="https://user-llm.example.com/v1",
                llm_model="user-model",
                llm_api_key_configured=True,
                github_token_configured=True,
                github_webhook_secret_configured=False,
            )

        def _get_raw_config(self, requested_id):
            assert requested_id == user_id
            return {
                "llm_api_key": "user-llm-key",
                "github_token": "user-github-token",
                "github_webhook_secret": None,
            }

    monkeypatch.setattr("app.storage.users.get_user_store", lambda: FakeUserStore())

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/effective-config")
    async def effective_config():
        config = get_effective_config()
        return {
            "llm_api_base_url": config.llm_api_base_url,
            "llm_model": config.llm_model,
            "llm_api_key": config.llm_api_key,
            "github_token": config.github_token,
        }

    token = create_access_token(str(user_id))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        authenticated = await client.get(
            "/effective-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        anonymous = await client.get("/effective-config")

    assert authenticated.json() == {
        "llm_api_base_url": "https://user-llm.example.com/v1",
        "llm_model": "user-model",
        "llm_api_key": "user-llm-key",
        "github_token": "user-github-token",
    }
    assert anonymous.json() == {
        "llm_api_base_url": settings.llm_api_base_url,
        "llm_model": settings.llm_model,
        "llm_api_key": settings.llm_api_key,
        "github_token": settings.github_token,
    }


@pytest.mark.asyncio
async def test_authenticated_user_without_config_does_not_inherit_server_defaults(monkeypatch):
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    user = User(
        id=user_id,
        name="Empty Config",
        email="empty@example.com",
        created_at=now,
        updated_at=now,
    )

    class FakeUserStore:
        def get_user(self, requested_id):
            return user if requested_id == user_id else None

        def get_user_config(self, _requested_id):
            return None

        def _get_raw_config(self, _requested_id):
            return None

    monkeypatch.setattr("app.storage.users.get_user_store", lambda: FakeUserStore())
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/effective-config")
    async def effective_config():
        config = get_effective_config()
        return {
            "llm_api_base_url": config.llm_api_base_url,
            "llm_model": config.llm_model,
            "llm_api_key": config.llm_api_key,
            "github_token": config.github_token,
            "github_webhook_secret": config.github_webhook_secret,
            "user_id": config.user_id,
        }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/effective-config",
            headers={"Authorization": f"Bearer {create_access_token(str(user_id))}"},
        )

    assert response.json() == {
        "llm_api_base_url": "",
        "llm_model": "",
        "llm_api_key": None,
        "github_token": None,
        "github_webhook_secret": None,
        "user_id": str(user_id),
    }
