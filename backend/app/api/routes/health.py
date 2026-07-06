"""Basic health check endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return ``{"status": "ok"}`` — used by monitoring and frontend connectivity checks."""
    return {"status": "ok"}
