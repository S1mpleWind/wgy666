"""Rule-based file classifier.

Categorizes repository files into types (SOURCE, TEST, DOCS, CONFIG, etc.)
based on file path patterns and extensions.

====================================================================
基于规则的仓库文件分类器
====================================================================

根据文件路径模式和后缀名，将仓库文件分为以下类别：

  - SOURCE       源码文件（.py, .js, .ts, .go, .java 等）
  - TEST         测试文件（位于 test*/tests/ 目录中，或以 test_ 开头）
  - DOCUMENTATION 文档（.md, .rst, README 等）
  - DEPENDENCY   依赖清单（requirements.txt, package.json, Cargo.toml 等）
  - CONFIGURATION 配置文件（.env.example, docker-compose.yml, .gitignore 等）
  - CI_CD        CI/CD 工作流（.github/workflows/, Jenkinsfile 等）
  - BUILD        构建文件（Makefile, build/ 目录）
  - ASSET        静态资源（.png, .jpg, .svg 等图片和媒体文件）
  - DATA         数据文件（.json, .csv, .yaml 等）
  - OTHER        无法归类的其他文件

分类规则优先级：从最具体到最通用依次匹配，命中即返回。
  CI/CD → TEST → DOCS → DEPENDENCY → CONFIG → BUILD → ASSET → SOURCE → DATA → OTHER

关键设计：
  - classify_many() 用于批量分类 git tree 中的 blob 文件，并生成各类别统计摘要。
  - 所有规则均为纯字符串/路径匹配，无外部依赖，保证离线环境可用。
"""

from collections import Counter
from pathlib import PurePosixPath

from app.schemas.repository import CategorySummary, ClassifiedFile, FileCategory


# -- Rule sets (extend these to cover more ecosystem patterns) -------------
# 以下集合定义了每种文件类别的匹配规则，扩展时只需新增对应的扩展名或文件名即可。

# 文档类扩展名：Markdown、reStructuredText 等
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
# 源码类扩展名：覆盖主流编程语言
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
# 静态资源扩展名：图片、视频等二进制文件
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".mp4", ".mov"}
# 数据文件扩展名
DATA_EXTENSIONS = {".json", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".sql"}
# 依赖清单文件名：各语言的包管理器锁文件/声明文件
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
# 配置文件/环境约定文件名
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
    """Classify a file path into a ``FileCategory`` using rule matching.

    纯规则匹配的文件分类器，不依赖任何外部服务或模型。
    """

    def classify(self, path: str) -> FileCategory:
        """Determine the category of a single file by its path.

        Rules are ordered from most specific to most general:
        CI/CD → TEST → DOCS → DEPENDENCY → CONFIG → BUILD → ASSET → SOURCE → DATA → OTHER.

        匹配逻辑：
          1. 路径标准化：将反斜杠转为正斜杠，统一为小写。
          2. 提取路径段集合、文件名、扩展名。
          3. 按优先级依次检查：CI/CD > 测试 > 文档 > 依赖 > 配置 > 构建 > 资源 > 源码 > 数据 > 其他。
          4. 命中任意一条规则即返回对应类别。

        Args:
            path: 文件在仓库中的相对路径（如 ``src/main.py``）。

        Returns:
            匹配到的文件类别枚举值。
        """
        normalized = path.replace("\\", "/").lower()
        parts = set(normalized.split("/"))
        file_name = PurePosixPath(normalized).name
        suffix = PurePosixPath(normalized).suffix

        # CI/CD: .github 目录、workflows 目录、Jenkinsfile 等
        if ".github" in parts or "workflows" in parts or file_name in {"jenkinsfile", ".travis.yml"}:
            return FileCategory.CI_CD
        # 测试: test/tests 目录、以 test_ 开头的文件、以 .test.ts 结尾的文件
        if "test" in parts or "tests" in parts or file_name.startswith("test_") or file_name.endswith(".test.ts"):
            return FileCategory.TEST
        # 文档: docs 目录、README、文档后缀名
        if "docs" in parts or file_name.startswith("readme") or suffix in DOC_EXTENSIONS:
            return FileCategory.DOCUMENTATION
        # 依赖: 匹配依赖清单文件名
        if file_name in DEPENDENCY_FILES:
            return FileCategory.DEPENDENCY
        # 配置: 配置文件名、隐藏文件（.开头）、文件名含 "config"
        if file_name in CONFIG_FILES or file_name.startswith(".") or "config" in file_name:
            return FileCategory.CONFIGURATION
        # 构建: Makefile、CMakeLists.txt、build/dist 目录
        if file_name in {"makefile", "cmakelists.txt"} or "build" in parts or "dist" in parts:
            return FileCategory.BUILD
        # 资源: 资源扩展名、assets/public 目录
        if suffix in ASSET_EXTENSIONS or "assets" in parts or "public" in parts:
            return FileCategory.ASSET
        # 源码: 源码扩展名
        if suffix in SOURCE_EXTENSIONS:
            return FileCategory.SOURCE
        # 数据: 数据扩展名
        if suffix in DATA_EXTENSIONS:
            return FileCategory.DATA
        # 其他: 不匹配任何规则
        return FileCategory.OTHER

    def classify_many(self, tree_items: list[dict], limit: int) -> tuple[list[ClassifiedFile], list[CategorySummary]]:
        """Classify all blob items in a git tree, up to ``limit`` items.

        批量分类方法，用于处理 git clone 后的文件列表。

        参数说明：
          - ``tree_items`` 每项需包含 ``type``、``path``、``size`` 字段（与 Git Tree API 返回格式一致）。
          - ``limit``  仅处理前 N 条以控制性能开销。
          - 只会处理 ``type == "blob"`` 的条目，跳过 tree 目录节点。

        Returns:
            (classified_files, category_summaries)：
              - classified_files: 分类后的文件列表（包含路径、类别、大小）。
              - category_summaries: 各类别的文件数量统计，按降序排列。

        Args:
            tree_items: Git tree 条目列表。
            limit: 最大处理条目数。

        Returns:
            (ClassifiedFile 列表, CategorySummary 列表) 元组。
        """
        files: list[ClassifiedFile] = []
        counter: Counter[str] = Counter()

        for item in tree_items[:limit]:
            # 跳过非文件条目（如子目录 tree 节点）
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
            # 累加各个类别的计数
            counter[category.value] += 1

        # 按出现频率从高到低生成摘要
        summaries = [
            CategorySummary(category=category, count=count)
            for category, count in counter.most_common()
        ]
        return files, summaries
