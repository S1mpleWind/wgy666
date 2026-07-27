"""User API route tests with authentication, roles, and per-user config."""

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.storage.users import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, reset_user_store


@pytest.fixture(autouse=True)
def clean_user_store(monkeypatch):
    """Reset the user store and clean up DB users between tests."""
    from app.core.config import settings
    from app.storage.database import users as users_table, user_configs as configs_table, create_database_engine
    from sqlalchemy import delete

    reset_user_store()

    if settings.database_url:
        try:
            engine = create_database_engine()
            with engine.begin() as conn:
                conn.execute(delete(configs_table))
                conn.execute(delete(users_table))
            engine.dispose()
        except Exception:
            pass

    yield
    reset_user_store()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_user(client: TestClient, name: str, email: str, password: str = "test123456") -> dict:
    """Register a user and return the response JSON with token."""
    resp = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": password,
    })
    assert resp.status_code == 201, f"Register failed: {resp.json()}"
    return resp.json()


def _login_as_admin(client: TestClient) -> str:
    """Login as the default admin and return the access token."""
    resp = client.post("/api/auth/login", json={
        "email": DEFAULT_ADMIN_EMAIL,
        "password": DEFAULT_ADMIN_PASSWORD,
    })
    assert resp.status_code == 200, f"Admin login failed: {resp.json()}"
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


def test_register_and_login(client: TestClient):
    """Register a new user, then login with the same credentials."""
    resp = client.post("/api/auth/register", json={
        "name": "Test User",
        "email": "test@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["name"] == "Test User"
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["role"] == "user"
    assert "password" not in str(data)

    token = data["access_token"]

    # Login
    resp2 = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "secret123",
    })
    assert resp2.status_code == 200
    assert "access_token" in resp2.json()

    # Get current user
    resp3 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp3.status_code == 200
    me = resp3.json()
    assert me["user"]["email"] == "test@example.com"
    assert me["user"]["role"] == "user"
    assert "config" in me


def test_register_duplicate_email(client: TestClient):
    """Registering the same email twice returns 409."""
    payload = {"name": "First", "email": "dup@example.com", "password": "secret123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    resp = client.post("/api/auth/register", json={
        "name": "Second", "email": "DUP@example.com", "password": "secret456",
    })
    assert resp.status_code == 409


def test_login_invalid_credentials(client: TestClient):
    """Login with wrong password returns 401."""
    client.post("/api/auth/register", json={
        "name": "User", "email": "user@example.com", "password": "correct",
    })
    resp = client.post("/api/auth/login", json={
        "email": "user@example.com", "password": "wrong",
    })
    assert resp.status_code == 401


def test_admin_seeded_on_startup(client: TestClient):
    """The default admin user is created automatically."""
    token = _login_as_admin(client)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["user"]["role"] == "admin"
    assert me["user"]["email"] == DEFAULT_ADMIN_EMAIL


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_unauthenticated_access_blocked(client: TestClient):
    """Endpoints that require auth should return 401 without a token."""
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users/me/config").status_code == 401
    assert client.patch("/api/users/me/config", json={}).status_code == 401


def test_non_admin_cannot_list_users(client: TestClient):
    """A regular user cannot list all users."""
    data = _register_user(client, "Regular", "regular@example.com")
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/users", headers=headers)
    assert resp.status_code == 403


