"""Build and search a graph-enhanced RAG knowledge base from repository data.

====================================================================
图增强 RAG 知识图谱构建与搜索服务
====================================================================

将已同步的仓库快照（RepositorySnapshot）转换为结构化的知识图谱，包含：

  1. 节点（KnowledgeNode）类型：
     - repository         仓库根节点，包含元数据（owner、语言、topics）。
     - directory          目录节点，包含文件数量和各分类统计。
     - module             推断的代码模块（包含源码文件的目录）。
     - dependency_manifest 依赖清单节点（requirements.txt / package.json 等）。
     - test_suite / test_file  测试套件和测试文件节点。
     - documentation      文档节点（README）。

  2. 边（KnowledgeEdge）关系：
     - contains          仓库→目录
     - defines_module    目录→模块
     - uses_dependency_manifest  仓库→依赖清单
     - tests_with / tests_module 测试→仓库/模块
     - documents         仓库→文档

  3. 文本分块（KnowledgeChunk）策略：
     - overview_chunk         仓库总览（语言、目录数、模块数等）。
     - directory_chunks       目录结构分块。
     - module_chunks          模块映射分块。
     - dependency_chunks      依赖关系分块。
     - test_chunks            测试脚本 + README 测试提示。
     - source_content_chunks  源码内容分块（滑动窗口 + 重叠，默认 chunk_size=1024, overlap=128）。

  4. 搜索（search）：
     - 构建图谱 → 对所有 chunk 打分 → 按分数降序返回 top-N 结果。
     - 支持中文关键词别名翻译（目录→directory，模块→module 等）。
     - 分数计算：查询词命中 +1，路径命中 +1，focus 匹配 +2。

设计思路：
  - 轻量无依赖：不依赖 Neo4j / Milvus 等外部服务，纯内存计算。
  - 按需构建：每次 search() 都重新构建图谱，保证数据与最新的 snapshot 一致。
  - 多粒度分块：总览→目录→模块→依赖→测试→源码，保证不同层级的检索需求。
"""

from collections import Counter, defaultdict
from pathlib import PurePosixPath
import re

from app.core.config import settings

from app.schemas.knowledge import (
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSearchResult,
    RepositoryKnowledgeGraph,
)
from app.services.architecture_analysis import ArchitectureAnalysisService
from app.schemas.repository import ClassifiedFile, RepositorySnapshot


# 依赖清单文件名 → 生态系统的映射
DEPENDENCY_ECOSYSTEMS = {
    "requirements.txt": "Python/pip",
    "pyproject.toml": "Python",
    "poetry.lock": "Python/Poetry",
    "uv.lock": "Python/uv",
    "package.json": "Node.js",
    "package-lock.json": "Node.js/npm",
    "pnpm-lock.yaml": "Node.js/pnpm",
    "yarn.lock": "Node.js/Yarn",
    "go.mod": "Go",
    "cargo.toml": "Rust",
    "pom.xml": "Java/Maven",
    "build.gradle": "Java/Gradle",
}

# README 中可能出现的测试命令提示词
TEST_HINTS = {
    "pytest": "pytest",
    "vitest": "vitest",
    "jest": "jest",
    "npm test": "npm test",
    "pnpm test": "pnpm test",
    "yarn test": "yarn test",
    "go test": "go test",
    "cargo test": "cargo test",
}


