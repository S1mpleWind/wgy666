"""Tests for deterministic semantic architecture and impact analysis."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.api.routes import repository_tools
from app.schemas.architecture import ImpactAnalysisRequest
from app.schemas.repository import (
    FileCategory,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
)
from app.services.architecture_analysis import ArchitectureAnalysisService
from app.services import repository_query
from app.storage.memory import InMemoryRepositoryStore


def _snapshot(revision: str, files: dict[str, tuple[FileCategory, str]]) -> RepositorySnapshot:
    return RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="architecture-tests",
            name="sample",
            full_name="architecture-tests/sample",
            html_url="https://github.com/architecture-tests/sample",
            default_branch="main",
        ),
        stats=RepositoryStats(primary_language="Python", languages={"Python": 1000}),
        source_contents=[
            RepositoryFileContent(path=path, category=category, content=content, size=len(content))
            for path, (category, content) in files.items()
        ],
        source_revision=revision,
        synced_at=datetime.now(timezone.utc),
    )


def test_python_symbols_routes_imports_and_tests_are_connected() -> None:
    snapshot = _snapshot("a" * 40, {
        "app/main.py": (
            FileCategory.SOURCE,
            "from fastapi import FastAPI\nfrom app.service import load_user\n"
            "app = FastAPI()\n@app.get('/users/{user_id}')\ndef read_user(user_id):\n"
            "    return load_user(user_id)\n",
        ),
        "app/service.py": (
            FileCategory.SOURCE,
            "class UserService:\n    def get(self, user_id):\n        return user_id\n\n"
            "def load_user(user_id):\n    return UserService().get(user_id)\n",
        ),
        "tests/test_service.py": (
            FileCategory.TEST,
            "from app.service import load_user\n\ndef test_load_user():\n    assert load_user(1) == 1\n",
        ),
    })

    result = ArchitectureAnalysisService().analyze(snapshot)

    assert any(symbol.kind == "class" and symbol.name == "UserService" for symbol in result.symbols)
    assert any(symbol.kind == "method" and symbol.name == "get" for symbol in result.symbols)
    assert any(route.method == "GET" and route.route == "/users/{user_id}" for route in result.routes)
    assert any(
        relation.relation == "imports"
        and relation.source == "module:app/main.py"
        and relation.target == "module:app/service.py"
        for relation in result.relations
    )
    mapping = next(item for item in result.test_mappings if item.test_path == "tests/test_service.py")
    assert mapping.source_paths == ["app/service.py"]
    assert result.coverage.parser_coverage_percent == 100.0


def test_test_mapping_excludes_support_files() -> None:
    snapshot = _snapshot("4" * 40, {
        "app/service.py": (FileCategory.SOURCE, "def load():\n    return []\n"),
        "tests/test_service.py": (
            FileCategory.TEST,
            "from app.service import load\ndef test_load():\n    assert load() == []\n",
        ),
        "tests/conftest.py": (FileCategory.TEST, "from app.service import load\n"),
        "tests/__init__.py": (FileCategory.TEST, ""),
    })

    result = ArchitectureAnalysisService().analyze(snapshot)

    assert [mapping.test_path for mapping in result.test_mappings] == ["tests/test_service.py"]


def test_health_detects_cycles_and_missing_test_links() -> None:
    snapshot = _snapshot("b" * 40, {
        "app/a.py": (FileCategory.SOURCE, "from app.b import value_b\nvalue_a = 1\n"),
        "app/b.py": (FileCategory.SOURCE, "from app.a import value_a\nvalue_b = 2\n"),
    })

    result = ArchitectureAnalysisService().analyze(snapshot)
    codes = {issue.code for issue in result.health.issues}

    assert "circular_import" in codes
    assert "missing_test_link" in codes
    assert result.health.score < 100


def test_impact_traces_importers_routes_and_recommended_tests() -> None:
    snapshot = _snapshot("c" * 40, {
        "app/main.py": (
            FileCategory.SOURCE,
            "from app.service import load\nfrom fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/items')\ndef items():\n    return load()\n",
        ),
        "app/service.py": (FileCategory.SOURCE, "def load():\n    return []\n"),
        "tests/test_service.py": (FileCategory.TEST, "from app.service import load\ndef test_load():\n    assert load() == []\n"),
    })
    service = ArchitectureAnalysisService()
    analysis = service.analyze(snapshot)

    impact = service.impact(analysis, ImpactAnalysisRequest(paths=["app/service.py"], max_depth=2))

    assert "app/service.py" in impact.affected_files
    assert "app/main.py" in impact.affected_files
    assert any(item.test_path == "tests/test_service.py" for item in impact.recommended_tests)
    assert any(route.route == "/items" for route in impact.affected_routes)
    assert impact.risk_score > 0
    assert impact.risk_level in {"low", "medium"}
    assert len(impact.nodes) == len(impact.affected_files)


def test_impact_does_not_expand_through_sibling_symbols() -> None:
    snapshot = _snapshot("2" * 40, {
        "app/router.py": (
            FileCategory.SOURCE,
            "from app.health import status\nfrom app.users import list_users\n"
            "def routes():\n    return status(), list_users()\n",
        ),
        "app/health.py": (FileCategory.SOURCE, "def status():\n    return 'ok'\n"),
        "app/users.py": (FileCategory.SOURCE, "def list_users():\n    return []\n"),
        "tests/test_health.py": (
            FileCategory.TEST,
            "from app.health import status\ndef test_status():\n    assert status() == 'ok'\n",
        ),
    })
    service = ArchitectureAnalysisService()
    analysis = service.analyze(snapshot)

    impact = service.impact(
        analysis,
        ImpactAnalysisRequest(paths=["app/health.py"], max_depth=2),
    )

    assert "app/health.py" in impact.affected_files
    assert "app/router.py" in impact.affected_files
    assert "tests/test_health.py" in impact.affected_files
    assert "app/users.py" not in impact.affected_files
    assert impact.risk_score < 70


def test_duplicate_module_aliases_resolve_within_same_source_root() -> None:
    snapshot = _snapshot("3" * 40, {
        "backend/app/storage/database.py": (FileCategory.SOURCE, "TABLES = []\n"),
        "backend/app/storage/postgres.py": (
            FileCategory.SOURCE,
            "from app.storage.database import TABLES\ndef save():\n    return TABLES\n",
        ),
        "TechPrototype/code/backend/app/storage/database.py": (
            FileCategory.SOURCE,
            "TABLES = []\n",
        ),
        "TechPrototype/code/backend/app/storage/postgres.py": (
            FileCategory.SOURCE,
            "from app.storage.database import TABLES\ndef save():\n    return TABLES\n",
        ),
    })
    service = ArchitectureAnalysisService()
    analysis = service.analyze(snapshot)

    assert any(
        relation.relation == "imports"
        and relation.source == "module:TechPrototype/code/backend/app/storage/postgres.py"
        and relation.target == "module:TechPrototype/code/backend/app/storage/database.py"
        for relation in analysis.relations
    )
    impact = service.impact(
        analysis,
        ImpactAnalysisRequest(
            paths=["TechPrototype/code/backend/app/storage/database.py"],
            max_depth=2,
        ),
    )

    assert "TechPrototype/code/backend/app/storage/postgres.py" in impact.affected_files
    assert "backend/app/storage/postgres.py" not in impact.affected_files


def test_impact_resolves_chinese_issue_domain_terms_and_handles_no_match() -> None:
    snapshot = _snapshot("1" * 40, {
        "app/auth_routes.py": (
            FileCategory.SOURCE,
            "from fastapi import FastAPI\napp = FastAPI()\n@app.post('/login')\ndef login():\n    return 'token'\n",
        ),
        "app/catalog.py": (FileCategory.SOURCE, "def list_items():\n    return []\n"),
    })
    service = ArchitectureAnalysisService()
    analysis = service.analyze(snapshot)

    auth_impact = service.impact(
        analysis,
        ImpactAnalysisRequest(issue_text="登录认证路由的 token 校验需要修改"),
    )
    unknown_impact = service.impact(
        analysis,
        ImpactAnalysisRequest(issue_text="一个完全无法定位到源码的模糊描述"),
    )

    assert auth_impact.seed_paths == ["app/auth_routes.py"]
    assert auth_impact.risk_score > 0
    assert unknown_impact.seed_paths == []
    assert unknown_impact.risk_score == 0
    assert "未从当前" in unknown_impact.reasons[0]


def test_diff_reports_changed_symbols_routes_and_dependencies() -> None:
    service = ArchitectureAnalysisService()
    base = service.analyze(_snapshot("d" * 40, {
        "app/main.py": (FileCategory.SOURCE, "def run():\n    return 1\n"),
    }))
    target = service.analyze(_snapshot("e" * 40, {
        "app/main.py": (
            FileCategory.SOURCE,
            "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\n"
            "def run():\n    return 2\n",
        ),
    }))

    result = service.diff(base, target)

    assert any(symbol.name == "run" for symbol in result.changed_symbols)
    assert any(route.route == "/health" for route in result.added_routes)
    assert result.base_revision == "d" * 40
    assert result.target_revision == "e" * 40


def test_architecture_endpoints_return_history_and_impact(monkeypatch) -> None:
    snapshot = _snapshot("f" * 40, {
        "app/main.py": (FileCategory.SOURCE, "def main():\n    return 1\n"),
    })
    store = InMemoryRepositoryStore()
    monkeypatch.setattr(repository_tools, "repository_store", store)
    monkeypatch.setattr(repository_query, "repository_store", store)
    store.save(snapshot)
    client = TestClient(create_app())

    analysis_response = client.get("/api/repositories/architecture-tests/sample/tools/architecture")
    history_response = client.get("/api/repositories/architecture-tests/sample/tools/architecture/history")
    impact_response = client.post(
        "/api/repositories/architecture-tests/sample/tools/architecture/impact",
        json={"paths": ["app/main.py"], "max_depth": 2},
    )

    assert analysis_response.status_code == 200
    assert history_response.status_code == 200
    assert history_response.json()[0]["revision"] == "f" * 40
    assert impact_response.status_code == 200
    assert "app/main.py" in impact_response.json()["affected_files"]


def test_same_revision_refreshes_when_indexed_source_count_changes() -> None:
    store = InMemoryRepositoryStore()
    revision = "9" * 40
    first = _snapshot(revision, {
        "app/main.py": (FileCategory.SOURCE, "def main():\n    return 1\n"),
    })
    expanded = _snapshot(revision, {
        "app/main.py": (FileCategory.SOURCE, "def main():\n    return 1\n"),
        "app/service.py": (FileCategory.SOURCE, "def load():\n    return []\n"),
    })

    store.save(first)
    store.save(expanded)
    refreshed = store.get_architecture_analysis("architecture-tests", "sample")

    assert refreshed is not None
    assert refreshed.coverage.indexed_files == 2
    assert any(symbol.path == "app/service.py" for symbol in refreshed.symbols)
    assert len(store.list_architecture_analyses("architecture-tests", "sample")) == 1