def test_non_admin_cannot_delete_users(client: TestClient):
    """A regular user cannot delete other users."""
    data = _register_user(client, "Regular", "regular2@example.com")
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Try to delete the admin
    resp = client.delete("/api/users/00000000-0000-0000-0000-000000000001", headers=headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin user CRUD
# ---------------------------------------------------------------------------


def test_admin_can_list_users(client: TestClient):
    """Admin can list all users."""
    _register_user(client, "Alice", "alice@example.com")
    token = _login_as_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    users = client.get("/api/users", headers=headers).json()
    assert len(users) >= 2  # admin + alice
    roles = {u["email"]: u["role"] for u in users}
    assert roles.get(DEFAULT_ADMIN_EMAIL) == "admin"
    assert roles.get("alice@example.com") == "user"


def test_admin_can_get_user(client: TestClient):
    """Admin can get a specific user by ID."""
    data = _register_user(client, "Bob", "bob@example.com")
    user_id = data["user"]["id"]

    token = _login_as_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    user = client.get(f"/api/users/{user_id}", headers=headers).json()
    assert user["email"] == "bob@example.com"
    assert user["role"] == "user"


def test_admin_can_delete_user(client: TestClient):
    """Admin can delete a user."""
    data = _register_user(client, "Charlie", "charlie@example.com")
    user_id = data["user"]["id"]

    token = _login_as_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.delete(f"/api/users/{user_id}", headers=headers).status_code == 204
    assert client.get(f"/api/users/{user_id}", headers=headers).status_code == 404


def test_admin_cannot_delete_self(client: TestClient):
    """Admin cannot delete their own account."""
    token = _login_as_admin(client)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/auth/me", headers=headers).json()

    resp = client.delete(f"/api/users/{me['user']['id']}", headers=headers)
    assert resp.status_code == 400


def test_user_can_update_own_profile(client: TestClient):
    """A user can update their own name/email/password."""
    data = _register_user(client, "Dave", "dave@example.com")
    token = data["access_token"]
    user_id = data["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    updated = client.patch(f"/api/users/{user_id}", json={"name": "David"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["name"] == "David"


def test_user_cannot_update_others_profile(client: TestClient):
    """A regular user cannot update another user's profile."""
    _register_user(client, "Eve", "eve@example.com")
    data2 = _register_user(client, "Frank", "frank@example.com")
    eve_id = data2["user"]["id"]

    # Login as eve, try to update frank's profile
    resp = client.post("/api/auth/login", json={"email": "eve@example.com", "password": "test123456"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp2 = client.patch(f"/api/users/{eve_id}", json={"name": "Hacked"}, headers=headers)
    assert resp2.status_code == 403


# ---------------------------------------------------------------------------
# Per-User Config
# ---------------------------------------------------------------------------


def test_per_user_config(client: TestClient):
    """Test that each user has their own isolated config."""
    r1 = client.post("/api/auth/register", json={
        "name": "U1", "email": "u1@example.com", "password": "pw123456",
    })
    r2 = client.post("/api/auth/register", json={
        "name": "U2", "email": "u2@example.com", "password": "pw123456",
    })
    t1 = r1.json()["access_token"]
    t2 = r2.json()["access_token"]
    h1 = {"Authorization": f"Bearer {t1}"}
    h2 = {"Authorization": f"Bearer {t2}"}

    # User 1 sets their config
    resp = client.patch("/api/users/me/config", json={
        "llm_api_base_url": "https://u1.example.com/v1",
        "llm_model": "u1-model",
        "llm_api_key": "u1-key",
        "github_token": "u1-token",
    }, headers=h1)
    assert resp.status_code == 200
    c1 = resp.json()
    assert c1["llm_api_base_url"] == "https://u1.example.com/v1"
    assert c1["llm_model"] == "u1-model"
    assert c1["llm_api_key_configured"] is True
    assert c1["github_token_configured"] is True

    # User 2 sets different config
    resp2 = client.patch("/api/users/me/config", json={
        "llm_api_base_url": "https://u2.example.com/v1",
        "llm_model": "u2-model",
        "llm_api_key": "u2-key",
    }, headers=h2)
    assert resp2.status_code == 200
    c2 = resp2.json()
    assert c2["llm_api_base_url"] == "https://u2.example.com/v1"
    assert c2["llm_model"] == "u2-model"

    # Verify isolation
    c1_again = client.get("/api/users/me/config", headers=h1).json()
    assert c1_again["llm_api_base_url"] == "https://u1.example.com/v1"
    assert c1_again["llm_api_key_configured"] is True

    c2_again = client.get("/api/users/me/config", headers=h2).json()
    assert c2_again["llm_api_base_url"] == "https://u2.example.com/v1"
    assert c2_again["llm_api_key_configured"] is True


def test_config_clear_secrets(client: TestClient):
    """Test clearing secrets via config endpoint."""
    r = client.post("/api/auth/register", json={
        "name": "U", "email": "u@example.com", "password": "pw123456",
    })
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.patch("/api/users/me/config", json={
        "llm_api_key": "my-key",
        "github_token": "my-token",
        "github_webhook_secret": "my-secret",
    }, headers=headers)

    config = client.get("/api/users/me/config", headers=headers).json()
    assert config["llm_api_key_configured"] is True
    assert config["github_token_configured"] is True
    assert config["github_webhook_secret_configured"] is True

    cleared = client.patch("/api/users/me/config", json={
        "clear_llm_api_key": True,
        "clear_github_token": True,
        "clear_github_webhook_secret": True,
    }, headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["llm_api_key_configured"] is False
    assert cleared.json()["github_token_configured"] is False
    assert cleared.json()["github_webhook_secret_configured"] is False


def test_config_rejects_invalid_url(client: TestClient):
    """Invalid API URL should be rejected with 422."""
    r = client.post("/api/auth/register", json={
        "name": "U", "email": "u2@example.com", "password": "pw123456",
    })
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch("/api/users/me/config", json={"llm_api_base_url": "not-a-url"}, headers=headers)
    assert resp.status_code == 422
