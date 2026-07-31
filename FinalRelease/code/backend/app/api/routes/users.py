"""User management and authentication endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.security import create_access_token, get_current_user
from app.schemas.user import (
    LoginRequest,
    IntegrationStatus,
    TokenResponse,
    UsageStats,
    User,
    UserConfig,
    UserConfigUpdate,
    UserCreate,
    UserUpdate,
    UserWithConfig,
)
from app.storage.users import DuplicateEmailError, get_user_store

router = APIRouter(prefix="/users", tags=["users"])

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate) -> TokenResponse:
    """Register a new user account and return a JWT token."""
    store = get_user_store()
    try:
        user = store.create_user(payload.name, payload.email, payload.password)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, user=user)


@auth_router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    """Authenticate with email and password, return a JWT token."""
    store = get_user_store()
    user = store.authenticate(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, user=user)


@auth_router.get("/me", response_model=UserWithConfig)
async def get_me(current_user: User = Depends(get_current_user)) -> UserWithConfig:
    """Return the currently authenticated user and their config."""
    store = get_user_store()
    config = store.get_user_config(current_user.id) or UserConfig(
        llm_api_base_url="",
        llm_model="",
        llm_api_key_configured=False,
        github_token_configured=False,
        github_webhook_secret_configured=False,
    )
    return UserWithConfig(user=current_user, config=config)


# ---------------------------------------------------------------------------
# Per-User Configuration
# ---------------------------------------------------------------------------


@router.get("/me/config", response_model=UserConfig)
async def get_my_config(current_user: User = Depends(get_current_user)) -> UserConfig:
    """Return the current user's integration config."""
    store = get_user_store()
    config = store.get_user_config(current_user.id)
    if config is None:
        return UserConfig(
            llm_api_base_url="",
            llm_model="",
            llm_api_key_configured=False,
            github_token_configured=False,
            github_webhook_secret_configured=False,
        )
    return config


@router.patch("/me/config", response_model=UserConfig)
async def update_my_config(
    payload: UserConfigUpdate,
    current_user: User = Depends(get_current_user),
) -> UserConfig:
    """Update the current user's integration config."""
    store = get_user_store()
    return store.upsert_user_config(current_user.id, payload)


@router.get("/me/integrations/status", response_model=IntegrationStatus)
async def get_my_integration_status(
    _current_user: User = Depends(get_current_user),
) -> IntegrationStatus:
    """Actively validate LLM and GitHub credentials and report webhook readiness."""
    from app.services.integration_health import check_integrations

    return await check_integrations()


@router.get("/me/usage", response_model=UsageStats)
async def get_my_usage(current_user: User = Depends(get_current_user)) -> UsageStats:
    """Return accumulated external API requests and LLM token usage."""
    return get_user_store().get_usage(current_user.id)


# ---------------------------------------------------------------------------
# Admin permission helper
# ---------------------------------------------------------------------------


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require the current user to have the admin role."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return current_user


# ---------------------------------------------------------------------------
# User CRUD (admin-only for listing/deleting, self-service for profile)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[User])
async def list_users(
    _admin: User = Depends(require_admin),
) -> list[User]:
    """List all users (admin only)."""
    return get_user_store().list_users()


@router.get("/{user_id}", response_model=User)
async def get_user(
    user_id: UUID,
    _admin: User = Depends(require_admin),
) -> User:
    """Get a specific user by ID (admin only)."""
    user = get_user_store().get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User was not found.")
    return user


@router.patch("/{user_id}", response_model=User)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
) -> User:
    """Update your own profile (or any user if admin)."""
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="You can only update your own profile.")

    store = get_user_store()
    try:
        user = store.update_user(user_id, payload)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User was not found.")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
) -> Response:
    """Delete a user (admin only). Cannot delete yourself."""
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account.")
    if not get_user_store().delete_user(user_id):
        raise HTTPException(status_code=404, detail="User was not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
