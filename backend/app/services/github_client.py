"""Async HTTP client for the GitHub REST API.

Wraps ``httpx.AsyncClient`` with GitHub-specific authentication, error
handling, exponential-backoff retries for transient failures, and
convenience methods for repository data fetching.
"""

import asyncio
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


# -- Retry helpers ----------------------------------------------------------


def _is_transient(status_code: int) -> bool:
    """True for status codes where retrying a GET request is safe."""
    return status_code in {429, 502, 503, 504} or status_code >= 500


async def _retry_with_backoff(
    coro_factory,
    max_retries: int,
) -> Any:
    """Call *coro_factory* up to *max_retries*+1 times with exponential backoff.

    *coro_factory* must be a zero-argument callable that returns an awaitable.
    Retries happen only for transient HTTP errors and network-level failures
    (``httpx.HTTPError``). Non-transient errors (4xx except 429) are raised
    immediately.
    """
    last: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await coro_factory()
        except httpx.HTTPError as exc:
            last = exc
            if attempt < max_retries:
                delay = 2 ** attempt
                await asyncio.sleep(delay)
            continue

        if response.status_code < 400:
            return response

        status = response.status_code
        if not _is_transient(status) or attempt == max_retries:
            message = "GitHub API request failed."
            try:
                message = response.json().get("message", message)
            except ValueError:
                pass
            sc = status if status in {400, 401, 403, 404} else 502
            raise GitHubClientError(message=message, status_code=sc)

        delay = 2 ** attempt
        if status == 429:  # rate-limited — use Retry-After if present
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = float(retry_after)
                except ValueError:
                    pass
        await asyncio.sleep(delay)

    # If we exit the loop, last is an httpx.HTTPError
    detail = str(last) or last.__class__.__name__
    raise GitHubClientError(f"GitHub request failed after {max_retries} retries: {detail}")


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

    async def get_file_content(self, ref: RepositoryRef, path: str, ref_name: str, max_bytes: int) -> tuple[str | None, bool]:
        """Fetch UTF-8 file content through GitHub contents API, capped for RAG indexing."""
        encoded_path = quote(path, safe="/")
        try:
            payload = await self._get(
                f"/repos/{ref.owner}/{ref.name}/contents/{encoded_path}",
                params={"ref": ref_name},
            )
        except GitHubClientError as exc:
            if exc.status_code == 404:
                return None, False
            raise

        if payload.get("type") != "file" or payload.get("encoding") != "base64":
            return None, False
        raw = payload.get("content")
        if not raw:
            return None, False
        decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
        byte_length = len(decoded.encode("utf-8"))
        truncated = byte_length > max_bytes or (payload.get("size") or 0) > max_bytes
        return decoded[:max_bytes], truncated

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

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with retry for transient failures."""
        method_label = method.upper()
        max_retries = 3

        async def _call():
            return await self._client.request(method, path, json=json_data, params=params)

        try:
            response = await _retry_with_backoff(_call, max_retries)
        except GitHubClientError:
            raise
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            raise GitHubClientError(
                f"[{method_label}] GitHub API request failed on {path}: {detail}"
            ) from exc

        # Build detailed error message for non-2xx responses.
        if response.status_code >= 400:
            try:
                body = response.json()
                gh_message = body.get("message", "")
            except ValueError:
                body = {}
                gh_message = ""

            rate_remaining = response.headers.get("x-ratelimit-remaining")
            rate_reset = response.headers.get("x-ratelimit-reset")

            parts = [f"[{method_label}] GitHub API error (HTTP {response.status_code})"]
            if gh_message:
                parts.append(f"message: {gh_message}")
            parts.append(f"path: {path}")
            if rate_remaining is not None and rate_remaining == "0":
                parts.append("API rate limit exceeded — set GITHUB_TOKEN or wait")
            if rate_reset:
                import datetime
                reset_time = datetime.datetime.fromtimestamp(int(rate_reset), tz=datetime.timezone.utc)
                parts.append(f"rate resets at {reset_time.isoformat()}")

            if method_label in ("POST", "PATCH") and response.status_code in (400, 422):
                if isinstance(body, dict) and "errors" in body:
                    parts.append(f"errors: {body['errors']}")

            sc = response.status_code if response.status_code in {400, 401, 403, 404, 422, 429} else 502
            raise GitHubClientError(message=" | ".join(parts), status_code=sc)

        return response.json()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json_data=json_data)

    async def _patch(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        return await self._request("PATCH", path, json_data=json_data)

    async def _put(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        return await self._request("PUT", path, json_data=json_data)

    # -- Write operations (auto-reply / auto-fix) ---------------------------

    async def comment_on_issue(self, ref: RepositoryRef, issue_number: int, body: str) -> dict[str, Any]:
        """Post a comment on a GitHub issue.

        Requires a GitHub token with ``issues:write`` scope.
        """
        return await self._post(
            f"/repos/{ref.owner}/{ref.name}/issues/{issue_number}/comments",
            json_data={"body": body},
        )

    async def update_issue(self, ref: RepositoryRef, issue_number: int, **fields: Any) -> dict[str, Any]:
        """Update issue fields (state, labels, title, etc.).

        Example::

            await client.update_issue(ref, 42, state="closed")
            await client.update_issue(ref, 42, labels=["bug", "triaged"])

        Requires a GitHub token with ``issues:write`` scope.
        """
        return await self._patch(
            f"/repos/{ref.owner}/{ref.name}/issues/{issue_number}",
            json_data=fields,
        )

    async def create_pull_request(
        self,
        ref: RepositoryRef,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> dict[str, Any]:
        """Open a pull request.

        Args:
            head: The name of the branch where changes are implemented.
            base: The name of the branch you want the changes pulled into.

        Requires a GitHub token with ``pull_requests:write`` scope.
        """
        return await self._post(
            f"/repos/{ref.owner}/{ref.name}/pulls",
            json_data={"title": title, "head": head, "base": base, "body": body},
        )

    async def create_branch(self, ref: RepositoryRef, branch_name: str, sha: str) -> dict[str, Any]:
        """Create a new branch from a given commit SHA.

        Requires a GitHub token with ``contents:write`` scope.
        """
        return await self._post(
            f"/repos/{ref.owner}/{ref.name}/git/refs",
            json_data={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )

    async def create_or_update_file(
        self,
        ref: RepositoryRef,
        path: str,
        content: str,
        commit_message: str,
        branch: str,
        sha: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a file in the repository.

        Args:
            path: File path in the repo (e.g. ``src/main.py``).
            content: UTF-8 file content (will be base64-encoded automatically).
            commit_message: Git commit message.
            branch: Target branch name.
            sha: Required when updating an existing file (get it from the
                  previous ``get_file_content`` response).

        Requires a GitHub token with ``contents:write`` scope.
        """
        import base64

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        json_data: dict[str, Any] = {
            "message": commit_message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            json_data["sha"] = sha
        return await self._put(
            f"/repos/{ref.owner}/{ref.name}/contents/{quote(path, safe='/')}",
            json_data=json_data,
        )
