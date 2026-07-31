"""Rule-based repository structure analysis shared by UI and assistant tools.

====================================================================
基于规则的仓库结构分析服务
====================================================================

从本地已同步的仓库快照中提取结构化的工程分析，包括：

  1. 工程类型推断：
     - 纯 Python 后端  / 纯 Web 前端 / 全栈项目（Python + 前端语言）。
     - 基于 GitHub 语言统计数据中各语言代码量占比。

  2. 依赖包解析与分组：
     - 支持 package.json（Node.js）、pyproject.toml / requirements.txt（Python）、
       Cargo.toml（Rust）。
     - 自动分组：runtime_framework（框架）→ data_interface（数据/通信库）
       → runtime（运行时依赖）→ development（开发依赖）。

  3. 框架检测：
     - 从解析出的依赖包中识别已知框架（FastAPI、Django、React、Vue、Express 等）。

  4. 入口文件识别：
     - 优先级排序的入口候选文件（main.py > index.js > app.tsx 等）。
     - 自动排除 test/docs/examples 目录中的文件。

  5. 目录分析：
     - 每个顶层目录的文件数量、主类别、源码文件数等统计。

使用方式：
    service = ProjectAnalysisService()
    analysis = service.analyze(snapshot)  # → ProjectAnalysis
"""

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


# 已知入口文件名称和优先级（数字越小优先级越高）
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
# 排除的入口文件目录：这些目录下的文件不作为入口候选
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
# Web 前端语言集合（用于判断是否为前端/全栈项目）
WEB_LANGUAGES = {"typescript", "javascript", "tsx", "vue", "css", "html"}
# 语言占比阈值：占比较高的语言才参与项目类型判定
SIGNIFICANT_LANGUAGE_SHARE = 0.1

# 已知框架名称映射（依赖包名 → 框架显示名）
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
# 数据/接口相关包（如 HTTP 客户端、ORM 等），分入 data_interface 组
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
# 开发工具包（lint、test、formatter 等），分入 development 组
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
# 依赖包名的正则：匹配 npm 范围包（@scope/name）和普通包名
DEPENDENCY_NAME_RE = re.compile(
    r"^(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*"
)
# 依赖分组的排序优先级（控制前端展示顺序）
DEPENDENCY_GROUP_PRIORITY = {
    "runtime_framework": 0,  # 框架（FastAPI、React 等）排在最前
    "data_interface": 1,     # 数据/通信库（httpx、sqlalchemy 等）
    "runtime": 2,            # 运行时依赖
    "development": 3,        # 开发依赖（测试、lint、工具）
}


