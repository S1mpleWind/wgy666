"""Rule-based repository structure analysis shared by UI and assistant tools."""

from collections import Counter, defaultdict
import json
from pathlib import PurePosixPath
import re
import tomllib
from typing import Any

from app.schemas.project_analysis import (
    ProjectAnalysis,
    ProjectDependency,
    ProjectDirectory,
)
from app.schemas.repository import ClassifiedFile, RepositorySnapshot


ENTRY_FILE_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "manage.py",
    "index.js",
    "index.ts",
    "index.tsx",
    "main.ts",
    "main.tsx",
    "app.tsx",
    "program.cs",
}
ENTRY_FILE_PRIORITY = {
    "main.py": 0,
    "main.ts": 0,
    "main.tsx": 0,
    "program.cs": 0,
    "index.js": 1,
    "index.ts": 1,
    "index.tsx": 1,
    "manage.py": 1,
    "server.py": 1,
    "app.py": 2,
    "app.tsx": 3,
}
EXCLUDED_ENTRY_DIRECTORIES = {
    ".github",
    "doc",
    "docs",
    "example",
    "examples",
    "fixture",
    "fixtures",
    "sample",
    "samples",
    "test",
    "tests",
}
WEB_LANGUAGES = {"typescript", "javascript", "tsx", "vue", "css", "html"}
SIGNIFICANT_LANGUAGE_SHARE = 0.1

FRAMEWORK_NAMES = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "uvicorn": "Uvicorn",
    "react": "React",
    "react-dom": "React",
    "next": "Next.js",
    "vue": "Vue",
    "express": "Express",
    "vite": "Vite",
}
DATA_AND_INTERFACE_PACKAGES = {
    "axios",
    "httpx",
    "openai",
    "pgvector",
    "psycopg",
    "psycopg2",
    "pydantic",
    "pydantic-settings",
    "requests",
    "sqlalchemy",
}
DEVELOPMENT_PACKAGES = {
    "eslint",
    "jest",
    "mypy",
    "oxlint",
    "prettier",
    "pytest",
    "pytest-asyncio",
    "ruff",
    "typescript",
    "vitest",
}
DEPENDENCY_NAME_RE = re.compile(
    r"^(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*"
)
DEPENDENCY_GROUP_PRIORITY = {
    "runtime_framework": 0,
    "data_interface": 1,
    "runtime": 2,
    "development": 3,
}


