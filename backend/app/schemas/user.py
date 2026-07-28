"""Request and response models for user management and authentication."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Payload for creating a user (registration)."""

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("name", "email")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.lower()
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must be a valid address")
        return value


class UserUpdate(BaseModel):
    """Payload for updating one or more user fields."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    password: str | None = Field(default=None, min_length=6, max_length=128)

    @field_validator("name", "email")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must be a valid address")
        return value

    @model_validator(mode="after")
    def require_a_field(self) -> "UserUpdate":
        if self.name is None and self.email is None and self.password is None:
            raise ValueError("at least one field must be provided")
        return self


class User(BaseModel):
    """Public representation of a user."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    email: str
    role: str = "user"
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Payload for logging in."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    """JWT token returned on successful login."""

    access_token: str
    token_type: str = "bearer"
    user: User


# ---------------------------------------------------------------------------
# Per-User Configuration
# ---------------------------------------------------------------------------


class UserConfigUpdate(BaseModel):
    """Runtime integration settings editable per user."""

    llm_api_base_url: str | None = Field(default=None, max_length=2048)
    llm_model: str | None = Field(default=None, max_length=255)
    llm_api_key: str | None = Field(default=None, max_length=4096)
    github_token: str | None = Field(default=None, max_length=4096)
    github_webhook_secret: str | None = Field(default=None, max_length=4096)
    clear_llm_api_key: bool = False
    clear_github_token: bool = False
    clear_github_webhook_secret: bool = False

    @field_validator("llm_api_base_url")
    @classmethod
    def validate_api_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LLM API base URL must be an HTTP(S) URL")
        return value

    @field_validator("llm_model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value

    @field_validator("llm_api_key", "github_token", "github_webhook_secret")
    @classmethod
    def normalize_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class UserConfig(BaseModel):
    """Per-user integration settings; secret values are represented by flags."""

    llm_api_base_url: str
    llm_model: str
    llm_api_key_configured: bool
    github_token_configured: bool
    github_webhook_secret_configured: bool


class IntegrationConnection(BaseModel):
    """Health of one configured external integration."""

    status: Literal["connected", "configured", "failed", "not_configured"]
    message: str
    checked_at: datetime
    last_received_at: datetime | None = None


class IntegrationStatus(BaseModel):
    """Connectivity status for the current user's integrations."""

    llm: IntegrationConnection
    github: IntegrationConnection
    webhook: IntegrationConnection


class UsageStats(BaseModel):
    """Accumulated external API usage for one user."""

    llm_requests: int = 0
    github_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    updated_at: datetime | None = None


class UserWithConfig(BaseModel):
    """A user together with their integration config."""

    user: User
    config: UserConfig


# ---------------------------------------------------------------------------
# Legacy system-config aliases (kept for test compatibility)
# ---------------------------------------------------------------------------

SystemConfigUpdate = UserConfigUpdate
SystemConfig = UserConfig
