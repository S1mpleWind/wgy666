"""Schemas for repository assistant chat and tool results."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class FreshnessMode(StrEnum):
    """How aggressively query tools should refresh repository data."""

    CACHE_FIRST = "cache_first"
    REFRESH_IF_STALE = "refresh_if_stale"
    FORCE_REFRESH = "force_refresh"


class ChatMessage(BaseModel):
    """A prior chat message sent by the user or assistant."""

    role: Literal["user", "assistant"]
    content: str


class AssistantChatRequest(BaseModel):
    """Request body for asking the repository assistant a question."""

    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    message: str = Field(min_length=1)
    freshness: FreshnessMode = FreshnessMode.CACHE_FIRST
    history: list[ChatMessage] = Field(default_factory=list)


class AssistantToolCall(BaseModel):
    """A tool invocation performed by the assistant harness."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str


class AssistantCitation(BaseModel):
    """Evidence returned with an assistant answer."""

    type: str
    label: str
    url: HttpUrl | None = None
    path: str | None = None


class AssistantChatResponse(BaseModel):
    """Answer returned by the repository assistant."""

    answer: str
    repository: str
    used_cached_data: bool
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)
    citations: list[AssistantCitation] = Field(default_factory=list)