class KnowledgeGraphService:
    """Create lightweight graph/RAG artifacts from synced repository snapshots.

    从同步好的仓库快照构建图/RAG 产物，支持结构化和语义搜索。
    """

    def build(self, snapshot: RepositorySnapshot) -> RepositoryKnowledgeGraph:
        """将仓库快照构建为完整的知识图谱。

        构建流程：
          1. 创建仓库根节点（含元数据摘要）。
          2. 按顶层目录分组，为每个目录创建 directory 节点，
             如果目录含源码文件，再创建对应的 module 节点。
          3. 识别依赖清单文件，创建 dependency_manifest 节点。
          4. 识别测试文件，创建 test_suite / test_file 节点。
          5. 识别 README，创建 documentation 节点。
          6. 生成 6 类文本分块：总览、目录、模块、依赖、测试、源码内容。

        Args:
            snapshot: 已同步的仓库快照。

        Returns:
            完整的 RepositoryKnowledgeGraph 对象（节点 + 边 + 分块）。
        """
        nodes: dict[str, KnowledgeNode] = {}
        edges: list[KnowledgeEdge] = []
        chunks: list[KnowledgeChunk] = []

        # 1. 仓库根节点
        repo_key = "repo"
        nodes[repo_key] = KnowledgeNode(
            key=repo_key,
            type="repository",
            name=snapshot.identity.full_name,
            summary=self._repository_summary(snapshot),
            metadata={
                "owner": snapshot.identity.owner,
                "name": snapshot.identity.name,
                "primary_language": snapshot.stats.primary_language,
                "languages": snapshot.stats.languages,
                "topics": snapshot.topics,
            },
        )

        # 2. 目录 + 模块节点
        directories = self._group_by_top_directory(snapshot.files)
        module_keys = self._add_directory_and_module_nodes(nodes, edges, repo_key, directories)

        # 3. 依赖节点
        dependency_keys = self._add_dependency_nodes(nodes, edges, repo_key, snapshot.files)

        # 4. 测试节点
        test_keys = self._add_test_nodes(nodes, edges, repo_key, module_keys, snapshot.files)

        # 5. README 节点
        readme_key = self._add_readme_node(nodes, edges, repo_key, snapshot)

        # 6. 生成各类文本分块
        chunks.extend(self._overview_chunks(snapshot, module_keys, dependency_keys, test_keys, readme_key))
        chunks.extend(self._directory_chunks(nodes, directories))
        chunks.extend(self._module_chunks(nodes, directories, module_keys))
        chunks.extend(self._dependency_chunks(nodes, dependency_keys))
        chunks.extend(self._test_chunks(snapshot, nodes, test_keys))
        chunks.extend(self._source_content_chunks(snapshot))
        self._add_semantic_architecture(snapshot, nodes, edges, chunks, repo_key)

        return RepositoryKnowledgeGraph(
            repository=snapshot.identity.full_name,
            nodes=list(nodes.values()),
            edges=edges,
            chunks=chunks,
        )

    def _add_semantic_architecture(
        self,
        snapshot: RepositorySnapshot,
        nodes: dict[str, KnowledgeNode],
        edges: list[KnowledgeEdge],
        chunks: list[KnowledgeChunk],
        repo_key: str,
    ) -> None:
        """Add AST/import evidence so RAG can answer source-level structure questions."""
        analysis = ArchitectureAnalysisService().analyze(snapshot)
        semantic_keys: dict[str, str] = {}
        for symbol in analysis.symbols[:600]:
            key = f"semantic:{symbol.key}"
            semantic_keys[symbol.key] = key
            nodes[key] = KnowledgeNode(
                key=key,
                type=f"code_{symbol.kind}",
                name=symbol.qualified_name,
                path=symbol.path,
                summary=(
                    f"{symbol.kind} {symbol.qualified_name} in {symbol.path or 'external dependency'}"
                    f" at lines {symbol.line_start or '?'}-{symbol.line_end or '?'}"
                ),
                metadata={
                    "language": symbol.language,
                    "line_start": symbol.line_start,
                    "line_end": symbol.line_end,
                },
            )
            if symbol.kind == "module":
                edges.append(KnowledgeEdge(source=repo_key, target=key, relation="contains_code_module"))

        for relation in analysis.relations[:1200]:
            source = semantic_keys.get(relation.source)
            target = semantic_keys.get(relation.target)
            if source and target:
                edges.append(KnowledgeEdge(
                    source=source,
                    target=target,
                    relation=f"code_{relation.relation}",
                    metadata={
                        "path": relation.evidence_path,
                        "line": relation.evidence_line,
                        "confidence": relation.confidence,
                    },
                ))

        by_path: dict[str, list] = defaultdict(list)
        for symbol in analysis.symbols:
            if symbol.path and symbol.kind != "module":
                by_path[symbol.path].append(symbol)
        for path, symbols in sorted(by_path.items())[:120]:
            content = "\n".join([
                f"Source file: {path}",
                *(
                    f"- {symbol.kind} {symbol.qualified_name} lines {symbol.line_start}-{symbol.line_end}"
                    for symbol in symbols[:30]
                ),
            ])
            chunks.append(KnowledgeChunk(
                key=f"chunk:semantic:{path}",
                title=f"Symbols in {path}",
                content=content,
                source_type="semantic_source",
                source_path=path,
                node_keys=[semantic_keys[symbol.key] for symbol in symbols[:30] if symbol.key in semantic_keys],
                metadata={"focus": "source_code", "revision": analysis.revision},
            ))

        if analysis.routes:
            chunks.append(KnowledgeChunk(
                key="chunk:semantic:routes",
                title="Detected API routes",
                content="\n".join(
                    f"- {route.method} {route.route} -> {route.handler_name} ({route.path}:{route.line})"
                    for route in analysis.routes
                ),
                source_type="api_routes",
                node_keys=[semantic_keys[route.handler_key] for route in analysis.routes if route.handler_key in semantic_keys],
                metadata={"focus": "modules", "revision": analysis.revision},
            ))

        chunks.append(KnowledgeChunk(
            key="chunk:semantic:health",
            title="Architecture health findings",
            content="\n".join([
                f"Architecture health score: {analysis.health.score}/100 ({analysis.health.grade})",
                f"File coverage: {analysis.coverage.file_coverage_percent}%",
                f"Parser coverage: {analysis.coverage.parser_coverage_percent}%",
                *(f"- [{issue.severity}] {issue.title}: {issue.description}" for issue in analysis.health.issues),
            ]),
            source_type="architecture_health",
            metadata={"focus": "structure", "revision": analysis.revision},
        ))

    def search(
        self,
        snapshot: RepositorySnapshot,
        query: str | None = None,
        focus: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeSearchResult]:
        """在图谱中搜索与查询词/焦点相关的分块。

        工作流程：
          1. 调用 build() 构建完整知识图谱（每次均重新构建以保持数据一致）。
          2. 对每个 chunk 调用 _score_chunk() 计算相关性分数。
          3. 关联 chunk 的节点和边信息，丰富返回结果。
          4. 按分数降序排序，返回 top-N（默认 5）。

        Args:
            snapshot: 已同步的仓库快照。
            query:    搜索查询文本。
            focus:    焦点过滤器，如 "modules"、"dependencies"、"tests" 等。
            limit:    最多返回的结果数量。

        Returns:
            按相关性分数降序排列的搜索结果列表。
        """
        graph = self.build(snapshot)
        query_terms = self._terms(f"{query or ''} {focus or ''}")
        focus_text = (focus or "").lower().strip()
        node_by_key = {node.key: node for node in graph.nodes}
        results: list[KnowledgeSearchResult] = []

        for chunk in graph.chunks:
            # 对每个 chunk 计算与查询的相关性分数
            score = self._score_chunk(chunk, query_terms, focus_text)
            if score <= 0 and query_terms:
                continue  # 无命中则跳过
            # 关联与该 chunk 相关的边（最多 8 条）
            related_edges = [
                edge for edge in graph.edges
                if edge.source in chunk.node_keys or edge.target in chunk.node_keys
            ][:8]
            results.append(
                KnowledgeSearchResult(
                    chunk=chunk,
                    score=score,
                    related_nodes=[node_by_key[key] for key in chunk.node_keys if key in node_by_key],
                    related_edges=related_edges,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        if not query_terms and not focus_text:
            return results[:limit]
        return results[:limit]

    # ── Node construction helpers ──────────────────────────────────────
    # 以下是各种节点的构建辅助方法

    def _add_directory_and_module_nodes(
        self,
        nodes: dict[str, KnowledgeNode],
        edges: list[KnowledgeEdge],
        repo_key: str,
        directories: dict[str, list[ClassifiedFile]],
    ) -> dict[str, str]:
        """为每个顶层目录创建 directory 节点，如果含源码则再创建 module 节点。

        Returns:
            {目录名: module_key} 映射，仅有源码文件的目录才有 module_key。
        """
        module_keys: dict[str, str] = {}
        for directory, files in sorted(directories.items()):
            categories = Counter(file.category.value for file in files)
            directory_key = f"dir:{directory}"
            nodes[directory_key] = KnowledgeNode(
                key=directory_key,
                type="directory",
                name=directory,
                path=None if directory == "(root)" else directory,
                summary=(
                    f"{directory} contains {len(files)} files; "
                    f"dominant category is {categories.most_common(1)[0][0]}."
                ),
                metadata={"categories": dict(categories), "file_count": len(files)},
            )
            edges.append(KnowledgeEdge(source=repo_key, target=directory_key, relation="contains"))

            # 如果目录中包含源代码文件，推断为模块并创建 module 节点
            source_files = [file for file in files if file.category.value == "source_code"]
            if source_files:
                module_key = f"module:{directory}"
                module_keys[directory] = module_key
                nodes[module_key] = KnowledgeNode(
                    key=module_key,
                    type="module",
                    name=directory,
                    path=None if directory == "(root)" else directory,
                    summary=(
                        f"{directory} is inferred as a code module with "
                        f"{len(source_files)} source files."
                    ),
                    metadata={
                        "source_count": len(source_files),
                        "representative_files": [file.path for file in source_files[:8]],
                    },
                )
                edges.append(KnowledgeEdge(source=directory_key, target=module_key, relation="defines_module"))
        return module_keys

    def _add_dependency_nodes(
        self,
        nodes: dict[str, KnowledgeNode],
        edges: list[KnowledgeEdge],
        repo_key: str,
        files: list[ClassifiedFile],
    ) -> list[str]:
        """为依赖清单文件创建节点，关联对应的生态系统。"""
        keys: list[str] = []
        dependency_files = [file for file in files if file.category.value == "dependency"]
        for file in dependency_files:
            file_name = PurePosixPath(file.path.lower()).name
            # 根据文件名识别生态系统（如 pyproject.toml → Python）
            ecosystem = DEPENDENCY_ECOSYSTEMS.get(file_name, "unknown")
            key = f"dependency:{file.path}"
            nodes[key] = KnowledgeNode(
                key=key,
                type="dependency_manifest",
                name=file.path,
                path=file.path,
                summary=f"{file.path} declares or locks dependencies for {ecosystem}.",
                metadata={"ecosystem": ecosystem, "size": file.size},
            )
            edges.append(KnowledgeEdge(source=repo_key, target=key, relation="uses_dependency_manifest"))
            keys.append(key)
        return keys

    def _add_test_nodes(
        self,
        nodes: dict[str, KnowledgeNode],
        edges: list[KnowledgeEdge],
        repo_key: str,
        module_keys: dict[str, str],
        files: list[ClassifiedFile],
    ) -> list[str]:
        """为测试文件创建 test_suite 和 test_file 节点。

        同时创建两条边：
          - tests_with:     连接仓库与测试套件。
          - tests_module:   连接测试套件与被测模块（如果模块存在）。
        """
        keys: list[str] = []
        test_files = [file for file in files if file.category.value == "tests"]
        by_directory = self._group_by_top_directory(test_files)
        for directory, grouped_files in sorted(by_directory.items()):
            key = f"test_suite:{directory}"
            nodes[key] = KnowledgeNode(
                key=key,
                type="test_suite",
                name=directory,
                path=None if directory == "(root)" else directory,
                summary=f"{directory} contains {len(grouped_files)} test files.",
                metadata={"test_files": [file.path for file in grouped_files[:12]]},
            )
            edges.append(KnowledgeEdge(source=repo_key, target=key, relation="tests_with"))
            # 如果该目录有对应的模块节点，建立测试→模块的关联
            if directory in module_keys:
                edges.append(KnowledgeEdge(source=key, target=module_keys[directory], relation="tests_module"))
            keys.append(key)

            # 为每个测试文件创建独立的 test_file 节点（最多 20 个）
            for file in grouped_files[:20]:
                file_key = f"test_file:{file.path}"
                nodes[file_key] = KnowledgeNode(
                    key=file_key,
                    type="test_file",
                    name=PurePosixPath(file.path).name,
                    path=file.path,
                    summary=f"{file.path} is classified as a test script.",
                    metadata={"size": file.size},
                )
                edges.append(KnowledgeEdge(source=key, target=file_key, relation="contains_test"))
                keys.append(file_key)
        return keys

    def _add_readme_node(
        self,
        nodes: dict[str, KnowledgeNode],
        edges: list[KnowledgeEdge],
        repo_key: str,
        snapshot: RepositorySnapshot,
    ) -> str | None:
        """创建 README 文档节点（如果 README 存在）。"""
        if not snapshot.readme:
            return None
        key = "doc:readme"
        nodes[key] = KnowledgeNode(
            key=key,
            type="documentation",
            name="README",
            path="README",
            summary="README content is available for usage, setup, and test hints.",
            metadata={"length": len(snapshot.readme)},
        )
        edges.append(KnowledgeEdge(source=repo_key, target=key, relation="documents"))
        return key

    # ── Chunk generators ───────────────────────────────────────────────
    # 以下是各类文本分块的生成方法

    def _overview_chunks(
        self,
        snapshot: RepositorySnapshot,
        module_keys: dict[str, str],
        dependency_keys: list[str],
        test_keys: list[str],
        readme_key: str | None,
    ) -> list[KnowledgeChunk]:
        """生成仓库总览分块（包含语言、目录数、模块数等高层信息）。"""
        node_keys = ["repo", *module_keys.values(), *dependency_keys, *test_keys]
        if readme_key:
            node_keys.append(readme_key)
        content = "\n".join(
            [
                self._repository_summary(snapshot),
                f"Directories: {len(self._group_by_top_directory(snapshot.files))}",
                f"Inferred modules: {', '.join(module_keys) or 'none'}",
                f"Dependency manifests: {len(dependency_keys)}",
                f"Test graph nodes: {len(test_keys)}",
            ]
        )
        return [
            KnowledgeChunk(
                key="chunk:overview",
                title="Repository structure overview",
                content=content,
                source_type="graph_summary",
                node_keys=node_keys,
                metadata={"focus": "overview"},
            )
        ]

    def _directory_chunks(
        self,
        nodes: dict[str, KnowledgeNode],
        directories: dict[str, list[ClassifiedFile]],
    ) -> list[KnowledgeChunk]:
        """生成目录结构分块。"""
        lines = []
        node_keys = []
        for directory, files in sorted(directories.items()):
            key = f"dir:{directory}"
            node_keys.append(key)
            categories = Counter(file.category.value for file in files)
            samples = ", ".join(file.path for file in files[:5])
            lines.append(f"- {directory}: {len(files)} files, categories={dict(categories)}, samples={samples}")
        return [
            KnowledgeChunk(
                key="chunk:directories",
                title="Directory structure",
                content="\n".join(lines) or "No directory information is available.",
                source_type="directory_graph",
                node_keys=[key for key in node_keys if key in nodes],
                metadata={"focus": "structure"},
            )
        ]

    def _module_chunks(
        self,
        nodes: dict[str, KnowledgeNode],
        directories: dict[str, list[ClassifiedFile]],
        module_keys: dict[str, str],
    ) -> list[KnowledgeChunk]:
        """生成模块映射分块。"""
        lines = []
        for directory, module_key in sorted(module_keys.items()):
            source_files = [file.path for file in directories[directory] if file.category.value == "source_code"]
            lines.append(f"- {directory}: {len(source_files)} source files; examples={', '.join(source_files[:8])}")
        return [
            KnowledgeChunk(
                key="chunk:modules",
                title="Module map",
                content="\n".join(lines) or "No source modules were inferred from the file tree.",
                source_type="module_graph",
                node_keys=[key for key in module_keys.values() if key in nodes],
                metadata={"focus": "modules"},
            )
        ]

    def _dependency_chunks(self, nodes: dict[str, KnowledgeNode], dependency_keys: list[str]) -> list[KnowledgeChunk]:
        """生成依赖关系分块。"""
        lines = []
        for key in dependency_keys:
            node = nodes[key]
            lines.append(f"- {node.path}: {node.summary}")
        return [
            KnowledgeChunk(
                key="chunk:dependencies",
                title="Dependency relationship map",
                content="\n".join(lines) or "No dependency manifest was found in the synced file tree.",
                source_type="dependency_graph",
                node_keys=dependency_keys,
                metadata={"focus": "dependencies"},
            )
        ]

    def _test_chunks(
        self,
        snapshot: RepositorySnapshot,
        nodes: dict[str, KnowledgeNode],
        test_keys: list[str],
    ) -> list[KnowledgeChunk]:
        """生成测试相关分块（测试文件列表 + README 中的测试提示）。"""
        test_lines = []
        for key in test_keys:
            node = nodes[key]
            if node.type in {"test_suite", "test_file"}:
                test_lines.append(f"- {node.path or node.name}: {node.summary}")
        # 从 README 中提取测试相关的命令行提示
        readme_hints = self._readme_test_hints(snapshot.readme or "")
        content = "\n".join(
            [
                *(test_lines or ["No test scripts were found in the synced file tree."]),
                "README test hints:",
                *(readme_hints or ["No README test hints found."]),
            ]
        )
        return [
            KnowledgeChunk(
                key="chunk:tests",
                title="Test scripts and test hints",
                content=content,
                source_type="test_graph",
                node_keys=test_keys,
                metadata={"focus": "tests"},
            )
        ]

    def _source_content_chunks(self, snapshot: RepositorySnapshot) -> list[KnowledgeChunk]:
        """生成源码内容分块（滑动窗口 + 重叠）。

        策略：
          - 对每个已索引的源码文件，使用滑动窗口分割为多个 chunk。
          - chunk_size 和 overlap 由配置读取（默认 1024 / 128）。
          - overlap 不超过 chunk_size 的一半，避免过度重叠。

        Args:
            snapshot: 仓库快照。

        Returns:
            源码内容分块列表。
        """
        chunks: list[KnowledgeChunk] = []
        chunk_size = max(500, settings.rag_chunk_size)
        overlap = min(max(0, settings.rag_chunk_overlap), chunk_size // 2)
        for file in snapshot.source_contents:
            start = 0
            index = 0
            text = file.content
            # 滑动窗口分割：每次前进 chunk_size - overlap
            while start < len(text):
                end = min(len(text), start + chunk_size)
                content = text[start:end].strip()
                if content:
                    chunks.append(
                        KnowledgeChunk(
                            key=f"chunk:source:{file.path}:{index}",
                            title=f"{file.path} source chunk {index + 1}",
                            content=content,
                            source_type=file.category.value,
                            source_path=file.path,
                            node_keys=[],
                            metadata={
                                "focus": "source_code" if file.category.value == "source_code" else file.category.value,
                                "path": file.path,
                                "chunk_index": index,
                                "truncated_file": file.truncated,
                            },
                        )
                    )
                if end >= len(text):
                    break
                # 下一窗口：end - overlap（保证相邻窗口间有重叠上下文）
                start = max(end - overlap, start + 1)
                index += 1
        return chunks

    # ── Utility methods ────────────────────────────────────────────────
    # 以下是工具方法

    def _repository_summary(self, snapshot: RepositorySnapshot) -> str:
        """生成仓库整体摘要文本。"""
        languages = ", ".join(snapshot.stats.languages) or snapshot.stats.primary_language or "unknown"
        return (
            f"{snapshot.identity.full_name} is a {languages} repository with "
            f"{len(snapshot.files)} indexed files, {len(snapshot.issues)} synced issues, "
            f"{len(snapshot.pull_requests)} pull requests, and {len(snapshot.recent_commits)} recent commits."
        )

    def _group_by_top_directory(self, files: list[ClassifiedFile]) -> dict[str, list[ClassifiedFile]]:
        """将文件按顶层目录分组。

        例如 ``src/main.py`` → ``"src"``，根目录文件 → ``"(root)"``。
        """
        grouped: dict[str, list[ClassifiedFile]] = defaultdict(list)
        for file in files:
            directory = file.path.split("/", 1)[0] if "/" in file.path else "(root)"
            grouped[directory].append(file)
        return dict(grouped)

    def _readme_test_hints(self, readme: str) -> list[str]:
        """从 README 中提取测试相关的命令提示。

        匹配规则：行中包含 "test" 或已知的测试命令（pytest, jest 等）。
        返回匹配行及前后 1-2 行的上下文。
        """
        if not readme:
            return []
        hints: list[str] = []
        lines = readme.splitlines()
        for index, line in enumerate(lines):
            lowered = line.lower()
            if "test" in lowered or any(command in lowered for command in TEST_HINTS):
                start = max(0, index - 1)
                end = min(len(lines), index + 3)
                hints.append(" ".join(part.strip() for part in lines[start:end] if part.strip()))
        return hints[:6]

    def _score_chunk(self, chunk: KnowledgeChunk, query_terms: set[str], focus: str) -> float:
        """根据查询词和焦点对 chunk 进行相关性评分。

        评分规则：
          - 无查询词且无 focus：统一返回 1.0。
          - 每个查询词命中：+1 分（路径类词匹配子串，普通词匹配完整单词/前缀）。
          - focus 命中（在内容、source_type 或 metadata.focus 中）：+2 分。

        Args:
            chunk:       要评分的分块。
            query_terms: 查询词集合。
            focus:       焦点字符串（如 "modules"、"tests"）。

        Returns:
            相关性分数（浮点数）。
        """
        haystack = f"{chunk.title} {chunk.content} {chunk.source_type} {chunk.metadata}".lower()
        haystack_terms = set(re.findall(r"[a-z0-9_]+", haystack))
        score = 0.0
        if not query_terms and not focus:
            score = 1.0
        for term in query_terms:
            is_path = "/" in term or "." in term
            matches_word = term in haystack_terms or (
                len(term) >= 4
                and any(candidate.startswith(term) for candidate in haystack_terms)
            )
            if (is_path and term in haystack) or (not is_path and matches_word):
                score += 1.0
        if focus and (focus in haystack or focus == chunk.metadata.get("focus")):
            score += 2.0
        return score

    def _terms(self, text: str) -> set[str]:
        """将文本转换为标准化的搜索词集合。

        包含中文关键词别名映射：
          目录 → directory structure / 模块 → module / 依赖 → dependency 等。

        Args:
            text: 输入文本（可能包含中文）。

        Returns:
            标准化的搜索词集合（≥2 字符）。
        """
        normalized = text.lower()
        aliases = {
            "目录": "directory structure",
            "结构": "structure",
            "模块": "module",
            "依赖": "dependency",
            "测试": "test",
            "脚本": "script",
            "源码": "source_code",
            "代码": "source_code",
        }
        for source, target in aliases.items():
            normalized = normalized.replace(source, f" {target} ")
        return {term for term in re.split(r"[^a-z0-9_./-]+", normalized) if len(term) >= 2}
