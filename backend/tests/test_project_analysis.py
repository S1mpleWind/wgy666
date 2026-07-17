"""Focused tests for the non-AI project structure analysis rules."""

from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.repository import (
    CategorySummary,
    ClassifiedFile,
    FileCategory,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.services.project_analysis import ProjectAnalysisService
from app.storage import repository_store


def _snapshot(
    *,
    languages: dict[str, int],
    primary_language: str | None,
    files: list[ClassifiedFile] | None = None,
    source_contents: list[RepositoryFileContent] | None = None,
) -> RepositorySnapshot:
    sample_files = files or []
    category_counts: dict[str, int] = {}
    for file in sample_files:
        category_counts[file.category.value] = category_counts.get(file.category.value, 0) + 1

    return RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="course-team",
            name="sample",
            full_name="course-team/sample",
            html_url="https://github.com/course-team/sample",
            default_branch="main",
        ),
        stats=RepositoryStats(
            primary_language=primary_language,
            languages=languages,
        ),
        files=sample_files,
        source_contents=source_contents or [],
        file_categories=[
            CategorySummary(category=category, count=count)
            for category, count in category_counts.items()
        ],
        synced_at=datetime.now(timezone.utc),
    )


def test_tiny_web_language_share_does_not_make_python_project_full_stack() -> None:
    snapshot = _snapshot(
        languages={"Python": 3_936_948, "JavaScript": 1_066, "HTML": 235, "CSS": 25},
        primary_language="Python",
    )

    analysis = ProjectAnalysisService().analyze(snapshot)

    assert analysis.project_type == "Python backend or tooling project"


def test_meaningful_python_and_frontend_shares_are_full_stack() -> None:
    snapshot = _snapshot(
        languages={"Python": 700_000, "TypeScript": 300_000},
        primary_language="Python",
    )

    analysis = ProjectAnalysisService().analyze(snapshot)

    assert analysis.project_type == "Full-stack project: Python backend plus web frontend"


def test_entry_candidates_only_include_source_files_outside_example_and_test_directories() -> None:
    snapshot = _snapshot(
        languages={"Python": 1_000},
        primary_language="Python",
        files=[
            ClassifiedFile(path="backend/app.py", category=FileCategory.SOURCE),
            ClassifiedFile(path="docs/example/main.py", category=FileCategory.SOURCE),
            ClassifiedFile(path="tests/app.py", category=FileCategory.SOURCE),
            ClassifiedFile(path="examples/server.py", category=FileCategory.SOURCE),
            ClassifiedFile(path="notes/main.py", category=FileCategory.DOCUMENTATION),
        ],
    )

    analysis = ProjectAnalysisService().analyze(snapshot)

    assert [file.path for file in analysis.entry_files] == ["backend/app.py"]


def test_entry_candidates_prioritize_conventional_application_directories() -> None:
    snapshot = _snapshot(
        languages={"Python": 700, "TypeScript": 300},
        primary_language="Python",
        files=[
            ClassifiedFile(path="frontend/src/App.tsx", category=FileCategory.SOURCE),
            ClassifiedFile(path="frontend/src/main.tsx", category=FileCategory.SOURCE),
            ClassifiedFile(path="backend/main.py", category=FileCategory.SOURCE),
            ClassifiedFile(path="backend/app/main.py", category=FileCategory.SOURCE),
        ],
    )

    analysis = ProjectAnalysisService().analyze(snapshot)

    assert [file.path for file in analysis.entry_files] == [
        "backend/app/main.py",
        "frontend/src/main.tsx",
        "backend/main.py",
        "frontend/src/App.tsx",
    ]


def test_analysis_combines_sampled_tree_with_complete_indexed_files() -> None:
    snapshot = _snapshot(
        languages={"Python": 1_000},
        primary_language="Python",
        files=[
            ClassifiedFile(path="README.md", category=FileCategory.DOCUMENTATION),
            ClassifiedFile(path="backend/app/main.py", category=FileCategory.SOURCE),
        ],
        source_contents=[
            RepositoryFileContent(
                path="backend/app/main.py",
                category=FileCategory.SOURCE,
                content="from fastapi import FastAPI\napp = FastAPI()",
            ),
            RepositoryFileContent(
                path="backend/app/services/sync.py",
                category=FileCategory.SOURCE,
                content="def sync(): pass",
            ),
            RepositoryFileContent(
                path="backend/tests/test_sync.py",
                category=FileCategory.TEST,
                content="def test_sync(): pass",
            ),
        ],
    )

    analysis = ProjectAnalysisService().analyze(snapshot)

    assert analysis.analyzed_file_count == 4
    assert analysis.source_count == 2
    backend_directory = next(item for item in analysis.top_directories if item.name == "backend")
    assert backend_directory.source_count == 2
    assert [file.path for file in analysis.entry_files] == ["backend/app/main.py"]
    assert [file.path for file in analysis.test_files] == ["backend/tests/test_sync.py"]


def test_analysis_parses_python_and_node_dependency_manifests() -> None:
    package_json = json.dumps(
        {
            "dependencies": {"react": "^19", "axios": "^1"},
            "devDependencies": {
                "@vitejs/plugin-react": "latest",
                "vite": "^8",
                "typescript": "^6",
            },
        }
    )
    pyproject = """
[project]
dependencies = ["fastapi>=0.139", "sqlalchemy>=2", "pydantic-settings>=2"]

[dependency-groups]
dev = ["pytest>=9", "ruff>=0.9"]
"""
    snapshot = _snapshot(
        languages={"Python": 700, "TypeScript": 300},
        primary_language="Python",
        source_contents=[
            RepositoryFileContent(
                path="backend/pyproject.toml",
                category=FileCategory.DEPENDENCY,
                content=pyproject,
            ),
            RepositoryFileContent(
                path="frontend/package.json",
                category=FileCategory.DEPENDENCY,
                content=package_json,
            ),
            RepositoryFileContent(
                path="prototype/package.json",
                category=FileCategory.DEPENDENCY,
                content=package_json,
            ),
        ],
    )

    analysis = ProjectAnalysisService().analyze(snapshot)
    packages = {item.name: item for item in analysis.dependency_packages}

    assert set(packages) == {
        "@vitejs/plugin-react",
        "axios",
        "fastapi",
        "pydantic-settings",
        "pytest",
        "react",
        "ruff",
        "sqlalchemy",
        "typescript",
        "vite",
    }
    assert packages["fastapi"].group == "runtime_framework"
    assert packages["sqlalchemy"].group == "data_interface"
    assert packages["pytest"].group == "development"
    assert analysis.detected_frameworks == ["FastAPI", "React", "Vite"]
    assert sum(item.name == "react" for item in analysis.dependency_packages) == 2


def test_project_structure_endpoint_returns_cached_backend_analysis() -> None:
    snapshot = _snapshot(
        languages={"Python": 1_000},
        primary_language="Python",
        files=[ClassifiedFile(path="app/main.py", category=FileCategory.SOURCE)],
    )
    snapshot.identity.owner = "project-analysis-api"
    snapshot.identity.name = "repo"
    snapshot.identity.full_name = "project-analysis-api/repo"
    repository_store.save(snapshot)

    response = TestClient(create_app()).get(
        "/api/repositories/project-analysis-api/repo/tools/project-structure",
        params={"freshness": "cache_first"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analyzed_file_count"] == 1
    assert payload["source_count"] == 1
    assert payload["entry_files"][0]["path"] == "app/main.py"
