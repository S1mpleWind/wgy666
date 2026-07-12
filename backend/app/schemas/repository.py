"""Pydantic models for repository data, sync requests, and file classification.

These models define the API contract shared between the backend and frontend.
Always update ``frontend/src/api.ts`` when changing a model here.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl

from app.schemas.issue import GitHubIssue


class FileCategory(StrEnum):
    """High-level file type categories used by the rule classifier."""

    SOURCE = "source_code"
    TEST = "tests"
    DOCUMENTATION = "documentation"
    CONFIGURATION = "configuration"
    CI_CD = "ci_cd"
    DEPENDENCY = "dependency"
    BUILD = "build"
    ASSET = "assets"
    DATA = "data"
    OTHER = "other"


class SyncRepositoryRequest(BaseModel):
    """Request body for ``POST /api/repositories/sync``."""

    url: str = Field(
        min_length=1,
        examples=["https://github.com/fastapi/fastapi"],
    )
    max_issues: int = Field(default=30, ge=0, le=100)
    max_pull_requests: int = Field(default=20, ge=0, le=100)
    max_commits: int = Field(default=20, ge=0, le=100)
    max_tree_items: int = Field(default=500, ge=10, le=5000)


class RepositoryIdentity(BaseModel):
    """Basic repository identification and URL."""

    owner: str
    name: str
    full_name: str
    html_url: HttpUrl
    default_branch: str


class RepositoryStats(BaseModel):
    """Aggregated repository statistics from GitHub."""

    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    size_kb: int = 0
    primary_language: str | None = None
    languages: dict[str, int] = Field(default_factory=dict)


class ClassifiedFile(BaseModel):
    """A file in the repository tree with its assigned category."""

    path: str
    category: FileCategory
    size: int | None = None


class RepositoryFileContent(BaseModel):
    """Source or documentation content fetched for RAG indexing."""

    path: str
    category: FileCategory
    content: str
    size: int | None = None
    truncated: bool = False


class CategorySummary(BaseModel):
    """Aggregated count for a category (used for bar charts)."""

    category: str
    count: int


class PullRequestSummary(BaseModel):
    """Minimal pull request information."""

    number: int
    title: str
    state: str
    html_url: HttpUrl
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CommitSummary(BaseModel):
    """Minimal commit information."""

    sha: str
    message: str
    author: str | None = None
    html_url: HttpUrl | None = None
    committed_at: datetime | None = None


class RepositorySnapshot(BaseModel):
    """Complete snapshot of a synced repository.

    This is the primary data structure returned by the sync endpoint and
    cached in the storage layer.
    """

    identity: RepositoryIdentity
    description: str | None = None
    stats: RepositoryStats
    topics: list[str] = Field(default_factory=list)
    readme: str | None = None
    files: list[ClassifiedFile] = Field(default_factory=list)
    source_contents: list[RepositoryFileContent] = Field(default_factory=list)
    file_categories: list[CategorySummary] = Field(default_factory=list)
    issues: list[GitHubIssue] = Field(default_factory=list)
    issue_categories: list[CategorySummary] = Field(default_factory=list)
    pull_requests: list[PullRequestSummary] = Field(default_factory=list)
    recent_commits: list[CommitSummary] = Field(default_factory=list)
    synced_at: datetime


class RepositoryListItem(BaseModel):
    """Lightweight item for the repository listing endpoint."""

    owner: str
    name: str
    full_name: str
    html_url: HttpUrl
    description: str | None = None
    synced_at: datetime
    issue_count: int
    file_count: int
