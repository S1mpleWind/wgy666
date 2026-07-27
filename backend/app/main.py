"""FastAPI application factory and root configuration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.assistant.router import router as assistant_router
from app.api.routes import health, issues, repositories, repository_tools, users
from app.core.config import settings
from app.core.security import AuthMiddleware
from app.api.routes.faq import router as faq_router
from app.webhooks.router import router as webhooks_router


from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    """Build the FastAPI application with middleware and route registration.

    Router prefix convention:
      - /api/repositories/*  — repository sync, list, and detail
      - /api/issues/*        — standalone issue classification
      - /api/auth/*          — user registration, login, token refresh
      - /api/users/*         — user management (authenticated)
      - /api/webhooks/*      — GitHub webhook event receiver
    """
    app = FastAPI(
        title="GitHub Issue Analysis Platform API",
        version="0.1.0",
        description=(
            "Base backend for syncing GitHub repositories and "
            "classifying project files and issues."
        ),
    )

    # Allow the Vite dev server (port 5173) to call the API during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware — sets effective user config ContextVar from JWT.
    # Runs after CORS so preflight requests don't trigger auth logic.
    app.add_middleware(AuthMiddleware)

    app.include_router(health.router, prefix="/api")
    app.include_router(repositories.router, prefix="/api")
    app.include_router(repository_tools.router, prefix="/api")
    app.include_router(issues.router, prefix="/api")
    app.include_router(users.auth_router, prefix="/api")  # /api/auth/*
    app.include_router(users.router, prefix="/api")       # /api/users/*
    app.include_router(assistant_router, prefix="/api")
    app.include_router(webhooks_router, prefix="/api")
    app.include_router(faq_router, prefix="/api")
    return app


# Module-level instance for uvicorn to discover (app = create_app()).
app = create_app()
