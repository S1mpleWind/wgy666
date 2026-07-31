"""ContextVar-based effective configuration for per-request user config.

This module provides a thread/asyncio-safe way to pass the current user's
config to downstream consumers (GitHubClient, AgentHarness, etc.) without
requiring every function signature to include a config parameter.

How it works:
1. ``AuthMiddleware`` (in security.py) decodes the JWT, looks up the user's
   config from the DB, and calls ``set_effective_config()``.
2. Any code that currently reads from ``settings.xxx`` instead calls
   ``get_effective_config()`` to get the effective config for the current
   request — user-specific if authenticated, server defaults otherwise.
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class EffectiveConfig:
    """Resolved configuration for the current request context."""

    llm_api_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str | None = None
    github_token: str | None = None
    github_webhook_secret: str | None = None
    user_id: str | None = None


_current_config: ContextVar[EffectiveConfig | None] = ContextVar(
    "current_effective_config", default=None
)


def set_effective_config(config: EffectiveConfig | None) -> Token:
    """Set the effective config for the current async context."""
    return _current_config.set(config)


def reset_effective_config(token: Token) -> None:
    """Restore the effective config that was active before ``token``."""
    _current_config.reset(token)


def get_effective_config() -> EffectiveConfig:
    """Return the effective config for the current request.

    If a user-specific config was set by AuthMiddleware, returns it.
    Otherwise falls back to server-level settings from ``.env``.
    """
    ctx = _current_config.get(None)
    if ctx is not None:
        return ctx

    # Fall back to server defaults
    return EffectiveConfig(
        llm_api_base_url=settings.llm_api_base_url,
        llm_model=settings.llm_model,
        llm_api_key=settings.llm_api_key,
        github_token=settings.github_token,
        github_webhook_secret=settings.github_webhook_secret,
    )
