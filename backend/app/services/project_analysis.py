"""Rule-based repository structure analysis shared by UI and assistant tools."""

from collections import Counter, defaultdict

from app.schemas.project_analysis import ProjectAnalysis, ProjectDirectory
from app.schemas.repository import ClassifiedFile, RepositorySnapshot


ENTRY_FILE_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "manage.py",
    "index.js",
    "index.ts",
    "main.ts",
    "main.tsx",
    "app.tsx",
    "program.cs",
}


class ProjectAnalysisService:
    """Generate a lightweight structural analysis from synced repository data."""

    def analyze(self, snapshot: RepositorySnapshot) -> ProjectAnalysis:
        files = snapshot.files
        category_counts = {item.category: item.count for item in snapshot.file_categories}
        directory_counter: dict[str, Counter[str]] = defaultdict(Counter)

        for file in files:
            directory = file.path.split("/", 1)[0] if "/" in file.path else "(root)"
            directory_counter[directory][file.category.value] += 1

        top_directories = [
            ProjectDirectory(
                name=name,
                count=sum(counter.values()),
                main_category=counter.most_common(1)[0][0] if counter else "other",
            )
            for name, counter in directory_counter.items()
        ]
        top_directories.sort(key=lambda item: item.count, reverse=True)

        return ProjectAnalysis(
            project_type=self._infer_project_type(snapshot),
            source_count=category_counts.get("source_code", 0),
            dependency_files=self._by_category(files, "dependency"),
            test_files=self._by_category(files, "tests"),
            doc_files=self._by_category(files, "documentation"),
            config_files=self._by_category(files, "configuration"),
            entry_files=[file for file in files if self._is_entry_candidate(file.path)],
            ci_files=self._by_category(files, "ci_cd"),
            top_directories=top_directories[:8],
        )

    def _infer_project_type(self, snapshot: RepositorySnapshot) -> str:
        languages = {language.lower() for language in snapshot.stats.languages}
        has_python = "python" in languages
        has_frontend = bool(languages & {"typescript", "javascript", "tsx", "vue", "css", "html"})

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
        return path.lower().split("/")[-1] in ENTRY_FILE_NAMES
