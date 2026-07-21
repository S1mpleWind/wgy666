"""Git clone service for reading repository files from local disk.

Shallow-clones a GitHub repository into a temporary directory, then
provides methods to walk the file tree and read individual file contents.
This avoids consuming GitHub API rate limits for file-level operations.

====================================================================
Git 仓库克隆与本地文件读取服务
====================================================================

通过浅克隆（shallow clone, --depth=1）将 GitHub 仓库下载到临时目录，
然后提供以下能力：

  - walk_files():       遍历克隆目录中的所有文件，返回与 GitHub Git Tree API
                        兼容的 blob 条目列表（供 FileClassifier 使用）。
  - read_file():        读取单个文件内容，支持 UTF-8 解码和截断检测。

设计动机：
  - GitHub API 对文件内容获取有严格的速率限制（5,000 次/小时）。
  - 通过一次 git clone（仅消耗少量 API 配额），后续所有文件读取都在本地磁盘完成。
  - 使用 --depth=1 浅克隆极大减少下载量和时间（只获取最新版本，不包含历史）。

使用方式：
    async with GitCloneService("https://github.com/owner/repo") as svc:
        tree = svc.walk_files(limit=500)    # 获取文件列表
        text, truncated = svc.read_file("src/main.py", max_bytes=200000)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile

from app.core.config import settings


# 遍历时跳过的目录（与 GitHub Tree API 保持一致，排除 .git 等）
_EXCLUDED_DIRS = frozenset({".git", ".hg", ".svn", "__pycache__", "node_modules", ".mypy_cache"})


class GitCloneError(Exception):
    """Raised when git clone or file read fails.

    表示 git clone 操作或文件读取失败，携带具体错误原因。
    """


class GitCloneService:
    """Shallow-clone a remote repository and expose files for classification
    and content retrieval.

    异步上下文管理器，进入时执行浅克隆，退出时自动清理临时目录。

    Usage::

        async with GitCloneService("https://github.com/owner/repo") as svc:
            tree = svc.walk_files()          # list of dicts for classify_many
            text, truncated = svc.read_file("src/main.py", max_bytes=200000)
    """

    def __init__(self, clone_url: str) -> None:
        self._clone_url: str = clone_url  # 仓库克隆 URL（支持 token 认证）
        self._workdir: str = ""           # 临时工作目录路径（__aenter__ 后赋值）
        self._depth: int = 1              # 浅克隆深度：1 表示只获取最新 commit

    async def __aenter__(self) -> "GitCloneService":
        """进入上下文管理器：创建临时目录并执行 git clone。

        Raises:
            GitCloneError: 克隆失败时抛出，并自动清理临时目录。
        """
        self._workdir = tempfile.mkdtemp(prefix="repo_sync_")
        try:
            await self._clone()
        except Exception:
            # 失败时清理空临时目录，避免留下垃圾文件
            shutil.rmtree(self._workdir, ignore_errors=True)
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        """退出上下文管理器：删除临时目录及其所有内容。"""
        shutil.rmtree(self._workdir, ignore_errors=True)

    # -- Public API ----------------------------------------------------------

    def walk_files(self, limit: int | None = None) -> list[dict]:
        """Return file items compatible with ``FileClassifier.classify_many``.

        Each dict has keys ``type``, ``path``, and ``size``, matching the
        shape of GitHub git-tree API blob entries.

        The *limit* is applied only after collecting **all** files so that the
        subsequent classification pass sees a representative sample.  That
        sample is shuffled to avoid biasing results toward alphabetically
        early directories (e.g. ``docs/`` before ``src/``).

        遍历克隆目录中的所有文件，返回与 FileClassifier 兼容的数据格式。

        采样策略：
          - 先收集所有文件，再从中随机采样（使用固定种子 42，可复现）。
          - 保证统计样本的代表性，避免按字母顺序偏向某些目录（如 docs/ 排在 src/ 前面）。

        Args:
            limit: 最大返回文件数，None 表示不限制。

        Returns:
            文件条目列表，每条为 ``{"type": "blob", "path": "...", "size": ...}``。
        """
        import random

        items: list[dict] = []
        for root, dirs, files in os.walk(self._workdir):
            # 过滤需要跳过的目录（.git, node_modules 等），原地修改 dirs 列表
            dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS and not d.startswith(".")]

            for name in files:
                full_path = os.path.join(root, name)
                # 将绝对路径转换为仓库相对路径，统一使用正斜杠
                rel_path = os.path.relpath(full_path, self._workdir).replace("\\", "/")
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0  # 文件权限等异常时大小为 0
                items.append({"type": "blob", "path": rel_path, "size": size})

        if limit is not None and len(items) > limit:
            # 使用固定随机种子确保多次采样的结果可复现
            rng = random.Random(42)
            items = rng.sample(items, limit)

        return items

    def read_file(self, path: str, max_bytes: int) -> tuple[str | None, bool]:
        """Read file content from the local clone.

        Returns ``(content, truncated)``.  ``content`` is ``None`` when the
        file cannot be decoded as UTF-8 (binary / asset).

        从本地克隆中读取文件内容，适用于 RAG 索引和分类分析。

        Args:
            path:     文件在仓库中的相对路径。
            max_bytes: 最大读取字节数，超过则截断。

        Returns:
            (content, truncated)：
              - content:   解码后的 UTF-8 文本内容，无法解码时返回 None。
              - truncated: True 表示文件内容被截断（实际大小 > max_bytes）。
        """
        full_path = os.path.join(self._workdir, path.replace("/", os.sep))
        try:
            # 多读 1 个字节用来判断是否超过上限（用于截断检测）
            raw = _read_bytes(full_path, max_bytes)
        except OSError:
            return None, False

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # 二进制文件（图片、编译产物等）无法按 UTF-8 解码，返回 None
            return None, False

        # 如果读取的字节数超过了 max_bytes，说明文件被截断了
        truncated = len(raw) > max_bytes
        return text, truncated

    # -- Internal ------------------------------------------------------------

    async def _clone(self) -> None:
        """Run ``git clone --depth=<N> <url> <workdir>`` with retry.

        核心克隆逻辑，包含重试和超时控制。

        重试策略：
          - 最多 3 次重试，每次间隔递增（3s → 6s → 9s）。
          - 非瞬态错误不重试：认证失败、仓库不存在直接抛出异常。
          - 每次重试前清理上一次可能残留的部分克隆文件。

        超时控制：
          - 使用 asyncio.wait_for + communicate 实现超时（默认 300s）。
          - 超时后 kill 进程并尝试重试。

        Raises:
            GitCloneError: 所有重试都失败时抛出。
        """
        timeout = settings.git_clone_timeout_seconds
        max_retries = 3
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            # 每次尝试前清理工作目录（上次网络失败可能留下不完整的文件）
            if os.path.exists(self._workdir):
                import shutil
                shutil.rmtree(self._workdir, ignore_errors=True)

            # 启动 git clone 子进程
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                str(self._depth),
                self._clone_url,
                self._workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                # 等待进程完成（含超时控制）
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                # 超时：杀掉进程，等待递增延迟后重试
                try:
                    process.kill()
                except ProcessLookupError:
                    # 进程可能已经自行退出，忽略 kill 失败
                    pass
                last_error = f"git clone timed out after {timeout}s"
                if attempt < max_retries:
                    delay = 3 * (attempt + 1)
                    await asyncio.sleep(delay)
                    continue
                raise GitCloneError(f"{last_error} for {self._clone_url}") from None

            if process.returncode == 0:
                return  # 克隆成功

            message = stderr.decode("utf-8", errors="replace").strip()
            last_error = f"git clone failed: {message}"

            # 不可重试的错误：认证失败、仓库不存在
            if "Authentication failed" in message or "Repository not found" in message or "not found" in message:
                raise GitCloneError(f"{last_error} for {self._clone_url}")

            # 其他错误等待后重试
            if attempt < max_retries:
                delay = 3 * (attempt + 1)
                await asyncio.sleep(delay)
                continue

        raise GitCloneError(
            f"{last_error} for {self._clone_url} (after {max_retries} retries)"
        )


def _read_bytes(path: str, max_bytes: int) -> bytes:
    """Read up to *max_bytes* bytes from *path*.

    读取文件原始字节，多读 1 个字节用于截断检测。
    调用方通过 ``len(raw) > max_bytes`` 判断是否被截断。

    Args:
        path:     文件绝对路径。
        max_bytes: 期望读取的最大字节数。

    Returns:
        文件原始字节数据。
    """
    with open(path, "rb") as fh:
        return fh.read(max_bytes + 1)  # +1 to detect truncation
