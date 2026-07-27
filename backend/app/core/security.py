"""Password hashing, JWT tokens, and authentication middleware."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.effective_config import (
    EffectiveConfig,
    reset_effective_config,
    set_effective_config,
)
from app.schemas.user import User, UserConfig

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    """Return a bcrypt hash of the given password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plain-text password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    """Create a signed JWT for the given user id."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode = {"sub": user_id, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    """Decode and validate a JWT, returning the user_id (sub) or None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Auth middleware — sets effective config from JWT
# ---------------------------------------------------------------------------


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuthMiddleware(BaseHTTPMiddleware):
    """HTTP middleware that decodes the JWT and sets the effective config ContextVar.

    For authenticated requests, the user's DB config is loaded into the
    ContextVar so downstream consumers (GitHubClient, AgentHarness, etc.) can
    read from ``get_effective_config()`` without needing to pass config objects.
    For unauthenticated requests (webhooks, health checks), the ContextVar
    stays at its default, causing ``get_effective_config()`` to fall back to
    ``settings.*``.
    """

    async def dispatch(self, request: Request, call_next):
        user_id = None
        effective = None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            decoded = decode_access_token(token)
            if decoded:
                user_id = decoded

        if user_id:
            try:
                from app.storage.users import get_user_store
                store = get_user_store()
                db_user = store.get_user(UUID(user_id))
                if db_user:
                    db_config = store.get_user_config(UUID(user_id))
                    raw = store._get_raw_config(UUID(user_id))
                    effective = EffectiveConfig(
                        llm_api_base_url=(
                            db_config.llm_api_base_url if db_config and db_config.llm_api_base_url
                            else settings.llm_api_base_url
                        ),
                        llm_model=(
                            db_config.llm_model if db_config and db_config.llm_model
                            else settings.llm_model
                        ),
                        llm_api_key=(
                            raw.get("llm_api_key") if raw
                            else settings.llm_api_key
                        ),
                        github_token=(
                            raw.get("github_token") if raw
                            else settings.github_token
                        ),
                        github_webhook_secret=(
                            raw.get("github_webhook_secret") if raw
                            else settings.github_webhook_secret
                        ),
                    )
                    # Store user info in request state for route handlers
                    request.scope["user"] = db_user
            except Exception:
                # If user lookup fails (e.g., DB not available), fall back to defaults.
                pass

        config_token = set_effective_config(effective)
        try:
            return await call_next(request)
        finally:
            reset_effective_config(config_token)


# ---------------------------------------------------------------------------
# FastAPI dependency — get current authenticated user
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> User:
    """Require a valid JWT and return the authenticated user.

    Raises 401 if no token is provided or the token is invalid/expired.
    Can also be resolved from the middleware-set request scope.
    """
    # First try the middleware-set scope (covers requests that pass through AuthMiddleware)
    user = request.scope.get("user")
    if user is not None:
        return user

    # Fallback: decode token directly (for tests that don't use middleware)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.storage.users import get_user_store
    store = get_user_store()
    db_user = store.get_user(UUID(user_id))
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return db_user


async def get_optional_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    """Like get_current_user but returns None instead of raising 401."""
    try:
        return await get_current_user(request, token)
    except HTTPException:
        return None
