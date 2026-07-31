"""Schemas for repository query tool endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.issue import GitHubIssue
from app.schemas.repository import (
    CategorySummary,
    ClassifiedFile,
    RepositoryIdentity,
    RepositoryStats,
)


class RepositoryOverview(BaseModel):
    """Compact repository overview returned by query tools."""

    identity: RepositoryIdentity
    description: str | None = None
    stats: RepositoryStats
    topics: list[str] = Field(default_factory=list)
    file_categories: list[CategorySummary] = Field(default_factory=list)
    issue_categories: list[CategorySummary] = Field(default_factory=list)
    synced_at: datetime
    used_cached_data: bool


class FileSearchResult(BaseModel):
    """File query tool response."""

    files: list[ClassifiedFile]
    used_cached_data: bool


class IssueSearchResult(BaseModel):
    """Issue query tool response."""

    issues: list[GitHubIssue]
    used_cached_data: bool
