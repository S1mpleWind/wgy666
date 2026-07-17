"""Schemas for rule-based repository structure analysis."""

from pydantic import BaseModel, Field

from app.schemas.repository import ClassifiedFile


class ProjectDirectory(BaseModel):
    """A top-level directory and its dominant file category."""

    name: str
    count: int
    main_category: str
    source_count: int = 0


class ProjectDependency(BaseModel):
    """A dependency parsed from a supported manifest file."""

    name: str
    ecosystem: str
    group: str
    source_file: str


class ProjectAnalysis(BaseModel):
    """Rule-based structural analysis derived from a repository snapshot."""

    project_type: str
    analyzed_file_count: int = 0
    analysis_warning: str | None = None
    source_count: int
    dependency_files: list[ClassifiedFile] = Field(default_factory=list)
    dependency_packages: list[ProjectDependency] = Field(default_factory=list)
    detected_frameworks: list[str] = Field(default_factory=list)
    test_files: list[ClassifiedFile] = Field(default_factory=list)
    doc_files: list[ClassifiedFile] = Field(default_factory=list)
    config_files: list[ClassifiedFile] = Field(default_factory=list)
    entry_files: list[ClassifiedFile] = Field(default_factory=list)
    ci_files: list[ClassifiedFile] = Field(default_factory=list)
    top_directories: list[ProjectDirectory] = Field(default_factory=list)
