"""Rule-based file classifier.

Categorizes repository files into types (SOURCE, TEST, DOCS, CONFIG, etc.)
based on file path patterns and extensions.
"""

from collections import Counter
from pathlib import PurePosixPath

from app.schemas.repository import CategorySummary, ClassifiedFile, FileCategory


# -- Rule sets (extend these to cover more ecosystem patterns) -------------

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".cs",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".scala",
    ".vue",
    ".svelte",
}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".mp4", ".mov"}
DATA_EXTENSIONS = {".json", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".sql"}
DEPENDENCY_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "pom.xml",
    "build.gradle",
}
CONFIG_FILES = {
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "dockerfile",
    "compose.yml",
    "docker-compose.yml",
    "tsconfig.json",
    "vite.config.ts",
    "eslint.config.js",
    "ruff.toml",
}


class FileClassifier:
    """Classify a file path into a ``FileCategory`` using rule matching."""

    def classify(self, path: str) -> FileCategory:
        """Determine the category of a single file by its path.

        Rules are ordered from most specific to most general:
        CI/CD → TEST → DOCS → DEPENDENCY → CONFIG → BUILD → ASSET → SOURCE → DATA → OTHER.
        """
        normalized = path.replace("\\", "/").lower()
        parts = set(normalized.split("/"))
        file_name = PurePosixPath(normalized).name
        suffix = PurePosixPath(normalized).suffix

        if ".github" in parts or "workflows" in parts or file_name in {"jenkinsfile", ".travis.yml"}:
            return FileCategory.CI_CD
        if "test" in parts or "tests" in parts or file_name.startswith("test_") or file_name.endswith(".test.ts"):
            return FileCategory.TEST
        if "docs" in parts or file_name.startswith("readme") or suffix in DOC_EXTENSIONS:
            return FileCategory.DOCUMENTATION
        if file_name in DEPENDENCY_FILES:
            return FileCategory.DEPENDENCY
        if file_name in CONFIG_FILES or file_name.startswith(".") or "config" in file_name:
            return FileCategory.CONFIGURATION
        if file_name in {"makefile", "cmakelists.txt"} or "build" in parts or "dist" in parts:
            return FileCategory.BUILD
        if suffix in ASSET_EXTENSIONS or "assets" in parts or "public" in parts:
            return FileCategory.ASSET
        if suffix in SOURCE_EXTENSIONS:
            return FileCategory.SOURCE
        if suffix in DATA_EXTENSIONS:
            return FileCategory.DATA
        return FileCategory.OTHER

    def classify_many(self, tree_items: list[dict], limit: int) -> tuple[list[ClassifiedFile], list[CategorySummary]]:
        """Classify all blob items in a git tree, up to ``limit`` items."""
        files: list[ClassifiedFile] = []
        counter: Counter[str] = Counter()

        for item in tree_items[:limit]:
            if item.get("type") != "blob":
                continue
            path = item.get("path")
            if not path:
                continue
            category = self.classify(path)
            files.append(
                ClassifiedFile(
                    path=path,
                    category=category,
                    size=item.get("size"),
                )
            )
            counter[category.value] += 1

        summaries = [
            CategorySummary(category=category, count=count)
            for category, count in counter.most_common()
        ]
        return files, summaries
