"""Pydantic settings and persistence for runtime-editable integrations.

All settings are read from environment variables or a ``.env`` file.
Add new fields here as the project grows (database URL, Celery broker, etc.).
"""

import os
from pathlib import Path

from dotenv import set_key

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
    request_timeout_seconds: float = 200
    github_request_retries: int = Field(
        default=3,
        validation_alias="GITHUB_REQUEST_RETRIES",
        description="Max retries (with exponential backoff) for transient GitHub API failures.",
    )

    # --- Database ---
    database_url: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
        description=(
            "SQLAlchemy PostgreSQL URL. When unset, the app falls back to "
            "the in-memory development store."
        ),
    )

    # --- Webhook ---
    github_webhook_secret: str | None = Field(
        default=None,
        validation_alias="GITHUB_WEBHOOK_SECRET",
        description="Secret for verifying GitHub webhook HMAC signatures. "
                    "Set to a random string in production; leave empty in dev to skip verification.",
    )

    # --- LLM / OpenAI-compatible chat completions ---
    llm_api_base_url: str = Field(
        default="https://models.sjtu.edu.cn/api/v1",
        validation_alias="LLM_API_BASE_URL",
        description="OpenAI-compatible API base URL.",
    )
    llm_api_key: str | None = Field(
        default=None,
        validation_alias="LLM_API_KEY",
        description="OpenAI-compatible API key. Never commit real keys.",
    )
    llm_model: str = Field(
        default="deepseek-reasoner",
        validation_alias="LLM_MODEL",
        description="Model name for assistant answer synthesis.",
    )
    llm_timeout_seconds: float = Field(default=60.0, validation_alias="LLM_TIMEOUT_SECONDS")
    assistant_max_tool_rounds: int = Field(default=3, validation_alias="ASSISTANT_MAX_TOOL_ROUNDS")

    # --- Git Clone ---
    git_clone_timeout_seconds: float = Field(
        default=120.0,
        validation_alias="GIT_CLONE_TIMEOUT_SECONDS",
        description="Max seconds to wait for a shallow clone before timing out.",
    )

    # --- RAG / Embeddings ---
    embedding_api_base_url: str = Field(default="https://models.sjtu.edu.cn/api/v1", validation_alias="EMBEDDING_API_BASE_URL")
    embedding_api_key: str | None = Field(default=None, validation_alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="text-embedding-3-small", validation_alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=1536, validation_alias="EMBEDDING_DIMENSIONS")
    embedding_batch_size: int = Field(default=64, validation_alias="EMBEDDING_BATCH_SIZE", ge=1, le=256)

    # Local embedding (sentence-transformers) — off by default.
    # When enabled, the local model takes priority over the remote API.
    local_embedding_enabled: bool = Field(
        default=False,
        validation_alias="LOCAL_EMBEDDING_ENABLED",
        description="Set to true to use a local sentence-transformers model instead of a remote embedding API.",
    )
    local_embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        validation_alias="LOCAL_EMBEDDING_MODEL",
        description="HuggingFace sentence-transformers model name. all-MiniLM-L6-v2 is ~80 MB / 384 dims.",
    )

    rag_max_source_files: int = Field(default=500, validation_alias="RAG_MAX_SOURCE_FILES")
    rag_max_source_file_bytes: int = Field(default=200000, validation_alias="RAG_MAX_SOURCE_FILE_BYTES")
    rag_chunk_size: int = Field(default=1800, validation_alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(default=250, validation_alias="RAG_CHUNK_OVERLAP")

    # --- CORS ---
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


def runtime_env_file() -> Path:
    """Return the env file used for settings saved through the frontend."""
    override = os.environ.get("ISSUESCOPE_RUNTIME_ENV_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / ".env"


def persist_system_config() -> None:
    """Persist editable integrations so they survive a backend restart."""
    env_file = runtime_env_file()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "LLM_API_BASE_URL": settings.llm_api_base_url,
        "LLM_MODEL": settings.llm_model,
        "LLM_API_KEY": settings.llm_api_key or "",
        "GITHUB_TOKEN": settings.github_token or "",
        "GITHUB_WEBHOOK_SECRET": settings.github_webhook_secret or "",
    }
    for key, value in values.items():
        set_key(str(env_file), key, value, quote_mode="always")
