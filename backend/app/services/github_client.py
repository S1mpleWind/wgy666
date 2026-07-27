"""Async HTTP client for the GitHub REST API.

Wraps ``httpx.AsyncClient`` with GitHub-specific authentication, error
handling, exponential-backoff retries for transient failures, and
convenience methods for repository data fetching.

====================================================================
GitHub REST API 异步 HTTP 客户端
====================================================================

基于 httpx.AsyncClient 封装的异步 HTTP 客户端，专用于 GitHub REST API 调用。

核心能力：
  1. 认证与请求头：
     - 通过 GITHUB_TOKEN（Bearer Token）进行身份认证。
     - 自动设置 Accept、X-GitHub-Api-Version、User-Agent 等必要请求头。

  2. 指数退避重试：
     - 对瞬时错误（429 频率限制、5xx 服务端错误）自动重试。
     - 退避公式：2^attempt 秒，最多 3 次。
     - 429 时优先使用响应头 Retry-After（服务端指定的等待时间）。
     - 非瞬态错误（400/401/403/404）不重试，直接抛出。

  3. 读操作（GET）：
     - get_repository:      获取仓库元数据（stars、forks、语言等）。
     - get_languages:       获取各语言的代码字节统计。
     - get_readme:          获取并 Base64 解码 README 文件。
     - get_tree:            获取完整 git tree（递归模式）。
     - get_file_content:    通过 Contents API 获取文件内容（Base64 解码，支持截断）。
     - get_issues:          获取 Issues 列表（自动过滤 PR）。
     - get_pull_requests:  获取 Pull Requests 列表。
     - get_commits:         获取 commit 历史。

  4. 写操作（POST/PUT/PATCH）：
     - comment_on_issue:    在 Issue 下添加评论。
     - update_issue:        更新 Issue 状态/标签等。
     - create_pull_request: 创建 Pull Request。
     - create_branch:       从指定 SHA 创建新分支。
     - create_or_update_file: 创建或更新仓库文件（自动 Base64 编码）。

  5. 错误信息增强：
     - 包含方法、路径、HTTP 状态码、GitHub 错误消息。
     - 在速率限制耗尽时，额外显示重置时间戳。

使用方式：
    async with GitHubClient() as client:
        repo = await client.get_repository(ref)
        tree = await client.get_tree(ref, "main")
"""

import asyncio
import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.services.repository_url import RepositoryRef


class GitHubClientError(Exception):
    """Carries both a human-readable message and an HTTP status code.

    Attributes:
        message:     人类可读的错误描述。
        status_code: HTTP 状态码（4xx/5xx）。
    """

    def __init__(self, message: str, status_code: int = 502) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# -- Retry helpers ----------------------------------------------------------
# 重试相关的辅助函数


