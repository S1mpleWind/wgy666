"""Build and search a graph-enhanced RAG knowledge base from repository data."""

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
from app.schemas.repository import ClassifiedFile, RepositorySnapshot


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
    """Create lightweight graph/RAG artifacts from synced repository snapshots."""

    def build(self, snapshot: RepositorySnapshot) -> RepositoryKnowledgeGraph:
        nodes: dict[str, KnowledgeNode] = {}
        edges: list[KnowledgeEdge] = []
        chunks: list[KnowledgeChunk] = []

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

        directories = self._group_by_top_directory(snapshot.files)
        module_keys = self._add_directory_and_module_nodes(nodes, edges, repo_key, directories)
        dependency_keys = self._add_dependency_nodes(nodes, edges, repo_key, snapshot.files)
        test_keys = self._add_test_nodes(nodes, edges, repo_key, module_keys, snapshot.files)
        readme_key = self._add_readme_node(nodes, edges, repo_key, snapshot)

        chunks.extend(self._overview_chunks(snapshot, module_keys, dependency_keys, test_keys, readme_key))
        chunks.extend(self._directory_chunks(nodes, directories))
        chunks.extend(self._module_chunks(nodes, directories, module_keys))
        chunks.extend(self._dependency_chunks(nodes, dependency_keys))
        chunks.extend(self._test_chunks(snapshot, nodes, test_keys))
        chunks.extend(self._source_content_chunks(snapshot))

        return RepositoryKnowledgeGraph(
            repository=snapshot.identity.full_name,
            nodes=list(nodes.values()),
            edges=edges,
            chunks=chunks,
        )

    def search(
        self,
        snapshot: RepositorySnapshot,
        query: str | None = None,
        focus: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeSearchResult]:
        graph = self.build(snapshot)
        query_terms = self._terms(f"{query or ''} {focus or ''}")
        focus_text = (focus or "").lower().strip()
        node_by_key = {node.key: node for node in graph.nodes}
        results: list[KnowledgeSearchResult] = []

        for chunk in graph.chunks:
            score = self._score_chunk(chunk, query_terms, focus_text)
            if score <= 0 and query_terms:
                continue
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

    def _add_directory_and_module_nodes(
        self,
        nodes: dict[str, KnowledgeNode],
        edges: list[KnowledgeEdge],
        repo_key: str,
        directories: dict[str, list[ClassifiedFile]],
    ) -> dict[str, str]:
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
        keys: list[str] = []
        dependency_files = [file for file in files if file.category.value == "dependency"]
        for file in dependency_files:
            file_name = PurePosixPath(file.path.lower()).name
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
            if directory in module_keys:
                edges.append(KnowledgeEdge(source=key, target=module_keys[directory], relation="tests_module"))
            keys.append(key)

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

    def _overview_chunks(
        self,
        snapshot: RepositorySnapshot,
        module_keys: dict[str, str],
        dependency_keys: list[str],
        test_keys: list[str],
        readme_key: str | None,
    ) -> list[KnowledgeChunk]:
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
        test_lines = []
        for key in test_keys:
            node = nodes[key]
            if node.type in {"test_suite", "test_file"}:
                test_lines.append(f"- {node.path or node.name}: {node.summary}")
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
        chunks: list[KnowledgeChunk] = []
        chunk_size = max(500, settings.rag_chunk_size)
        overlap = min(max(0, settings.rag_chunk_overlap), chunk_size // 2)
        for file in snapshot.source_contents:
            start = 0
            index = 0
            text = file.content
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
                start = max(end - overlap, start + 1)
                index += 1
        return chunks

    def _repository_summary(self, snapshot: RepositorySnapshot) -> str:
        languages = ", ".join(snapshot.stats.languages) or snapshot.stats.primary_language or "unknown"
        return (
            f"{snapshot.identity.full_name} is a {languages} repository with "
            f"{len(snapshot.files)} indexed files, {len(snapshot.issues)} synced issues, "
            f"{len(snapshot.pull_requests)} pull requests, and {len(snapshot.recent_commits)} recent commits."
        )

    def _group_by_top_directory(self, files: list[ClassifiedFile]) -> dict[str, list[ClassifiedFile]]:
        grouped: dict[str, list[ClassifiedFile]] = defaultdict(list)
        for file in files:
            directory = file.path.split("/", 1)[0] if "/" in file.path else "(root)"
            grouped[directory].append(file)
        return dict(grouped)

    def _readme_test_hints(self, readme: str) -> list[str]:
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
