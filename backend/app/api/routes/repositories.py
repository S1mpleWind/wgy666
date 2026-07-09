"""Repository sync and listing endpoints."""

from fastapi import APIRouter, HTTPException

from app.schemas.repository import RepositoryListItem, RepositorySnapshot, SyncRepositoryRequest
from app.services.github_client import GitHubClientError
from app.services.repository_sync import RepositorySyncService
from app.storage import repository_store

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post("/sync", response_model=RepositorySnapshot)
async def sync_repository(payload: SyncRepositoryRequest) -> RepositorySnapshot:
    """Fetch repository data from GitHub, classify files and issues, cache the snapshot.

    This is a synchronous (blocking) request. Large repositories may take
    several seconds.
    """
    service = RepositorySyncService()
    try:
        snapshot = await service.sync(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    repository_store.save(snapshot)
    return snapshot


@router.get("", response_model=list[RepositoryListItem])
async def list_repositories() -> list[RepositoryListItem]:
    """Return all synced repositories, most recently synced first."""
    return repository_store.list()


@router.get("/{owner}/{name}", response_model=RepositorySnapshot)
async def get_repository(owner: str, name: str) -> RepositorySnapshot:
    """Return the cached snapshot for a previously synced repository."""
    snapshot = repository_store.get(owner, name)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Repository snapshot was not found. Sync it first.")
    return snapshot
