"""Orchestrates the end-to-end repository sync workflow.

Fetches data from GitHub → classifies files → classifies issues →
assembles a ``RepositorySnapshot``.

File tree and source content are obtained via a shallow ``git clone``
instead of the GitHub tree/content API to avoid rate-limit exhaustion.
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
from app.services.git_clone import GitCloneService
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
        2. Fetch repo metadata, languages, README, issues, PRs, commits via API.
        3. Clone the repo locally for file tree and source content.
        4. Classify files and issues.
        5. Assemble and return the snapshot.
        """
        ref = parse_github_repository_url(request.url)
        if settings.github_token:
            # Authenticated clone — avoids GitHub rate limits for git operations.
            clone_url = f"https://x-access-token:{settings.github_token}@github.com/{ref.owner}/{ref.name}.git"
        else:
            clone_url = f"https://github.com/{ref.owner}/{ref.name}.git"

        async with GitHubClient() as client:
            repository = await client.get_repository(ref)
            languages = await client.get_languages(ref)
            readme = await client.get_readme(ref)
            branch = repository.get("default_branch") or "main"
            issues = await client.get_issues(ref, request.max_issues)
            pulls = await client.get_pull_requests(ref, request.max_pull_requests)
            commits = await client.get_commits(ref, request.max_commits)

        # -- File classification + source content from git clone --------------
        async with GitCloneService(clone_url) as git_clone:
            # Channel A: random sample for accurate category statistics
            tree = git_clone.walk_files(limit=request.max_tree_items)
            files, file_categories = self.file_classifier.classify_many(
                tree, request.max_tree_items
            )

            # Channel B: full scan of all indexable files for RAG vectorization
            source_contents = self._clone_all_indexable_files(
                git_clone,
                self.file_classifier,
                max_files=settings.rag_max_source_files,
                max_bytes=settings.rag_max_source_file_bytes,
            )

        classified_issues = [await self._map_issue(issue) for issue in issues]
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

    # -- Source content extraction (git clone) --------------------------------

    def _clone_all_indexable_files(
        self,
        git_clone: GitCloneService,
        classifier: FileClassifier,
        max_files: int,
        max_bytes: int,
    ) -> list[RepositoryFileContent]:
        """Walk the full clone and read every indexable file for RAG vectorization.

        Unlike the sampled *files* list used for category statistics, this
        scan is exhaustive — it collects **all** candidates first, then
        selects up to *max_files* items. Small manifests are retained first
        so project analysis can inspect dependencies before source indexing
        consumes the available file budget.
        """
        excluded = {FileCategory.ASSET, FileCategory.DATA}
        priority_order = [
            # Keep small manifests available for project analysis even when a
            # repository has more source files than the RAG indexing limit.
            FileCategory.DEPENDENCY,
            FileCategory.BUILD,
            FileCategory.SOURCE,
            FileCategory.TEST,
            FileCategory.DOCUMENTATION,
            FileCategory.CONFIGURATION,
            FileCategory.CI_CD,
            FileCategory.OTHER,
        ]
        # map category → list of dicts that pass the size filter
        buckets: dict[FileCategory, list[dict]] = {c: [] for c in priority_order}

        for item in git_clone.walk_files():  # no limit — full scan
            path = item["path"]
            size = item.get("size")
            if size is not None and size > max_bytes:
                continue

            category = classifier.classify(path)
            if category in excluded:
                continue

            buckets.setdefault(category, []).append(item)

        # Fill results by priority, reading file contents on demand.
        contents: list[RepositoryFileContent] = []
        seen: set[str] = set()

        for category in priority_order:
            for item in buckets.get(category, []):
                path = item["path"]
                if path in seen:
                    continue
                seen.add(path)

                content, truncated = git_clone.read_file(path, max_bytes)
                if content is None or not content.strip():
                    continue

                contents.append(
                    RepositoryFileContent(
                        path=path,
                        category=category,
                        content=content,
                        size=item.get("size"),
                        truncated=truncated,
                    )
                )
                if len(contents) >= max_files:
                    return contents

        return contents

    # -- Mapping helpers (GitHub API → Pydantic models) --------------------

    async def _map_issue(self, payload: dict[str, Any]) -> GitHubIssue:
        """Map a GitHub API issue object to our ``GitHubIssue`` model."""
        labels = [label["name"] for label in payload.get("labels", []) if "name" in label]
        classification = await self.issue_classifier.async_classify(
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
