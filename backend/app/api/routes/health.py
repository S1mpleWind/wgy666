"""Basic health check endpoint."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=None)
async def health_check() -> dict[str, str] | JSONResponse:
    """Report API and configured database availability."""
    if not settings.database_url:
        return {"status": "ok", "database": "not_configured"}

    from app.storage.database import create_database_engine
    from sqlalchemy import text

    engine = create_database_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unavailable"},
        )
    finally:
        engine.dispose()
