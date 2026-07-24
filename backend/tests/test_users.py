"""User API route tests."""

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.core.config import settings
from app.storage.users import user_store


@pytest.fixture(autouse=True)
def empty_user_store(monkeypatch):
    monkeypatch.setattr("app.api.routes.users.persist_system_config", lambda: None)
    user_store.clear()
    yield
    user_store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_user_crud(client: TestClient):
    created = client.post("/api/users", json={"name": " Alice ", "email": "ALICE@example.com"})
    assert created.status_code == 201
    user = created.json()
    assert user["name"] == "Alice"
    assert user["email"] == "alice@example.com"

    assert client.get("/api/users").json() == [user]
    assert client.get(f"/api/users/{user['id']}").json() == user

    updated = client.patch(f"/api/users/{user['id']}", json={"name": "Alicia"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Alicia"

    assert client.delete(f"/api/users/{user['id']}").status_code == 204
    assert client.get(f"/api/users/{user['id']}").status_code == 404


def test_duplicate_email_returns_conflict(client: TestClient):
    payload = {"name": "First", "email": "same@example.com"}
    assert client.post("/api/users", json=payload).status_code == 201
    assert client.post("/api/users", json={"name": "Second", "email": "SAME@example.com"}).status_code == 409


def test_invalid_payloads_are_rejected(client: TestClient):
    assert client.post("/api/users", json={"name": "Alice", "email": "invalid"}).status_code == 422
    assert client.post("/api/users", json={"name": "   ", "email": "alice@example.com"}).status_code == 422
    created = client.post("/api/users", json={"name": "Alice", "email": "alice@example.com"}).json()
    assert client.patch(f"/api/users/{created['id']}", json={}).status_code == 422


def test_runtime_config_hides_secrets_and_can_clear_them(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_base_url", "https://initial.example.com/v1")
    monkeypatch.setattr(settings, "llm_model", "initial-model")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "github_token", None)
    monkeypatch.setattr(settings, "github_webhook_secret", None)

    response = client.patch("/api/users/config", json={
        "llm_api_base_url": "https://llm.example.com/v1/",
        "llm_model": "example-model",
        "llm_api_key": "llm-secret",
        "github_token": "github-secret",
        "github_webhook_secret": "webhook-secret",
    })
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "llm_api_base_url": "https://llm.example.com/v1",
        "llm_model": "example-model",
        "llm_api_key_configured": True,
        "github_token_configured": True,
        "github_webhook_secret_configured": True,
    }
    assert "llm-secret" not in response.text
    assert "github-secret" not in response.text
    assert "webhook-secret" not in response.text

    cleared = client.patch("/api/users/config", json={
        "clear_llm_api_key": True,
        "clear_github_token": True,
        "clear_github_webhook_secret": True,
    })
    assert cleared.status_code == 200
    assert cleared.json()["llm_api_key_configured"] is False
    assert cleared.json()["github_token_configured"] is False
    assert cleared.json()["github_webhook_secret_configured"] is False


def test_runtime_config_rejects_invalid_api_url(client: TestClient):
    response = client.patch("/api/users/config", json={"llm_api_base_url": "not-a-url"})
    assert response.status_code == 422


def test_saved_config_is_used_by_assistant_and_github_clients(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_base_url", "https://initial.example.com/v1")
    monkeypatch.setattr(settings, "llm_model", "initial-model")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "github_token", None)
    monkeypatch.setattr(settings, "github_webhook_secret", None)

    response = client.patch("/api/users/config", json={
        "llm_api_base_url": "https://runtime.example.com/v1",
        "llm_model": "runtime-model",
        "llm_api_key": "runtime-llm-key",
        "github_token": "runtime-github-token",
        "github_webhook_secret": "runtime-webhook-secret",
    })
    assert response.status_code == 200

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
    assert github_client_args["base_url"] == settings.github_api_base_url
    assert github_client_args["headers"]["Authorization"] == "Bearer runtime-github-token"
    assert settings.github_webhook_secret == "runtime-webhook-secret"
