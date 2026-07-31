"""Pydantic models for issue data and classification results.

These models define the API contract shared between the backend and frontend.
Always update ``frontend/src/api.ts`` when changing a model here.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class IssueCategory(StrEnum):
    """Taxonomy of GitHub issue types used throughout the system."""

    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    QUESTION = "question"
    DOCUMENTATION = "documentation"
    DUPLICATE = "duplicate"
    INFO_NEEDED = "info_needed"
    INVALID = "invalid"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class IssueAnalysisRequest(BaseModel):
    """Request body for ``POST /api/issues/analyze`` (standalone classification)."""

    title: str = Field(min_length=1)
    body: str | None = None
    labels: list[str] = Field(default_factory=list)


class IssueClassification(BaseModel):
    """Result of classifying a single issue."""

    category: IssueCategory
    confidence: float = Field(ge=0, le=1)
    reason: str
    suggested_action: str
    signals: list[str] = Field(default_factory=list)
    auto_reply_draft: str | None = Field(
        default=None,
        description="LLM-generated draft reply for non-bug issues.",
    )


class GitHubIssue(BaseModel):
    """Normalized GitHub issue with embedded classification."""

    number: int
    title: str
    state: str
    html_url: HttpUrl
    author: str | None = None
    labels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    comments: int = 0
    classification: IssueClassification