class ProjectAnalysisService:
    """Generate a structural analysis from all locally available repository data."""

    def analyze(self, snapshot: RepositorySnapshot) -> ProjectAnalysis:
        files = self._analysis_files(snapshot)
        category_counts = Counter(file.category.value for file in files)
        directory_counter: dict[str, Counter[str]] = defaultdict(Counter)

        for file in files:
            directory = file.path.split("/", 1)[0] if "/" in file.path else "(root)"
            directory_counter[directory][file.category.value] += 1

        top_directories = [
            ProjectDirectory(
                name=name,
                count=sum(counter.values()),
                main_category=counter.most_common(1)[0][0] if counter else "other",
                source_count=counter.get("source_code", 0),
            )
            for name, counter in directory_counter.items()
        ]
        top_directories.sort(key=lambda item: (-item.count, item.name))

        dependency_files = self._by_category(files, "dependency")
        dependency_packages = self._extract_dependency_packages(snapshot)
        source_count = category_counts.get("source_code", 0)

        return ProjectAnalysis(
            project_type=self._infer_project_type(snapshot),
            analyzed_file_count=len(files),
            analysis_warning=self._analysis_warning(snapshot, source_count, dependency_files, dependency_packages),
            source_count=source_count,
            dependency_files=dependency_files,
            dependency_packages=dependency_packages,
            detected_frameworks=self._detected_frameworks(dependency_packages),
            test_files=self._by_category(files, "tests"),
            doc_files=self._by_category(files, "documentation"),
            config_files=self._by_category(files, "configuration"),
            entry_files=sorted(
                (
                    file
                    for file in files
                    if file.category.value == "source_code" and self._is_entry_candidate(file.path)
                ),
                key=self._entry_sort_key,
            ),
            ci_files=self._by_category(files, "ci_cd"),
            top_directories=top_directories[:8],
        )

    def _analysis_files(self, snapshot: RepositorySnapshot) -> list[ClassifiedFile]:
        """Combine the sampled tree with complete indexed files without duplicates."""
        by_path = {file.path: file for file in snapshot.files}
        for content in snapshot.source_contents:
            by_path[content.path] = ClassifiedFile(
                path=content.path,
                category=content.category,
                size=content.size,
            )
        return sorted(by_path.values(), key=lambda file: file.path)

    def _extract_dependency_packages(self, snapshot: RepositorySnapshot) -> list[ProjectDependency]:
        dependencies: dict[tuple[str, str, str], ProjectDependency] = {}

        for content in snapshot.source_contents:
            file_name = PurePosixPath(content.path).name.lower()
            try:
                parsed = self._parse_manifest(file_name, content.content)
            except (json.JSONDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError):
                continue

            for raw_name, ecosystem, declared_group in parsed:
                name = self._dependency_name(raw_name)
                if not name:
                    continue
                key = (name.lower(), ecosystem, content.path)
                dependencies.setdefault(
                    key,
                    ProjectDependency(
                        name=name,
                        ecosystem=ecosystem,
                        group=self._dependency_group(name, declared_group),
                        source_file=content.path,
                    ),
                )

        return sorted(
            dependencies.values(),
            key=lambda item: (
                DEPENDENCY_GROUP_PRIORITY.get(item.group, 99),
                item.name.lower(),
                item.ecosystem,
                item.source_file,
            ),
        )[:120]

    def _parse_manifest(self, file_name: str, content: str) -> list[tuple[str, str, str]]:
        if file_name == "package.json":
            return self._parse_package_json(content)
        if file_name == "pyproject.toml":
            return self._parse_pyproject(content)
        if file_name.startswith("requirements") and file_name.endswith((".txt", ".in")):
            group = "development" if any(hint in file_name for hint in ("dev", "test")) else "runtime"
            return [(line, "Python", group) for line in content.splitlines()]
        if file_name == "cargo.toml":
            return self._parse_cargo_toml(content)
        return []

    def _parse_package_json(self, content: str) -> list[tuple[str, str, str]]:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return []
        result: list[tuple[str, str, str]] = []
        groups = {
            "dependencies": "runtime",
            "peerDependencies": "runtime",
            "optionalDependencies": "runtime",
            "devDependencies": "development",
        }
        for field, group in groups.items():
            values = payload.get(field)
            if isinstance(values, dict):
                result.extend((str(name), "Node.js", group) for name in values)
        return result

    def _parse_pyproject(self, content: str) -> list[tuple[str, str, str]]:
        payload = tomllib.loads(content)
        result: list[tuple[str, str, str]] = []

        project = payload.get("project")
        if isinstance(project, dict):
            dependencies = project.get("dependencies")
            if isinstance(dependencies, list):
                result.extend((str(item), "Python", "runtime") for item in dependencies)
            optional = project.get("optional-dependencies")
            if isinstance(optional, dict):
                for group_name, values in optional.items():
                    if isinstance(values, list):
                        group = "development" if any(hint in group_name.lower() for hint in ("dev", "test")) else "runtime"
                        result.extend((str(item), "Python", group) for item in values)

        dependency_groups = payload.get("dependency-groups")
        if isinstance(dependency_groups, dict):
            for values in dependency_groups.values():
                if isinstance(values, list):
                    result.extend((str(item), "Python", "development") for item in values if isinstance(item, str))

        tool = payload.get("tool")
        poetry = tool.get("poetry") if isinstance(tool, dict) else None
        if isinstance(poetry, dict):
            dependencies = poetry.get("dependencies")
            if isinstance(dependencies, dict):
                result.extend(
                    (str(name), "Python", "runtime")
                    for name in dependencies
                    if str(name).lower() != "python"
                )
            groups = poetry.get("group")
            if isinstance(groups, dict):
                for group_payload in groups.values():
                    values = group_payload.get("dependencies") if isinstance(group_payload, dict) else None
                    if isinstance(values, dict):
                        result.extend((str(name), "Python", "development") for name in values)
        return result

    def _parse_cargo_toml(self, content: str) -> list[tuple[str, str, str]]:
        payload = tomllib.loads(content)
        result: list[tuple[str, str, str]] = []
        for field, group in (("dependencies", "runtime"), ("dev-dependencies", "development")):
            values = payload.get(field)
            if isinstance(values, dict):
                result.extend((str(name), "Rust", group) for name in values)
        return result

    def _dependency_name(self, value: Any) -> str | None:
        text = str(value).strip()
        if not text or text.startswith(("#", "-r", "--", "http://", "https://", "git+")):
            return None
        match = DEPENDENCY_NAME_RE.match(text)
        return match.group(0) if match else None

    def _dependency_group(self, name: str, declared_group: str) -> str:
        normalized = name.lower()
        if declared_group == "development" or normalized in DEVELOPMENT_PACKAGES:
            return "development"
        if normalized in DATA_AND_INTERFACE_PACKAGES:
            return "data_interface"
        if normalized in FRAMEWORK_NAMES:
            return "runtime_framework"
        return "runtime"

    def _detected_frameworks(self, dependencies: list[ProjectDependency]) -> list[str]:
        frameworks = {
            FRAMEWORK_NAMES[item.name.lower()]
            for item in dependencies
            if item.name.lower() in FRAMEWORK_NAMES
        }
        return sorted(frameworks)

    def _analysis_warning(
        self,
        snapshot: RepositorySnapshot,
        source_count: int,
        dependency_files: list[ClassifiedFile],
        dependency_packages: list[ProjectDependency],
    ) -> str | None:
        if source_count == 0 and snapshot.stats.primary_language:
            return (
                f"GitHub reports {snapshot.stats.primary_language} as the primary language, "
                "but no source files were available to the analyzer."
            )
        if dependency_files and not dependency_packages:
            return "Dependency manifests were found, but no package entries could be parsed."
        return None

    def _infer_project_type(self, snapshot: RepositorySnapshot) -> str:
        languages = snapshot.stats.languages
        total_bytes = sum(max(byte_count, 0) for byte_count in languages.values())
        primary_language = (snapshot.stats.primary_language or "").lower()

        def language_share(names: set[str]) -> float:
            if total_bytes == 0:
                return 0
            matching_bytes = sum(
                max(byte_count, 0)
                for language, byte_count in languages.items()
                if language.lower() in names
            )
            return matching_bytes / total_bytes

        has_python = primary_language == "python" or language_share({"python"}) >= SIGNIFICANT_LANGUAGE_SHARE
        has_frontend = language_share(WEB_LANGUAGES) >= SIGNIFICANT_LANGUAGE_SHARE

        if has_python and has_frontend:
            return "Full-stack project: Python backend plus web frontend"
        if has_python:
            return "Python backend or tooling project"
        if has_frontend:
            return "Web frontend or Node.js project"
        if snapshot.stats.languages:
            return f"{next(iter(snapshot.stats.languages))}-first project"
        return "Unknown primary stack"

    def _by_category(self, files: list[ClassifiedFile], category: str) -> list[ClassifiedFile]:
        return [file for file in files if file.category.value == category]

    def _is_entry_candidate(self, path: str) -> bool:
        segments = path.lower().split("/")
        if any(segment in EXCLUDED_ENTRY_DIRECTORIES for segment in segments[:-1]):
            return False
        return segments[-1] in ENTRY_FILE_NAMES

    def _entry_sort_key(self, file: ClassifiedFile) -> tuple[int, int, int, str]:
        segments = file.path.lower().split("/")
        file_name = segments[-1]
        conventional_parent = (
            0 if any(segment in {"app", "src"} for segment in segments[:-1]) else 1
        )
        return (
            ENTRY_FILE_PRIORITY.get(file_name, 99),
            conventional_parent,
            len(segments),
            file.path.lower(),
        )