def _is_transient(status_code: int) -> bool:
    """True for status codes where retrying a GET request is safe.

    判断 HTTP 状态码是否为瞬时错误（可安全重试）：
      - 429: Too Many Requests（频率限制，等待后可恢复）
      - 5xx: 服务端错误（临时性，下次请求可能成功）
      - 502/503/504: 网关/服务不可用
    """
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

    指数退避重试协程：

    重试触发条件：
      - httpx.HTTPError（网络层错误：连接超时、DNS 解析失败等）。
      - 瞬时 HTTP 错误（429 频率限制、5xx 服务端错误）。

    不重试的情况：
      - 4xx 客户端错误（401 未授权、403 禁止、404 未找到等）——重试无意义。
      - 已达最大重试次数。

    退避策略：
      - 默认：2^attempt 秒（1s, 2s, 4s, ...）。
      - 429 且存在 Retry-After 头时，使用服务端建议的等待时间。

    Args:
        coro_factory: 返回 awaitable 的零参数工厂函数。
        max_retries:  最大重试次数。

    Returns:
        成功的 HTTP Response 对象。

    Raises:
        GitHubClientError: 达到最大重试次数或遇到不可重试错误时抛出。
    """
    last: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await coro_factory()
        except httpx.HTTPError as exc:
            # 网络层错误：连接超时、DNS 失败等 → 重试
            last = exc
            if attempt < max_retries:
                delay = 2 ** attempt
                await asyncio.sleep(delay)
            continue

        if response.status_code < 400:
            return response  # 成功

        status = response.status_code
        # 非瞬时错误或已达重试上限 → 抛出异常
        if not _is_transient(status) or attempt == max_retries:
            message = "GitHub API request failed."
            try:
                message = response.json().get("message", message)
            except ValueError:
                pass  # 无法解析 JSON 响应体，使用默认消息
            sc = status if status in {400, 401, 403, 404} else 502
            raise GitHubClientError(message=message, status_code=sc)

        # 计算退避延迟
        delay = 2 ** attempt
        if status == 429:  # rate-limited — use Retry-After if present
            # 频率限制时，优先使用 GitHub 返回的 Retry-After 建议时间
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = float(retry_after)
                except ValueError:
                    pass  # 非数字格式则使用默认退避公式
        await asyncio.sleep(delay)

    # 如果退出循环，说明 last 是 httpx.HTTPError（所有重试都失败了）
    detail = str(last) or last.__class__.__name__
    raise GitHubClientError(f"GitHub request failed after {max_retries} retries: {detail}")


class GitHubClient:
    """Async context manager for GitHub REST API calls.

    基于 httpx.AsyncClient 的异步上下文管理器，自动处理连接生命周期。

    Usage::

        async with GitHubClient() as client:
            repo = await client.get_repository(ref)
    """

    def __init__(self) -> None:
        """初始化 HTTP 客户端，设置认证头和基础 URL。

        认证：通过 GITHUB_TOKEN 环境变量传入 Bearer Token。
        基础 URL：默认 https://api.github.com，可通过 GITHUB_API_BASE_URL 覆盖。
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": settings.github_api_version,
            "User-Agent": "wgy666-github-issue-analysis-platform",
        }
        cfg = get_effective_config()
        if cfg.github_token:
            headers["Authorization"] = f"Bearer {cfg.github_token}"

        self._client = httpx.AsyncClient(
            base_url=settings.github_api_base_url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
        )

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        """退出时关闭底层 HTTP 连接池。"""
        await self._client.aclose()

    # -- Repository metadata ------------------------------------------------
    # 仓库元数据相关接口

    async def get_repository(self, ref: RepositoryRef) -> dict[str, Any]:
        """Return repository metadata (owner, stats, topics, etc.).

        获取仓库基本信息：名称、描述、stars、forks、topics、默认分支等。

        Args:
            ref: 仓库引用（owner + name）。

        Returns:
            仓库元数据字典。
        """
        return await self._get(f"/repos/{ref.owner}/{ref.name}")

    async def get_languages(self, ref: RepositoryRef) -> dict[str, int]:
        """Return ``{language_name: bytes_count}``.

        获取仓库各语言的代码字节数统计。

        Args:
            ref: 仓库引用。

        Returns:
            语言名称到字节数的映射字典。
        """
        return await self._get(f"/repos/{ref.owner}/{ref.name}/languages")

    # -- Repository content -------------------------------------------------
    # 仓库内容相关接口

    async def get_readme(self, ref: RepositoryRef) -> str | None:
        """Fetch and decode the repository README (raw text, max 12 KiB).

        获取并解码仓库 README 文件。
        - 返回的是 Base64 解码后的 UTF-8 文本。
        - 截断至 12,000 字符以避免内存占用过大。
        - 仓库没有 README 时返回 None（不抛异常）。

        Args:
            ref: 仓库引用。

        Returns:
            README 文本内容，或 None（不存在时）。
        """
        try:
            payload = await self._get(f"/repos/{ref.owner}/{ref.name}/readme")
        except GitHubClientError as exc:
            if exc.status_code == 404:
                return None  # 没有 README，不视为错误
            raise

        content = payload.get("content")
        encoding = payload.get("encoding")
        if not content or encoding != "base64":
            return None
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
        return decoded[:12000]

    async def get_tree(self, ref: RepositoryRef, branch: str) -> list[dict[str, Any]]:
        """Return the full git tree (recursive) for the given branch.

        获取指定分支的完整 git tree（递归模式，包含所有子目录文件）。

        Args:
            ref:    仓库引用。
            branch: 分支名（如 ``main``）。

        Returns:
            tree 条目列表，每条包含 path、type、sha、size 等字段。
        """
        branch_ref = quote(branch, safe="")
        payload = await self._get(
            f"/repos/{ref.owner}/{ref.name}/git/trees/{branch_ref}",
            params={"recursive": "1"},
        )
        tree = payload.get("tree")
        return tree if isinstance(tree, list) else []

    async def get_file_content(self, ref: RepositoryRef, path: str, ref_name: str, max_bytes: int) -> tuple[str | None, bool]:
        """Fetch UTF-8 file content through GitHub contents API, capped for RAG indexing.

        通过 GitHub Contents API 获取文件内容，用于 RAG 索引。

        Args:
            ref:       仓库引用。
            path:      文件路径（如 ``src/main.py``）。
            ref_name:  分支名或 commit SHA。
            max_bytes: 最大返回字节数（用于限制 RAG 索引的单文件大小）。

        Returns:
            (content, truncated)：
              - content:   Base64 解码后的文件文本，解析失败时返回 None。
              - truncated: True 表示文件大小超过 max_bytes。
        """
        encoded_path = quote(path, safe="/")
        try:
            payload = await self._get(
                f"/repos/{ref.owner}/{ref.name}/contents/{encoded_path}",
                params={"ref": ref_name},
            )
        except GitHubClientError as exc:
            if exc.status_code == 404:
                return None, False  # 文件不存在
            raise

        # 只处理 base64 编码的普通文件（不支持子模块、目录链接等）
        if payload.get("type") != "file" or payload.get("encoding") != "base64":
            return None, False
        raw = payload.get("content")
        if not raw:
            return None, False
        decoded_bytes = base64.b64decode(raw)
        truncated = len(decoded_bytes) > max_bytes or (payload.get("size") or 0) > max_bytes
        decoded = decoded_bytes[:max_bytes].decode("utf-8", errors="ignore")
        return decoded, truncated

    # -- Issues, PRs, Commits -----------------------------------------------
    # Issue / Pull Request / Commit 相关接口

    async def get_issues(self, ref: RepositoryRef, limit: int) -> list[dict[str, Any]]:
        """Return recent issues (excludes PRs), sorted by last updated.

        获取最近的 Issues 列表。

        注意：
          - GitHub 的 /issues 端点会同时返回 Issues 和 Pull Requests。
          - 本方法自动过滤掉 PR（通过检查是否含 ``pull_request`` 字段）。

        Args:
            ref:   仓库引用。
            limit: 最多返回的 Issues 数量（0 表示不获取）。

        Returns:
            Issues 列表（已过滤 PR）。
        """
        if limit <= 0:
            return []
        issues: list[dict[str, Any]] = []
        page = 1
        per_page = min(100, max(limit, 30))
        while len(issues) < limit:
            payload = await self._get(
                f"/repos/{ref.owner}/{ref.name}/issues",
                params={
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            if not payload:
                break
            issues.extend(
                issue for issue in payload
                if "pull_request" not in issue
            )
            if len(payload) < per_page:
                break
            page += 1
        return issues[:limit]

    async def get_pull_requests(self, ref: RepositoryRef, limit: int) -> list[dict[str, Any]]:
        """Return recent pull requests, sorted by last updated.

        获取最近的 Pull Requests 列表。

        Args:
            ref:   仓库引用。
            limit: 最多返回的 PR 数量。

        Returns:
            PR 列表。
        """
        if limit <= 0:
            return []
        return await self._get(
            f"/repos/{ref.owner}/{ref.name}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": min(limit, 100)},
        )

    async def get_commits(self, ref: RepositoryRef, limit: int) -> list[dict[str, Any]]:
        """Return recent commits from the default branch.

        获取默认分支的最近 commit 列表。

        Args:
            ref:   仓库引用。
            limit: 最多返回的 commit 数量。

        Returns:
            Commit 列表。
        """
        if limit <= 0:
            return []
        return await self._get(
            f"/repos/{ref.owner}/{ref.name}/commits",
            params={"per_page": min(limit, 100)},
        )

    # -- Internal -----------------------------------------------------------
    # 内部 HTTP 请求方法

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with retry for transient failures.

        内部统一请求方法，带重试和增强错误信息。

        流程：
        1. 调用 _retry_with_backoff 执行带重试的 HTTP 请求。
        2. 对非 2xx 响应构建详细错误信息（含速率限制状态）。
        3. 返回 JSON 解析后的响应体。

        Args:
            method:    HTTP 方法（GET / POST / PUT / PATCH）。
            path:      API 路径（如 ``/repos/owner/name``）。
            json_data: 请求的 JSON 体（用于 POST/PUT/PATCH）。
            params:    查询参数（用于 GET）。

        Returns:
            JSON 解析后的响应体。

        Raises:
            GitHubClientError: HTTP 错误或请求失败。
        """
        method_label = method.upper()
        max_retries = 3

        async def _call():
            return await self._client.request(method, path, json=json_data, params=params)

        try:
            response = await _retry_with_backoff(_call, max_retries)
        except GitHubClientError:
            raise
        except Exception as exc:
            # 其他未预期的异常包装为 GitHubClientError
            detail = str(exc) or exc.__class__.__name__
            raise GitHubClientError(
                f"[{method_label}] GitHub API request failed on {path}: {detail}"
            ) from exc

        # 非 2xx 响应：构建详细的错误信息
        if response.status_code >= 400:
            try:
                body = response.json()
                gh_message = body.get("message", "")
            except ValueError:
                body = {}
                gh_message = ""

            # 检查速率限制状态
            rate_remaining = response.headers.get("x-ratelimit-remaining")
            rate_reset = response.headers.get("x-ratelimit-reset")

            parts = [f"[{method_label}] GitHub API error (HTTP {response.status_code})"]
            if gh_message:
                parts.append(f"message: {gh_message}")
            parts.append(f"path: {path}")
            if rate_remaining is not None and rate_remaining == "0":
                # 速率限制耗尽提示
                parts.append("API rate limit exceeded — set GITHUB_TOKEN or wait")
            if rate_reset:
                import datetime
                reset_time = datetime.datetime.fromtimestamp(int(rate_reset), tz=datetime.timezone.utc)
                parts.append(f"rate resets at {reset_time.isoformat()}")

            # POST/PATCH 的 400/422 错误通常包含 validation errors
            if method_label in ("POST", "PATCH") and response.status_code in (400, 422):
                if isinstance(body, dict) and "errors" in body:
                    parts.append(f"errors: {body['errors']}")

            sc = response.status_code if response.status_code in {400, 401, 403, 404, 422, 429} else 502
            raise GitHubClientError(message=" | ".join(parts), status_code=sc)

        return response.json()

    # 各 HTTP 方法的便捷封装
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json_data=json_data)

    async def _patch(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        return await self._request("PATCH", path, json_data=json_data)

    async def _put(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        return await self._request("PUT", path, json_data=json_data)

    # -- Write operations (auto-reply / auto-fix) ---------------------------
    # 写操作：自动回复 / 自动修复

    async def comment_on_issue(self, ref: RepositoryRef, issue_number: int, body: str) -> dict[str, Any]:
        """Post a comment on a GitHub issue.

        Requires a GitHub token with ``issues:write`` scope.

        在指定 issue 下发布评论。

        Args:
            ref:          仓库引用。
            issue_number: Issue 编号。
            body:         评论正文（Markdown 格式）。

        Returns:
            创建的评论对象。

        权限要求：Token 需具备 ``issues:write`` 范围。
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

        更新 issue 的字段（状态、标签、标题等）。

        Args:
            ref:          仓库引用。
            issue_number: Issue 编号。
            **fields:     要更新的字段键值对。

        权限要求：Token 需具备 ``issues:write`` 范围。
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

        创建一个 Pull Request。

        Args:
            ref:   仓库引用。
            title: PR 标题。
            head:  源分支名（包含修改的分支）。
            base:  目标分支名（要合入的分支，通常为 main/master）。
            body:  PR 描述（Markdown 格式）。

        权限要求：Token 需具备 ``pull_requests:write`` 范围。
        """
        return await self._post(
            f"/repos/{ref.owner}/{ref.name}/pulls",
            json_data={"title": title, "head": head, "base": base, "body": body},
        )

    async def create_branch(self, ref: RepositoryRef, branch_name: str, sha: str) -> dict[str, Any]:
        """Create a new branch from a given commit SHA.

        Requires a GitHub token with ``contents:write`` scope.

        从指定的 commit SHA 创建新分支。

        Args:
            ref:          仓库引用。
            branch_name:  新分支名称（如 ``auto-fix/issue-42``）。
            sha:          新分支的起始 commit SHA。

        权限要求：Token 需具备 ``contents:write`` 范围。
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

        创建或更新仓库中的单个文件。

        行为差异：
          - sha = None：创建新文件（如果文件已存在则报错）。
          - sha = 当前文件的 SHA：更新已有文件（并发安全，SHA 不匹配则失败）。

        Args:
            ref:            仓库引用。
            path:           文件路径（如 ``src/main.py``）。
            content:        UTF-8 文件内容（自动 Base64 编码）。
            commit_message: commit 消息。
            branch:        目标分支名。
            sha:           更新已有文件时必须提供（从 get_file_content 获取）。

        权限要求：Token 需具备 ``contents:write`` 范围。
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
