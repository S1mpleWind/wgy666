"""Schemas for deterministic source architecture and impact analysis."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SymbolKind = Literal["module", "class", "function", "method", "component", "dependency"]
RelationKind = Literal["contains", "imports", "calls", "tests"]
HealthSeverity = Literal["info", "warning", "critical"]


class CodeSymbol(BaseModel):
    key: str
    name: str
    qualified_name: str
    kind: SymbolKind
    path: str | None = None
    language: str
    line_start: int | None = None
    line_end: int | None = None
    parent_key: str | None = None
    fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeRelation(BaseModel):
    source: str
    target: str
    relation: RelationKind
    evidence_path: str | None = None
    evidence_line: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ApiRoute(BaseModel):
    method: str
    route: str
    handler_key: str
    handler_name: str
    path: str
    line: int


class TestMapping(BaseModel):
    test_path: str
    source_paths: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ArchitectureDependency(BaseModel):
    name: str
    version: str | None = None
    ecosystem: str
    group: str
    source_file: str


class AnalysisCoverage(BaseModel):
    discovered_files: int
    indexed_files: int
    discovered_source_files: int
    parsed_source_files: int
    truncated_files: int
    file_coverage_percent: float = Field(ge=0.0, le=100.0)
    parser_coverage_percent: float = Field(ge=0.0, le=100.0)
    warnings: list[str] = Field(default_factory=list)


class ArchitectureHealthIssue(BaseModel):
    code: str
    severity: HealthSeverity
    title: str
    description: str
    evidence_paths: list[str] = Field(default_factory=list)
    suggestion: str


class ArchitectureHealth(BaseModel):
    score: int = Field(ge=0, le=100)
    grade: str
    metrics: dict[str, int | float] = Field(default_factory=dict)
    issues: list[ArchitectureHealthIssue] = Field(default_factory=list)


class ArchitectureAnalysis(BaseModel):
    repository: str
    revision: str
    generated_at: datetime
    parser_version: str
    coverage: AnalysisCoverage
    symbols: list[CodeSymbol] = Field(default_factory=list)
    relations: list[CodeRelation] = Field(default_factory=list)
    routes: list[ApiRoute] = Field(default_factory=list)
    test_mappings: list[TestMapping] = Field(default_factory=list)
    dependencies: list[ArchitectureDependency] = Field(default_factory=list)
    health: ArchitectureHealth


class ImpactAnalysisRequest(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=20)
    issue_text: str | None = Field(default=None, max_length=10000)
    max_depth: int = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def require_seed(self) -> "ImpactAnalysisRequest":
        if not self.paths and not (self.issue_text or "").strip():
            raise ValueError("Provide at least one path or issue_text.")
        return self


class ImpactNode(BaseModel):
    key: str
    label: str
    kind: str
    path: str | None = None
    depth: int = 0
    reason: str


class ImpactEdge(BaseModel):
    source: str
    target: str
    relation: str


class ImpactAnalysis(BaseModel):
    repository: str
    revision: str
    seed_paths: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    affected_symbols: list[CodeSymbol] = Field(default_factory=list)
    recommended_tests: list[TestMapping] = Field(default_factory=list)
    affected_routes: list[ApiRoute] = Field(default_factory=list)
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    reasons: list[str] = Field(default_factory=list)
    nodes: list[ImpactNode] = Field(default_factory=list)
    edges: list[ImpactEdge] = Field(default_factory=list)


class ArchitectureHistoryItem(BaseModel):
    revision: str
    generated_at: datetime
    symbol_count: int
    relation_count: int
    route_count: int
    health_score: int


class ArchitectureDiff(BaseModel):
    repository: str
    base_revision: str
    target_revision: str
    added_symbols: list[CodeSymbol] = Field(default_factory=list)
    removed_symbols: list[CodeSymbol] = Field(default_factory=list)
    changed_symbols: list[CodeSymbol] = Field(default_factory=list)
    added_routes: list[ApiRoute] = Field(default_factory=list)
    removed_routes: list[ApiRoute] = Field(default_factory=list)
    added_dependencies: list[ArchitectureDependency] = Field(default_factory=list)
    removed_dependencies: list[ArchitectureDependency] = Field(default_factory=list)
    health_score_delta: int
