"""Tool implementations available to the repository assistant harness."""

from dataclasses import dataclass, field
from typing import Any

from app.schemas.assistant import AssistantCitation, AssistantToolCall
from app.schemas.project_analysis import ProjectAnalysis
from app.schemas.repository import RepositorySnapshot
from app.services.project_analysis import ProjectAnalysisService
from app.services.repository_query import RepositoryQueryService


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
