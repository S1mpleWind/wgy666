"""Schemas for graph-enhanced repository knowledge bases."""

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeNode(BaseModel):
    """A typed entity discovered from a repository snapshot."""

    key: str
    type: str
    name: str
    path: str | None = None
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeEdge(BaseModel):
    """A relationship between two repository knowledge nodes."""

    source: str
    target: str
    relation: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    """A retrievable text unit grounded in graph entities."""

    key: str
    title: str
    content: str
    source_type: str
    source_path: str | None = None
    node_keys: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None


class KnowledgeSearchResult(BaseModel):
    """A ranked Graph RAG retrieval result."""

    chunk: KnowledgeChunk
    score: float
    related_nodes: list[KnowledgeNode] = Field(default_factory=list)
    related_edges: list[KnowledgeEdge] = Field(default_factory=list)


class RepositoryKnowledgeGraph(BaseModel):
    """Graph-enhanced RAG knowledge base derived from one repository."""

    repository: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
