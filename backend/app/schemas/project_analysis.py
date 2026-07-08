"""Schemas for rule-based repository structure analysis."""

from pydantic import BaseModel, Field

from app.schemas.repository import ClassifiedFile


class ProjectDirectory(BaseModel):
    """A top-level directory and its dominant file category."""

    name: str
    count: int
    main_category: str


class ProjectAnalysis(BaseModel):
    """Rule-based structural analysis derived from a repository snapshot."""

    project_type: str
    source_count: int
    dependency_files: list[ClassifiedFile] = Field(default_factory=list)
    test_files: list[ClassifiedFile] = Field(default_factory=list)
    doc_files: list[ClassifiedFile] = Field(default_factory=list)
    config_files: list[ClassifiedFile] = Field(default_factory=list)
    entry_files: list[ClassifiedFile] = Field(default_factory=list)
    ci_files: list[ClassifiedFile] = Field(default_factory=list)
    top_directories: list[ProjectDirectory] = Field(default_factory=list)
