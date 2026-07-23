"""Tool implementations available to the repository assistant harness."""

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from app.schemas.assistant import AssistantCitation, AssistantToolCall
from app.schemas.repository import RepositorySnapshot
from app.services.knowledge_graph import KnowledgeGraphService
from app.services.project_analysis import ProjectAnalysisService
from app.services.repository_query import RepositoryQueryService
from app.core.config import settings
from app.storage import repository_store


@dataclass
class ToolResult:
    """Structured result from a tool invocation."""

    call: AssistantToolCall
    content: str
    citations: list[AssistantCitation] = field(default_factory=list)


class RepositoryAssistantTools:
    """Read-only tools backed by synced repository state."""

    def __init__(self) -> None:
        self.query = RepositoryQueryService()
        self.project_analysis = ProjectAnalysisService()
        self.knowledge_graph = KnowledgeGraphService()

    def read_file(self, snapshot: RepositorySnapshot, path: str, start_line: int | None = None,
                  end_line: int | None = None) -> ToolResult:
        result = self._file(snapshot, path)
        if result is None:
            return self._simple("read_file", {"path": path}, f"File not found in indexed source: {path}")
        content = result["content"]
        lines = content.splitlines()
        start = max(1, start_line or 1)
        end = min(len(lines), end_line or len(lines))
        if start > end:
            body = "Invalid line range."
        else:
            body = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
        suffix = "\n[content was truncated during repository sync]" if result.get("truncated") else ""
        return self._simple("read_file", {"path": path, "start_line": start_line, "end_line": end}, body + suffix, path)

    def read_source_context(self, snapshot: RepositorySnapshot, path: str, line: int,
                            before: int = 5, after: int = 5) -> ToolResult:
        return self.read_file(snapshot, path, max(1, line - before), line + after)

    def grep_code(self, snapshot: RepositorySnapshot, pattern: str, path: str | None = None,
                  regex: bool = False, file_type: str | None = None) -> ToolResult:
        files = snapshot.source_contents
        if path:
            files = [file for file in files if path.lower() in file.path.lower()]
        if file_type:
            files = [file for file in files if file.path.rsplit(".", 1)[-1].lower() == file_type.lower().lstrip(".")]
        try:
            matcher = re.compile(pattern, re.IGNORECASE) if regex else None
        except re.error as exc:
            return self._simple("grep_code", {"pattern": pattern}, f"Invalid regular expression: {exc}")
        matches: list[str] = []
        for file in files:
            for number, text in enumerate(file.content.splitlines(), 1):
                if (matcher.search(text) if matcher else pattern.lower() in text.lower()):
                    matches.append(f"{file.path}:{number}: {text}")
        body = "\n".join(matches[:100]) if matches else "No matches."
        if len(matches) > 100:
            body += f"\n[showing 100 of {len(matches)} matches]"
        return self._simple("grep_code", {"pattern": pattern, "path": path, "regex": regex, "file_type": file_type}, body)

    def find_symbol(self, snapshot: RepositorySnapshot, symbol: str, references: bool = False,
                    path: str | None = None) -> ToolResult:
        files = [file for file in snapshot.source_contents if not path or path.lower() in file.path.lower()]
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        rows: list[str] = []
        for file in files:
            for number, text in enumerate(file.content.splitlines(), 1):
                is_definition = bool(re.search(rf"\b(def|class|function|const|let|var)\s+{re.escape(symbol)}\b", text))
                if (is_definition if not references else bool(pattern.search(text))):
                    rows.append(f"{file.path}:{number}: {text}")
        name = "find_symbol_references" if references else "find_symbol_definition"
        return self._simple(name, {"symbol": symbol, "path": path}, "\n".join(rows[:100]) or "No matches.")

    def vector_search(self, snapshot: RepositorySnapshot, query: str, limit: int = 5,
                      filters: dict[str, Any] | None = None) -> ToolResult:
        rows = []
        if hasattr(repository_store, "search_knowledge"):
            try:
                rows = repository_store.search_knowledge(snapshot.identity.owner, snapshot.identity.name, query, limit=max(1, min(limit, 20)))
            except Exception:
                rows = []
        if filters:
            rows = [row for row in rows if all(not value or row.get(key) == value for key, value in filters.items())]
        body = "\n\n".join(f"## {row.get('title')}\nScore: {float(row.get('score') or 0):.3f}\n{row.get('content')}" for row in rows)
        return self._simple("vector_search", {"query": query, "limit": limit, "filters": filters}, body or "No vector results.")

    def resolve_source_path(self, snapshot: RepositorySnapshot, source_path: str) -> ToolResult:
        result = self._file(snapshot, source_path)
        if result is None:
            return self._simple("resolve_source_path", {"source_path": source_path}, "No indexed file resolved.")
        return self._simple("resolve_source_path", {"source_path": source_path}, f"Resolved path: {result['path']}\nCategory: {result['category']}\nSize: {result.get('size')}", result["path"])

    def working_tree_diff(self, snapshot: RepositorySnapshot) -> ToolResult:
        return self._run_command("working_tree_diff", ["git", "diff", "--no-ext-diff", "--"], {})

    def run_tests(self, snapshot: RepositorySnapshot, path: str | None = None, test_name: str | None = None) -> ToolResult:
        command = [sys.executable, "-m", "pytest"]
        if path:
            command.append(path)
        if test_name:
            command.extend(["-k", test_name])
        return self._run_command("run_tests", command, {"path": path, "test_name": test_name})

    def embedding_status(self, snapshot: RepositorySnapshot) -> ToolResult:
        from app.services.embeddings import EmbeddingService

        mode, error = EmbeddingService.backend_status()
        body = f"Embedding backend actually used: {mode}\nConfigured dimensions: {settings.embedding_dimensions}"
        if error:
            body += f"\nLast fallback reason: {error[:300]}"
        return self._simple("embedding_status", {}, body)

    def _file(self, snapshot: RepositorySnapshot, path: str) -> dict[str, Any] | None:
        normalized = path.replace("\\", "/").lstrip("./")
        item = next((item for item in snapshot.source_contents if item.path == normalized), None)
        return item.model_dump(mode="json") if item else None

    def _simple(self, name: str, args: dict[str, Any], content: str, path: str | None = None) -> ToolResult:
        citations = [AssistantCitation(type="file", label=path, path=path)] if path else []
        return ToolResult(call=AssistantToolCall(name=name, args=args, summary=f"Execute {name}."), content=content, citations=citations)

    def _run_command(self, name: str, command: list[str], args: dict[str, Any]) -> ToolResult:
        root = Path(__file__).resolve().parents[3]
        try:
            completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120, check=False)
            output = (completed.stdout + completed.stderr).strip() or "Command completed without output."
            content = f"Exit code: {completed.returncode}\n{output[-12000:]}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            content = f"Command failed: {exc}"
        return self._simple(name, args, content)

    def overview(self, snapshot: RepositorySnapshot) -> ToolResult:
        stats = snapshot.stats
        lines = [
            f"Repository: {snapshot.identity.full_name}",
            f"Description: {snapshot.description or 'No description'}",
            f"Default branch: {snapshot.identity.default_branch}",
            f"Primary language: {stats.primary_language or 'unknown'}",
            f"Stars/Forks/Open issues: {stats.stars}/{stats.forks}/{stats.open_issues}",
            f"Indexed files: {len(snapshot.files)}",
            f"Synced at: {snapshot.synced_at.isoformat()}",
        ]
        return ToolResult(
            call=AssistantToolCall(name="repo_overview", args={}, summary="Read repository metadata and aggregate counts."),
            content="\n".join(lines),
            citations=[
                AssistantCitation(type="repository", label=snapshot.identity.full_name, url=snapshot.identity.html_url)
            ],
        )

    def project_structure(self, snapshot: RepositorySnapshot) -> ToolResult:
        analysis = self.project_analysis.analyze(snapshot)
        directory_lines = [
            f"- {item.name}: {item.count} files, mostly {item.main_category}"
            for item in analysis.top_directories[:6]
        ]
        content = "\n".join(
            [
                f"Project type: {analysis.project_type}",
                f"Source files: {analysis.source_count}",
                f"Dependency files: {len(analysis.dependency_files)}",
                f"Test files: {len(analysis.test_files)}",
                f"Documentation files: {len(analysis.doc_files)}",
                "Top directories:",
                *(directory_lines or ["- No directory information available"]),
            ]
        )
        citations = [
            AssistantCitation(type="file", label=file.path, path=file.path)
            for file in analysis.entry_files[:5]
        ]
        return ToolResult(
            call=AssistantToolCall(
                name="project_structure",
                args={},
                summary="Analyze synced file tree for stack, directories, entries, tests, docs, and dependencies.",
            ),
            content=content,
            citations=citations,
        )

    def search_files(self, snapshot: RepositorySnapshot, query: str | None = None, category: str | None = None) -> ToolResult:
        files = self.query.search_files(snapshot, query=query, category=category)
        label = category or query or "all files"
        if not files:
            content = f"No files matched {label}."
        else:
            content = "\n".join(f"- {file.path} ({file.category.value})" for file in files)
        return ToolResult(
            call=AssistantToolCall(
                name="search_files",
                args={"query": query, "category": category},
                summary=f"Search repository files for {label}.",
            ),
            content=content,
            citations=[
                AssistantCitation(type="file", label=file.path, path=file.path)
                for file in files[:8]
            ],
        )

    def list_issues(self, snapshot: RepositorySnapshot, category: str | None = None, state: str | None = None) -> ToolResult:
        issues = self.query.list_issues(snapshot, category=category, state=state)
        label = category or state or "recent issues"
        if not issues:
            content = f"No issues matched {label}."
        else:
            content = "\n".join(
                f"- #{issue.number} [{issue.classification.category.value}] {issue.title}"
                for issue in issues
            )
        return ToolResult(
            call=AssistantToolCall(
                name="list_issues",
                args={"category": category, "state": state},
                summary=f"List repository issues filtered by {label}.",
            ),
            content=content,
            citations=[
                AssistantCitation(type="issue", label=f"#{issue.number}", url=issue.html_url)
                for issue in issues[:8]
            ],
        )

    def readme_lookup(self, snapshot: RepositorySnapshot, query: str | None = None) -> ToolResult:
        excerpt = self.query.readme_excerpt(snapshot, query=query)
        content = excerpt or "No README content is available in the synced data."
        args: dict[str, Any] = {"query": query}
        return ToolResult(
            call=AssistantToolCall(name="readme_lookup", args=args, summary="Inspect README content for relevant guidance."),
            content=content,
            citations=[
                AssistantCitation(
                    type="readme",
                    label="README",
                    url=f"{snapshot.identity.html_url}#readme",
                )
            ],
        )

    def recent_activity(self, snapshot: RepositorySnapshot) -> ToolResult:
        commit_lines = [
            f"- commit {commit.sha}: {commit.message}"
            for commit in snapshot.recent_commits[:5]
        ]
        pr_lines = [
            f"- PR #{pull.number} [{pull.state}] {pull.title}"
            for pull in snapshot.pull_requests[:5]
        ]
        content = "\n".join(
            [
                "Recent commits:",
                *(commit_lines or ["- No commits synced"]),
                "Recent pull requests:",
                *(pr_lines or ["- No pull requests synced"]),
            ]
        )
        citations = [
            AssistantCitation(type="commit", label=commit.sha, url=commit.html_url)
            for commit in snapshot.recent_commits[:3]
            if commit.html_url
        ]
        citations.extend(
            AssistantCitation(type="pull_request", label=f"#{pull.number}", url=pull.html_url)
            for pull in snapshot.pull_requests[:3]
        )
        return ToolResult(
            call=AssistantToolCall(name="recent_activity", args={}, summary="Read recent commits and pull requests."),
            content=content,
            citations=citations,
        )


    def knowledge_graph_search(
        self,
        snapshot: RepositorySnapshot,
        query: str | None = None,
        focus: str | None = None,
    ) -> ToolResult:
        vector_rows = []
        if hasattr(repository_store, "search_knowledge"):
            try:
                vector_rows = repository_store.search_knowledge(
                    snapshot.identity.owner,
                    snapshot.identity.name,
                    query or focus or "repository knowledge",
                )
            except Exception:
                vector_rows = []
        if vector_rows:
            content = "\n\n".join(
                f"## {row['title']}\nScore: {float(row.get('score') or 0):.3f}\n{row['content']}"
                for row in vector_rows
            )
            citations = [
                AssistantCitation(type=row["source_type"], label=row["title"], path=row.get("source_path"))
                for row in vector_rows
                if row.get("source_path")
            ]
            return ToolResult(
                call=AssistantToolCall(
                    name="knowledge_graph_search",
                    args={"query": query, "focus": focus},
                    summary="Search pgvector-backed source RAG knowledge chunks.",
                ),
                content=content,
                citations=citations[:8],
            )

        results = self.knowledge_graph.search(snapshot, query=query, focus=focus)
        if not results:
            content = "No graph RAG knowledge chunks matched the query."
            citations: list[AssistantCitation] = []
        else:
            sections = []
            citations = []
            for result in results:
                chunk = result.chunk
                node_names = ", ".join(node.name for node in result.related_nodes[:5])
                sections.append(
                    f"## {chunk.title}\n"
                    f"Score: {result.score:.1f}\n"
                    f"Related graph nodes: {node_names or 'none'}\n"
                    f"{chunk.content}"
                )
                for node in result.related_nodes:
                    if node.path:
                        citations.append(
                            AssistantCitation(type=node.type, label=node.name, path=node.path)
                        )
            content = "\n\n".join(sections)

        return ToolResult(
            call=AssistantToolCall(
                name="knowledge_graph_search",
                args={"query": query, "focus": focus},
                summary="Search graph-enhanced RAG knowledge for structure, modules, dependencies, and tests.",
            ),
            content=content,
            citations=citations[:8],
        )



def merge_citations(results: list[ToolResult]) -> list[AssistantCitation]:
    """Deduplicate citations while preserving order."""
    seen: set[tuple[str, str, str | None]] = set()
    citations: list[AssistantCitation] = []
    for result in results:
        for citation in result.citations:
            key = (citation.type, citation.label, str(citation.url) if citation.url else citation.path)
            if key in seen:
                continue
            seen.add(key)
            citations.append(citation)
    return citations
