"""Orchestrates the end-to-end repository sync workflow.

Fetches data from GitHub → classifies files → classifies issues →
assembles a ``RepositorySnapshot``.
"""

from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

from app.schemas.issue import GitHubIssue, IssueCategory
from app.schemas.repository import (
    ClassifiedFile,
    CommitSummary,
    FileCategory,
    PullRequestSummary,
    RepositoryFileContent,
    RepositoryIdentity,
    RepositorySnapshot,
    RepositoryStats,
    SyncRepositoryRequest,
)
from app.services.file_classifier import FileClassifier
from app.services.github_client import GitHubClient
from app.services.issue_classifier import IssueClassifier
from app.services.repository_url import parse_github_repository_url


class RepositorySyncService:
    """Coordinate GitHub data fetching → file/issue classification → snapshot creation."""

    def __init__(self) -> None:
        self.file_classifier = FileClassifier()
        self.issue_classifier = IssueClassifier()

    async def sync(self, request: SyncRepositoryRequest) -> RepositorySnapshot:
        """Execute a full repository sync and return the resulting snapshot.

        Steps:
        1. Parse the GitHub URL.
        2. Fetch repo metadata, languages, README, tree, issues, PRs, commits.
        3. Classify files and issues.
        4. Assemble and return the snapshot.
        """
        ref = parse_github_repository_url(request.url)
        async with GitHubClient() as client:
            repository = await client.get_repository(ref)
            languages = await client.get_languages(ref)
            readme = await client.get_readme(ref)
            branch = repository.get("default_branch") or "main"
            tree = await client.get_tree(ref, branch)
            issues = await client.get_issues(ref, request.max_issues)
            pulls = await client.get_pull_requests(ref, request.max_pull_requests)
            commits = await client.get_commits(ref, request.max_commits)

        files, file_categories = self.file_classifier.classify_many(tree, request.max_tree_items)
        async with GitHubClient() as client:
            source_contents = await self._fetch_source_contents(client, ref, branch, files)
        classified_issues = [self._map_issue(issue) for issue in issues]
        issue_categories = self.issue_classifier.summarize(
            [issue.classification.category for issue in classified_issues]
        )

        return RepositorySnapshot(
            identity=RepositoryIdentity(
                owner=repository["owner"]["login"],
                name=repository["name"],
                full_name=repository["full_name"],
                html_url=repository["html_url"],
                default_branch=branch,
            ),
            description=repository.get("description"),
            stats=RepositoryStats(
                stars=repository.get("stargazers_count", 0),
                forks=repository.get("forks_count", 0),
                watchers=repository.get("watchers_count", 0),
                open_issues=repository.get("open_issues_count", 0),
                size_kb=repository.get("size", 0),
                primary_language=repository.get("language"),
                languages=languages,
            ),
            topics=repository.get("topics") or [],
            readme=readme,
            files=files,
            source_contents=source_contents,
            file_categories=file_categories,
            issues=classified_issues,
            issue_categories=issue_categories,
            pull_requests=[self._map_pull_request(pull) for pull in pulls],
            recent_commits=[self._map_commit(commit) for commit in commits],
            synced_at=datetime.now(timezone.utc),
        )

    async def _fetch_source_contents(
        self,
        client: GitHubClient,
        ref,
        branch: str,
        files: list[ClassifiedFile],
    ) -> list[RepositoryFileContent]:
        """Fetch source files for persistent storage and RAG indexing.

        All file categories except ASSET (images/binaries) and DATA
        (large datasets) are indexed. The per-call cap is controlled by
        ``rag_max_source_files`` and ``rag_max_source_file_bytes``.
        """
        indexable_categories = {
            FileCategory.SOURCE,
            FileCategory.TEST,
            FileCategory.DOCUMENTATION,
            FileCategory.DEPENDENCY,
            FileCategory.CONFIGURATION,
            FileCategory.CI_CD,
            FileCategory.BUILD,
            FileCategory.OTHER,
        }
        selected = [
            file
            for file in files
            if file.category in indexable_categories
            and (file.size is None or file.size <= settings.rag_max_source_file_bytes)
        ][: settings.rag_max_source_files]

        contents: list[RepositoryFileContent] = []
        for file in selected:
            content, truncated = await client.get_file_content(
                ref,
                file.path,
                branch,
                settings.rag_max_source_file_bytes,
            )
            if content is None or not content.strip():
                continue
            contents.append(
                RepositoryFileContent(
                    path=file.path,
                    category=file.category,
                    content=content,
                    size=file.size,
                    truncated=truncated,
                )
            )
        return contents

    # -- Mapping helpers (GitHub API → Pydantic models) --------------------

    def _map_issue(self, payload: dict[str, Any]) -> GitHubIssue:
        """Map a GitHub API issue object to our ``GitHubIssue`` model."""
        labels = [label["name"] for label in payload.get("labels", []) if "name" in label]
        classification = self.issue_classifier.classify(
            title=payload.get("title") or "",
            body=payload.get("body"),
            labels=labels,
        )
        return GitHubIssue(
            number=payload["number"],
            title=payload.get("title") or "",
            state=payload.get("state") or "unknown",
            html_url=payload["html_url"],
            author=(payload.get("user") or {}).get("login"),
            labels=labels,
            created_at=_parse_datetime(payload.get("created_at")),
            updated_at=_parse_datetime(payload.get("updated_at")),
            comments=payload.get("comments", 0),
            classification=classification,
        )

    def _map_pull_request(self, payload: dict[str, Any]) -> PullRequestSummary:
        """Map a GitHub API PR object to our ``PullRequestSummary`` model."""
        return PullRequestSummary(
            number=payload["number"],
            title=payload.get("title") or "",
            state=payload.get("state") or "unknown",
            html_url=payload["html_url"],
            author=(payload.get("user") or {}).get("login"),
            created_at=_parse_datetime(payload.get("created_at")),
            updated_at=_parse_datetime(payload.get("updated_at")),
        )

    def _map_commit(self, payload: dict[str, Any]) -> CommitSummary:
        """Map a GitHub API commit object to our ``CommitSummary`` model."""
        commit = payload.get("commit") or {}
        author = commit.get("author") or {}
        return CommitSummary(
            sha=(payload.get("sha") or "")[:12],
            message=(commit.get("message") or "").splitlines()[0],
            author=author.get("name"),
            html_url=payload.get("html_url"),
            committed_at=_parse_datetime(author.get("date")),
        )


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string, handling the trailing 'Z'."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
