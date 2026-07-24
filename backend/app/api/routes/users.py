"""User management endpoints."""

from uuid import UUID
from threading import RLock

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import persist_system_config, settings
from app.schemas.user import SystemConfig, SystemConfigUpdate, User, UserCreate, UserUpdate
from app.storage.users import DuplicateEmailError, user_store

router = APIRouter(prefix="/users", tags=["users"])
config_lock = RLock()


def current_system_config() -> SystemConfig:
    return SystemConfig(
        llm_api_base_url=settings.llm_api_base_url,
        llm_model=settings.llm_model,
        llm_api_key_configured=bool(settings.llm_api_key),
        github_token_configured=bool(settings.github_token),
        github_webhook_secret_configured=bool(settings.github_webhook_secret),
    )


@router.post("", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> User:
    try:
        return user_store.create(payload)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc


@router.get("", response_model=list[User])
async def list_users() -> list[User]:
    return user_store.list()


@router.get("/config", response_model=SystemConfig)
async def get_system_config() -> SystemConfig:
    """Return non-secret integration settings and secret presence flags."""
    return current_system_config()


@router.patch("/config", response_model=SystemConfig)
async def update_system_config(payload: SystemConfigUpdate) -> SystemConfig:
    """Update and persist integrations without returning stored secrets."""
    with config_lock:
        if payload.llm_api_base_url is not None:
            settings.llm_api_base_url = payload.llm_api_base_url
        if payload.llm_model is not None:
            settings.llm_model = payload.llm_model

        if payload.clear_llm_api_key:
            settings.llm_api_key = None
        elif payload.llm_api_key is not None:
            settings.llm_api_key = payload.llm_api_key

        if payload.clear_github_token:
            settings.github_token = None
        elif payload.github_token is not None:
            settings.github_token = payload.github_token

        if payload.clear_github_webhook_secret:
            settings.github_webhook_secret = None
        elif payload.github_webhook_secret is not None:
            settings.github_webhook_secret = payload.github_webhook_secret

        persist_system_config()
        return current_system_config()


@router.get("/{user_id}", response_model=User)
async def get_user(user_id: UUID) -> User:
    user = user_store.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User was not found.")
    return user


@router.patch("/{user_id}", response_model=User)
async def update_user(user_id: UUID, payload: UserUpdate) -> User:
    try:
        user = user_store.update(user_id, payload)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User was not found.")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: UUID) -> Response:
    if not user_store.delete(user_id):
        raise HTTPException(status_code=404, detail="User was not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
