"""Async HTTP client for the GitHub REST API.

Wraps ``httpx.AsyncClient`` with GitHub-specific authentication, error
handling, and convenience methods for repository data fetching.
"""

import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services.repository_url import RepositoryRef


class GitHubClientError(Exception):
    """Carries both a human-readable message and an HTTP status code."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class GitHubClient:
    """Async context manager for GitHub REST API calls.

    Usage::

        async with GitHubClient() as client:
            repo = await client.get_repository(ref)
    """

    def __init__(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": settings.github_api_version,
            "User-Agent": "wgy666-github-issue-analysis-platform",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        self._client = httpx.AsyncClient(
            base_url=settings.github_api_base_url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
        )

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    # -- Repository metadata ------------------------------------------------

    async def get_repository(self, ref: RepositoryRef) -> dict[str, Any]:
        """Return repository metadata (owner, stats, topics, etc.)."""
        return await self._get(f"/repos/{ref.owner}/{ref.name}")

    async def get_languages(self, ref: RepositoryRef) -> dict[str, int]:
        """Return ``{language_name: bytes_count}``."""
        return await self._get(f"/repos/{ref.owner}/{ref.name}/languages")

    # -- Repository content -------------------------------------------------

    async def get_readme(self, ref: RepositoryRef) -> str | None:
        """Fetch and decode the repository README (raw text, max 12 KiB)."""
        try:
            payload = await self._get(f"/repos/{ref.owner}/{ref.name}/readme")
        except GitHubClientError as exc:
            if exc.status_code == 404:
                return None
            raise

        content = payload.get("content")
        encoding = payload.get("encoding")
        if not content or encoding != "base64":
            return None
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
        return decoded[:12000]

    async def get_tree(self, ref: RepositoryRef, branch: str) -> list[dict[str, Any]]:
        """Return the full git tree (recursive) for the given branch."""
        branch_ref = quote(branch, safe="")
        payload = await self._get(
            f"/repos/{ref.owner}/{ref.name}/git/trees/{branch_ref}",
            params={"recursive": "1"},
        )
        tree = payload.get("tree")
        return tree if isinstance(tree, list) else []

    # -- Issues, PRs, Commits -----------------------------------------------

    async def get_issues(self, ref: RepositoryRef, limit: int) -> list[dict[str, Any]]:
        """Return recent issues (excludes PRs), sorted by last updated."""
        if limit <= 0:
            return []
        payload = await self._get(
            f"/repos/{ref.owner}/{ref.name}/issues",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": min(limit, 100)},
        )
        # The /issues endpoint includes PRs; filter them out.
        return [issue for issue in payload[:limit] if "pull_request" not in issue]

    async def get_pull_requests(self, ref: RepositoryRef, limit: int) -> list[dict[str, Any]]:
        """Return recent pull requests, sorted by last updated."""
        if limit <= 0:
            return []
        return await self._get(
            f"/repos/{ref.owner}/{ref.name}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": min(limit, 100)},
        )

    async def get_commits(self, ref: RepositoryRef, limit: int) -> list[dict[str, Any]]:
        """Return recent commits from the default branch."""
        if limit <= 0:
            return []
        return await self._get(
            f"/repos/{ref.owner}/{ref.name}/commits",
            params={"per_page": min(limit, 100)},
        )

    # -- Internal -----------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform a GET request and raise ``GitHubClientError`` on failure."""
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            detail = str(exc) or exc.__class__.__name__
            raise GitHubClientError(f"GitHub request failed: {detail}") from exc

        if response.status_code >= 400:
            message = "GitHub API request failed."
            try:
                message = response.json().get("message", message)
            except ValueError:
                pass
            status_code = response.status_code if response.status_code in {400, 401, 403, 404} else 502
            raise GitHubClientError(message=message, status_code=status_code)

        return response.json()
