"""Git clone service for reading repository files from local disk.

Shallow-clones a GitHub repository into a temporary directory, then
provides methods to walk the file tree and read individual file contents.
This avoids consuming GitHub API rate limits for file-level operations.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile

from app.core.config import settings


# Directories to skip during walk (same as GitHub tree API excludes .git)
_EXCLUDED_DIRS = frozenset({".git", ".hg", ".svn", "__pycache__", "node_modules", ".mypy_cache"})


class GitCloneError(Exception):
    """Raised when git clone or file read fails."""


class GitCloneService:
    """Shallow-clone a remote repository and expose files for classification
    and content retrieval.

    Usage::

        async with GitCloneService("https://github.com/owner/repo") as svc:
            tree = svc.walk_files()          # list of dicts for classify_many
            text, truncated = svc.read_file("src/main.py", max_bytes=200000)
    """

    def __init__(self, clone_url: str, token: str | None = None) -> None:
        self._clone_url: str = clone_url
        self._token = token
        self._workdir: str = ""
        self._depth: int = 1

    async def __aenter__(self) -> "GitCloneService":
        self._workdir = tempfile.mkdtemp(prefix="repo_sync_")
        try:
            await self._clone()
        except Exception:
            # Clean up the empty temp dir on failure.
            shutil.rmtree(self._workdir, ignore_errors=True)
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
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
        """
        import random

        items: list[dict] = []
        for root, dirs, files in os.walk(self._workdir):
            dirs[:] = [
                d for d in dirs
                if d not in _EXCLUDED_DIRS
                and not d.startswith(".")
                and not os.path.islink(os.path.join(root, d))
            ]

            for name in files:
                full_path = os.path.join(root, name)
                if os.path.islink(full_path) or not os.path.isfile(full_path):
                    continue
                rel_path = os.path.relpath(full_path, self._workdir).replace("\\", "/")
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0
                items.append({"type": "blob", "path": rel_path, "size": size})

        if limit is not None and len(items) > limit:
            rng = random.Random(42)  # deterministic for reproducibility
            items = rng.sample(items, limit)

        return items

    def read_file(self, path: str, max_bytes: int) -> tuple[str | None, bool]:
        """Read file content from the local clone.

        Returns ``(content, truncated)``.  ``content`` is ``None`` when the
        file cannot be decoded as UTF-8 (binary / asset).
        """
        full_path = os.path.realpath(os.path.join(self._workdir, path.replace("/", os.sep)))
        workdir = os.path.realpath(self._workdir)
        try:
            if os.path.commonpath([workdir, full_path]) != workdir:
                return None, False
        except ValueError:
            return None, False
        if os.path.islink(os.path.join(self._workdir, path.replace("/", os.sep))):
            return None, False
        if not os.path.isfile(full_path):
            return None, False
        try:
            raw = _read_bytes(full_path, max_bytes)
        except OSError:
            return None, False

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, False

        truncated = len(raw) > max_bytes
        return text, truncated

    # -- Internal ------------------------------------------------------------

    async def _clone(self) -> None:
        """Run ``git clone --depth=<N> <url> <workdir>`` with retry."""
        timeout = settings.git_clone_timeout_seconds
        max_retries = 3
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            # Clean up workdir before each attempt (previous run may have
            # left partial files on network failure).
            if os.path.exists(self._workdir):
                import shutil
                shutil.rmtree(self._workdir, ignore_errors=True)
            env = os.environ.copy()
            if self._token:
                credential = base64.b64encode(
                    f"x-access-token:{self._token}".encode("utf-8")
                ).decode("ascii")
                env.update({
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
                })
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                str(self._depth),
                self._clone_url,
                self._workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                last_error = f"git clone timed out after {timeout}s"
                if attempt < max_retries:
                    delay = 3 * (attempt + 1)
                    await asyncio.sleep(delay)
                    continue
                raise GitCloneError(last_error) from None

            if process.returncode == 0:
                return  # success

            message = stderr.decode("utf-8", errors="replace").strip()
            last_error = f"git clone failed: {message}"

            # Non-retriable: auth error, repo not found
            if "Authentication failed" in message or "Repository not found" in message or "not found" in message:
                raise GitCloneError(last_error)

            if attempt < max_retries:
                delay = 3 * (attempt + 1)
                await asyncio.sleep(delay)
                continue

        raise GitCloneError(
            f"{last_error} (after {max_retries} retries)"
        )


def _read_bytes(path: str, max_bytes: int) -> bytes:
    """Read up to *max_bytes* bytes from *path*."""
    with open(path, "rb") as fh:
        return fh.read(max_bytes + 1)  # +1 to detect truncation
