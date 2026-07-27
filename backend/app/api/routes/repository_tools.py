"""Repository query tool endpoints for assistant and UI debugging."""

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.schemas.architecture import (
    ArchitectureAnalysis,
    ArchitectureDiff,
    ArchitectureHistoryItem,
    ImpactAnalysis,
    ImpactAnalysisRequest,
)
from app.schemas.assistant import FreshnessMode
from app.schemas.project_analysis import ProjectAnalysis
from app.schemas.repository_tools import FileSearchResult, IssueSearchResult, RepositoryOverview
from app.services.github_client import GitHubClientError
from app.services.architecture_analysis import ArchitectureAnalysisService
from app.services.project_analysis import ProjectAnalysisService
from app.services.repository_query import RepositoryQueryService
from app.storage import repository_store

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


@router.get("/file-contents")
async def list_file_contents(
    owner: str,
    name: str,
) -> list[dict]:
    """List all synced source file contents for the repository."""
    contents = repository_store.get_file_contents(owner, name)
    if not contents:
        # Check if the repository exists at all
        snapshot = repository_store.get(owner, name)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail="Repository snapshot was not found. Sync it first.",
            )
    return contents


@router.get("/file-contents/{path:path}")
async def get_file_content(
    owner: str,
    name: str,
    path: str,
) -> dict:
    """Return the content of a single file by its full path from the database."""
    content = repository_store.get_file_content(owner, name, path)
    if content is None:
        snapshot = repository_store.get(owner, name)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail=f"Repository {owner}/{name} was not found. Sync it first.",
            )
        raise HTTPException(
            status_code=404,
            detail=f"File '{path}' not found in repository {owner}/{name}. Sync it first.",
        )
    return content


@router.get("/architecture", response_model=ArchitectureAnalysis)
async def get_architecture_analysis(
    owner: str,
    name: str,
    revision: str | None = None,
) -> ArchitectureAnalysis:
    """Return a persisted semantic architecture analysis for one revision."""
    snapshot, _ = await _get_snapshot(owner, name, FreshnessMode.CACHE_FIRST)
    current_revision = ArchitectureAnalysisService.revision_for(snapshot)
    stored = repository_store.get_architecture_analysis(owner, name, revision)
    if stored is not None and (
        stored.revision != current_revision
        or stored.parser_version == ArchitectureAnalysisService.parser_version
    ):
        return stored
    if revision and revision != current_revision:
        raise HTTPException(status_code=404, detail="Architecture revision was not found.")
    analysis = await asyncio.to_thread(ArchitectureAnalysisService().analyze, snapshot)
    return await asyncio.to_thread(repository_store.save_architecture_analysis, snapshot, analysis)


@router.post("/architecture/impact", response_model=ImpactAnalysis)
async def analyze_architecture_impact(
    owner: str,
    name: str,
    payload: ImpactAnalysisRequest,
) -> ImpactAnalysis:
    """Trace affected files, symbols, routes, and tests from paths or issue text."""
    snapshot, _ = await _get_snapshot(owner, name, FreshnessMode.CACHE_FIRST)
    analysis = repository_store.get_architecture_analysis(owner, name)
    current_revision = ArchitectureAnalysisService.revision_for(snapshot)
    if (
        analysis is None
        or (
            analysis.revision == current_revision
            and analysis.parser_version != ArchitectureAnalysisService.parser_version
        )
    ):
        generated = await asyncio.to_thread(ArchitectureAnalysisService().analyze, snapshot)
        analysis = await asyncio.to_thread(
            repository_store.save_architecture_analysis,
            snapshot,
            generated,
        )
    return await asyncio.to_thread(ArchitectureAnalysisService().impact, analysis, payload)


@router.get("/architecture/history", response_model=list[ArchitectureHistoryItem])
async def list_architecture_history(owner: str, name: str) -> list[ArchitectureHistoryItem]:
    """List up to twenty architecture snapshots, newest first."""
    snapshot, _ = await _get_snapshot(owner, name, FreshnessMode.CACHE_FIRST)
    current = repository_store.get_architecture_analysis(owner, name)
    if current is None or (
        current.revision == ArchitectureAnalysisService.revision_for(snapshot)
        and current.parser_version != ArchitectureAnalysisService.parser_version
    ):
        await asyncio.to_thread(repository_store.save_architecture_analysis, snapshot)
    history = repository_store.list_architecture_analyses(owner, name)
    return history


@router.get("/architecture/diff", response_model=ArchitectureDiff)
async def compare_architecture_revisions(
    owner: str,
    name: str,
    base_revision: str,
    target_revision: str,
) -> ArchitectureDiff:
    """Compare symbols, routes, dependencies, and health between revisions."""
    await _get_snapshot(owner, name, FreshnessMode.CACHE_FIRST)
    base = repository_store.get_architecture_analysis(owner, name, base_revision)
    target = repository_store.get_architecture_analysis(owner, name, target_revision)
    if base is None or target is None:
        raise HTTPException(status_code=404, detail="One or both architecture revisions were not found.")
    return await asyncio.to_thread(ArchitectureAnalysisService().diff, base, target)


async def _get_snapshot(owner: str, name: str, freshness: FreshnessMode):
    try:
        return await RepositoryQueryService().get_snapshot(owner, name, freshness)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
