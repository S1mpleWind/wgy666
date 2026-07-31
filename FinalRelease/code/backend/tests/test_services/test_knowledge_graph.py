"""Tests for graph-enhanced repository knowledge construction."""

from datetime import datetime, timezone

from app.schemas.repository import (
    CategorySummary,
    ClassifiedFile,
    FileCategory,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.services.knowledge_graph import KnowledgeGraphService


def test_knowledge_graph_builds_structure_dependency_and_test_chunks():
    snapshot = _make_snapshot()
    service = KnowledgeGraphService()

    graph = service.build(snapshot)

    node_types = {node.type for node in graph.nodes}
    chunk_titles = {chunk.title for chunk in graph.chunks}

    assert "directory" in node_types
    assert "module" in node_types
    assert "dependency_manifest" in node_types
    assert "test_suite" in node_types
    assert "Test scripts and test hints" in chunk_titles
    assert any(edge.relation == "uses_dependency_manifest" for edge in graph.edges)


def test_knowledge_graph_search_supports_chinese_focus_terms():
    results = KnowledgeGraphService().search(_make_snapshot(), query="测试脚本在哪里")

    assert results
    assert results[0].chunk.title == "Test scripts and test hints"
    assert "backend/tests/test_main.py" in results[0].chunk.content


def _make_snapshot() -> RepositorySnapshot:
    files = [
        ClassifiedFile(path="backend/app/main.py", category=FileCategory.SOURCE, size=100),
        ClassifiedFile(path="backend/app/service.py", category=FileCategory.SOURCE, size=100),
        ClassifiedFile(path="backend/tests/test_main.py", category=FileCategory.TEST, size=50),
        ClassifiedFile(path="frontend/src/App.tsx", category=FileCategory.SOURCE, size=80),
        ClassifiedFile(path="pyproject.toml", category=FileCategory.DEPENDENCY, size=20),
        ClassifiedFile(path="package.json", category=FileCategory.DEPENDENCY, size=20),
        ClassifiedFile(path=".github/workflows/test.yml", category=FileCategory.CI_CD, size=20),
        ClassifiedFile(path="README.md", category=FileCategory.DOCUMENTATION, size=30),
    ]
    return RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="graph",
            name="repo",
            full_name="graph/repo",
            html_url="https://github.com/graph/repo",
            default_branch="main",
        ),
        description="Graph RAG test repository.",
        stats=RepositoryStats(
            primary_language="Python",
            languages={"Python": 1000, "TypeScript": 500},
        ),
        readme="# Demo\n\n## Test\n\nRun pytest for backend tests.",
        files=files,
        file_categories=[
            CategorySummary(category="source_code", count=3),
            CategorySummary(category="tests", count=1),
            CategorySummary(category="dependency", count=2),
        ],
        synced_at=datetime.now(timezone.utc),
    )