class ProjectAnalysisService:
    """Generate a structural analysis from all locally available repository data.

    从仓库快照中生成结构化的项目分析报告。
    """

    def analyze(self, snapshot: RepositorySnapshot) -> ProjectAnalysis:
        """核心入口：分析快照并返回 ProjectAnalysis。

        分析流程：
          1. 合并采样文件列表 + 全量源码内容（去重）。
          2. 统计各类别的文件数量。
          3. 按顶层目录分组，生成目录分析。
          4. 解析依赖包（package.json / pyproject.toml 等）。
          5. 检测框架。
          6. 识别入口文件。
          7. 推断工程类型。

        Args:
            snapshot: 已同步的仓库快照。

        Returns:
            ProjectAnalysis 对象（直接序列化为前端所需数据结构）。
        """
        # 合并采样文件和全量扫描文件（去重）
        files = self._analysis_files(snapshot)
        category_counts = Counter(file.category.value for file in files)
        directory_counter: dict[str, Counter[str]] = defaultdict(Counter)

        for file in files:
            directory = file.path.split("/", 1)[0] if "/" in file.path else "(root)"
            directory_counter[directory][file.category.value] += 1

        # 构建顶层目录分析（按文件总数降序排列）
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

        # 解析依赖
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
            # 入口文件：源文件中按优先级排序
            entry_files=sorted(
                (
                    file
                    for file in files
                    if file.category.value == "source_code" and self._is_entry_candidate(file.path)
                ),
                key=self._entry_sort_key,
            ),
            ci_files=self._by_category(files, "ci_cd"),
            top_directories=top_directories[:8],  # 最多 8 个顶层目录
        )

    # ── File merging ───────────────────────────────────────────────────

    def _analysis_files(self, snapshot: RepositorySnapshot) -> list[ClassifiedFile]:
        """Combine the sampled tree with complete indexed files without duplicates.

        将采样文件列表（用于分类统计）与全量源码内容列表合并，
        以路径为 key 去重，保证不丢失全量扫描中的文件信息。

        Args:
            snapshot: 仓库快照。

        Returns:
            去重后的 ClassifiedFile 列表（按路径排序）。
        """
        by_path = {file.path: file for file in snapshot.files}
        for content in snapshot.source_contents:
            by_path[content.path] = ClassifiedFile(
                path=content.path,
                category=content.category,
                size=content.size,
            )
        return sorted(by_path.values(), key=lambda file: file.path)

    # ── Dependency extraction ────────────────────────────────────────

    def _extract_dependency_packages(self, snapshot: RepositorySnapshot) -> list[ProjectDependency]:
        """从所有已索引的依赖清单文件中解析依赖包。

        支持解析：
          - package.json  → Node.js 依赖
          - pyproject.toml → Python (PEP 621 + Poetry + dependency-groups)
          - requirements.txt / requirements-*.txt → Python (pip)
          - Cargo.toml → Rust

        分组策略：
          1. 声明时的组别（dependencies vs devDependencies 等）。
          2. 知名包名覆盖（DEVELOPMENT_PACKAGES / DATA_AND_INTERFACE_PACKAGES / FRAMEWORK_NAMES）。

        Args:
            snapshot: 仓库快照。

        Returns:
            去重后的 ProjectDependency 列表（最多 120 个，按组优先级+名称排序）。
        """
        dependencies: dict[tuple[str, str, str], ProjectDependency] = {}

        for content in snapshot.source_contents:
            file_name = PurePosixPath(content.path).name.lower()
            try:
                # 根据文件名选择对应的解析器
                parsed = self._parse_manifest(file_name, content.content)
            except (json.JSONDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError):
                continue  # 解析异常时跳过该文件

            for raw_name, ecosystem, declared_group in parsed:
                name = self._dependency_name(raw_name)
                if not name:
                    continue
                # 以 (name, ecosystem, source_file) 为 key 去重
                key = (name.lower(), ecosystem, content.path)
                dependencies.setdefault(
                    key,
                    ProjectDependency(
                        name=name,
                        ecosystem=ecosystem,
                        group=self._dependency_group(name, declared_group),
                        source_file=content.path,
                        version=self._dependency_version(raw_name, name),
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
        """根据文件名分派到对应的解析方法。

        Returns:
            list of (raw_dependency_name, ecosystem, declared_group)
        """
        if file_name == "package.json":
            return self._parse_package_json(content)
        if file_name == "pyproject.toml":
            return self._parse_pyproject(content)
        if file_name.startswith("requirements") and file_name.endswith((".txt", ".in")):
            # requirements-dev.txt / requirements-test.txt → development
            group = "development" if any(hint in file_name for hint in ("dev", "test")) else "runtime"
            return [(line, "Python", group) for line in content.splitlines()]
        if file_name == "cargo.toml":
            return self._parse_cargo_toml(content)
        return []

    def _parse_package_json(self, content: str) -> list[tuple[str, str, str]]:
        """解析 Node.js package.json 的依赖字段。

        处理字段：dependencies、peerDependencies、optionalDependencies（runtime）、
                 devDependencies（development）。
        """
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
                result.extend(
                    (f"{name}@{version}", "Node.js", group)
                    for name, version in values.items()
                )
        return result

    def _parse_pyproject(self, content: str) -> list[tuple[str, str, str]]:
        """解析 Python pyproject.toml 的依赖字段。

        支持三种规范：
          1. PEP 621: [project] dependencies + optional-dependencies
          2. PEP 735: [dependency-groups]（默认视为 development）
          3. Poetry: [tool.poetry.dependencies] + [tool.poetry.group.*.dependencies]
        """
        payload = tomllib.loads(content)
        result: list[tuple[str, str, str]] = []

        # PEP 621
        project = payload.get("project")
        if isinstance(project, dict):
            dependencies = project.get("dependencies")
            if isinstance(dependencies, list):
                result.extend((str(item), "Python", "runtime") for item in dependencies)
            optional = project.get("optional-dependencies")
            if isinstance(optional, dict):
                for group_name, values in optional.items():
                    if isinstance(values, list):
                        # optional-dependencies 中带 dev/test 的视为开发依赖
                        group = "development" if any(hint in group_name.lower() for hint in ("dev", "test")) else "runtime"
                        result.extend((str(item), "Python", group) for item in values)

        # PEP 735 dependency-groups（如 uv / pdm 等工具）
        dependency_groups = payload.get("dependency-groups")
        if isinstance(dependency_groups, dict):
            for values in dependency_groups.values():
                if isinstance(values, list):
                    result.extend((str(item), "Python", "development") for item in values if isinstance(item, str))

        # Poetry
        tool = payload.get("tool")
        poetry = tool.get("poetry") if isinstance(tool, dict) else None
        if isinstance(poetry, dict):
            dependencies = poetry.get("dependencies")
            if isinstance(dependencies, dict):
                result.extend(
                    (f"{name}{version if isinstance(version, str) else ''}", "Python", "runtime")
                    for name, version in dependencies.items()
                    if str(name).lower() != "python"  # Poetry 的 python 约束行不算依赖
                )
            groups = poetry.get("group")
            if isinstance(groups, dict):
                for group_payload in groups.values():
                    values = group_payload.get("dependencies") if isinstance(group_payload, dict) else None
                    if isinstance(values, dict):
                        result.extend(
                            (f"{name}{version if isinstance(version, str) else ''}", "Python", "development")
                            for name, version in values.items()
                        )
        return result

    def _parse_cargo_toml(self, content: str) -> list[tuple[str, str, str]]:
        """解析 Rust Cargo.toml 的依赖字段。

        处理字段：dependencies（runtime）、dev-dependencies（development）。
        """
        payload = tomllib.loads(content)
        result: list[tuple[str, str, str]] = []
        for field, group in (("dependencies", "runtime"), ("dev-dependencies", "development")):
            values = payload.get(field)
            if isinstance(values, dict):
                result.extend(
                    (f"{name}@{version if isinstance(version, str) else version.get('version', '') if isinstance(version, dict) else ''}", "Rust", group)
                    for name, version in values.items()
                )
        return result

    def _dependency_name(self, value: Any) -> str | None:
        """从原始依赖声明行中提取标准化的包名。

        过滤掉：
          - 注释行（# 开头）
          - 约束/引用行（-r、-- 开头）
          - URL 依赖（http://、https://、git+ 开头）

        Args:
            value: 依赖声明的原始文本。

        Returns:
            提取到的包名，或 None（表示不是有效的依赖声明）。
        """
        text = str(value).strip()
        if not text or text.startswith(("#", "-r", "--", "http://", "https://", "git+")):
            return None
        match = DEPENDENCY_NAME_RE.match(text)
        return match.group(0) if match else None

    def _dependency_version(self, value: Any, name: str) -> str | None:
        """Return the declared version range that follows a normalized package name."""
        text = str(value).strip()
        if not text.startswith(name):
            return None
        version = text[len(name):].strip()
        if version.startswith("@"):
            version = version[1:].strip()
        return version or None

    def _dependency_group(self, name: str, declared_group: str) -> str:
        """根据包名和声明时的组别确定最终的依赖分组。

        优先级：知名包名覆盖 > 声明时的组别 > runtime（默认）。

        Args:
            name:           包名。
            declared_group: 声明时的组别（"runtime" / "development"）。

        Returns:
            最终分组名（"runtime_framework" / "data_interface" / "runtime" / "development"）。
        """
        normalized = name.lower()
        if declared_group == "development" or normalized in DEVELOPMENT_PACKAGES:
            return "development"
        if normalized in DATA_AND_INTERFACE_PACKAGES:
            return "data_interface"
        if normalized in FRAMEWORK_NAMES:
            return "runtime_framework"
        return "runtime"

    # ── Framework detection ───────────────────────────────────────────

    def _detected_frameworks(self, dependencies: list[ProjectDependency]) -> list[str]:
        """从依赖包列表中检测已知框架。

        遍历所有依赖包，如果包名在 FRAMEWORK_NAMES 中，
        则添加对应的框架显示名（已排序去重）。

        Args:
            dependencies: 已解析的依赖包列表。

        Returns:
            框架名称列表（如 ``["FastAPI", "React", "Vite"]``）。
        """
        frameworks = {
            FRAMEWORK_NAMES[item.name.lower()]
            for item in dependencies
            if item.name.lower() in FRAMEWORK_NAMES
        }
        return sorted(frameworks)

    # ── Analysis helpers ─────────────────────────────────────────────

    def _analysis_warning(
        self,
        snapshot: RepositorySnapshot,
        source_count: int,
        dependency_files: list[ClassifiedFile],
        dependency_packages: list[ProjectDependency],
    ) -> str | None:
        """生成分析警告（当数据不完整时提示用户）。

        警告场景：
          - GitHub 报告了编程语言，但没有任何源码文件被索引 → 可能 token 不足。
          - 找到了依赖清单，但一个依赖都没解析出来 → 可能解析器有遗漏。
        """
        if source_count == 0 and snapshot.stats.primary_language:
            return (
                f"GitHub reports {snapshot.stats.primary_language} as the primary language, "
                "but no source files were available to the analyzer."
            )
        if dependency_files and not dependency_packages:
            return "Dependency manifests were found, but no package entries could be parsed."
        return None

    def _infer_project_type(self, snapshot: RepositorySnapshot) -> str:
        """根据语言统计数据推断工程类型。

        判定逻辑：
          - 语言字节占比 ≥ 10% 视为显著参与。
          - Python 显著 + 前端语言显著 → 全栈项目。
          - 仅 Python 显著 → Python 后端/工具项目。
          - 仅前端语言显著 → Web 前端/Node.js 项目。
          - 无显著指标 → 以占比最高的语言命名。

        Args:
            snapshot: 仓库快照。

        Returns:
            工程类型描述字符串。
        """
        languages = snapshot.stats.languages
        total_bytes = sum(max(byte_count, 0) for byte_count in languages.values())
        primary_language = (snapshot.stats.primary_language or "").lower()

        def language_share(names: set[str]) -> float:
            """计算指定语言集合在代码库中的字节占比。"""
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
        """按类别过滤文件列表。

        Args:
            files:    文件列表。
            category: 类别值（如 ``"source_code"``、``"tests"``）。

        Returns:
            匹配指定类别的文件列表。
        """
        return [file for file in files if file.category.value == category]

    def _is_entry_candidate(self, path: str) -> bool:
        """判断一个源文件路径是否为入口候选文件。

        条件：
          - 文件名在 ENTRY_FILE_NAMES 中。
          - 不在 EXCLUDED_ENTRY_DIRECTORIES 目录中（排除 test/docs/examples 等）。

        Args:
            path: 文件仓库内路径。

        Returns:
            True 表示该文件可能是入口文件。
        """
        segments = path.lower().split("/")
        # 检查路径中（除最后一个文件名外）是否包含排除目录
        if any(segment in EXCLUDED_ENTRY_DIRECTORIES for segment in segments[:-1]):
            return False
        return segments[-1] in ENTRY_FILE_NAMES

    def _entry_sort_key(self, file: ClassifiedFile) -> tuple[int, int, int, str]:
        """入口文件的排序键。

        排序优先级：文件优先级（main.py=0 > index.js=1 > app.py=2）
                  > 是否在常规父目录（app/、src/ 优先）
                  > 路径深度（浅的优先）
                  > 路径字母序。

        Args:
            file: 已分类的文件。

        Returns:
            四元组排序键。
        """
        segments = file.path.lower().split("/")
        file_name = segments[-1]
        # 位于 app/ 或 src/ 下的文件更可能是真正的入口
        conventional_parent = (
            0 if any(segment in {"app", "src"} for segment in segments[:-1]) else 1
        )
        return (
            ENTRY_FILE_PRIORITY.get(file_name, 99),
            conventional_parent,
            len(segments),  # 路径深度越浅越可能是入口
            file.path.lower(),
        )
