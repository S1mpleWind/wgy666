"""Repository query tool endpoints for assistant and UI debugging."""

from fastapi import APIRouter, HTTPException, Query

from app.schemas.assistant import FreshnessMode
from app.schemas.project_analysis import ProjectAnalysis
from app.schemas.repository_tools import FileSearchResult, IssueSearchResult, RepositoryOverview
from app.services.github_client import GitHubClientError
from app.services.project_analysis import ProjectAnalysisService
from app.services.repository_query import RepositoryQueryService

router = APIRouter(prefix="/repositories/{owner}/{name}/tools", tags=["repository-tools"])


@router.get("/overview", response_model=RepositoryOverview)
async def get_overview(
    owner: str,
    name: str,
    freshness: FreshnessMode = FreshnessMode.REFRESH_IF_STALE,
) -> RepositoryOverview:
    """Return compact repository metadata and category summaries."""
    snapshot, used_cached_data = await _get_snapshot(owner, name, freshness)
    return RepositoryOverview(
        identity=snapshot.identity,
        description=snapshot.description,
        stats=snapshot.stats,
        topics=snapshot.topics,
        file_categories=snapshot.file_categories,
        issue_categories=snapshot.issue_categories,
        synced_at=snapshot.synced_at,
        used_cached_data=used_cached_data,
    )


@router.get("/project-structure", response_model=ProjectAnalysis)
async def get_project_structure(
    owner: str,
    name: str,
    freshness: FreshnessMode = FreshnessMode.REFRESH_IF_STALE,
) -> ProjectAnalysis:
    """Return rule-based project structure analysis."""
    snapshot, _ = await _get_snapshot(owner, name, freshness)
    return ProjectAnalysisService().analyze(snapshot)


@router.get("/files", response_model=FileSearchResult)
async def search_files(
    owner: str,
    name: str,
    query: str | None = None,
    category: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    freshness: FreshnessMode = FreshnessMode.REFRESH_IF_STALE,
) -> FileSearchResult:
    """Search files by path substring and/or category."""
    service = RepositoryQueryService()
    snapshot, used_cached_data = await _get_snapshot(owner, name, freshness)
    return FileSearchResult(
        files=service.search_files(snapshot, query=query, category=category, limit=limit),
        used_cached_data=used_cached_data,
    )


@router.get("/issues", response_model=IssueSearchResult)
async def list_issues(
    owner: str,
    name: str,
    category: str | None = None,
    state: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    freshness: FreshnessMode = FreshnessMode.REFRESH_IF_STALE,
) -> IssueSearchResult:
    """List issues by category and/or state."""
    service = RepositoryQueryService()
    snapshot, used_cached_data = await _get_snapshot(owner, name, freshness)
    return IssueSearchResult(
        issues=service.list_issues(snapshot, category=category, state=state, limit=limit),
        used_cached_data=used_cached_data,
    )


async def _get_snapshot(owner: str, name: str, freshness: FreshnessMode):
    try:
        return await RepositoryQueryService().get_snapshot(owner, name, freshness)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
