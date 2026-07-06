"""Pydantic-settings configuration loaded from environment / .env file.

All settings are read from environment variables or a ``.env`` file.
Add new fields here as the project grows (database URL, Celery broker, etc.).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- GitHub API ---
    github_token: str | None = Field(
        default=None,
        validation_alias="GITHUB_TOKEN",
        description="GitHub personal access token for higher API rate limits.",
    )
    github_api_base_url: str = "https://api.github.com"
    github_api_version: str = "2022-11-28"
    request_timeout_seconds: float = 20.0

    # --- Webhook ---
    github_webhook_secret: str | None = Field(
        default=None,
        validation_alias="GITHUB_WEBHOOK_SECRET",
        description="Secret for verifying GitHub webhook HMAC signatures. "
                    "Set to a random string in production; leave empty in dev to skip verification.",
    )

    # --- CORS ---
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
