"""Orchestrates the end-to-end repository sync workflow.

Fetches data from GitHub → classifies files → classifies issues →
assembles a ``RepositorySnapshot``.

File tree and source content are obtained via a shallow ``git clone``
instead of the GitHub tree/content API to avoid rate-limit exhaustion.

====================================================================
仓库同步编排服务
====================================================================

协调端到端的仓库同步流程，将 GitHub 的原始数据转换为结构化的 RepositorySnapshot。

同步流水线步骤：
  1. 解析 GitHub URL → 提取 owner/name。
  2. 通过 GitHub API 获取仓库元数据、语言统计、README、Issues、PRs、Commits。
  3. 通过浅克隆（git clone --depth=1）获取本地文件树（避免 API 频率限制）。
  4. 对文件树进行双通道处理：
     - Channel A（采样通道）：随机采样 → FileClassifier 分类 → 用于类别统计。
     - Channel B（全量扫描通道）：遍历所有文件 → 读取源文件内容 → 用于 RAG 向量化。
  5. 对 Issues 进行分类（规则 + LLM 兜底）。
  6. 组装所有数据 → RepositorySnapshot。

关键技术决策：
  - 使用 git clone 替代 GitHub Tree API：
    git clone 消耗 1 次 API 配额（认证时）或 0 次（公开仓库），
    而遍历大型仓库完全使用 Tree API 可能消耗数十乃至数百次请求。
  - 双通道设计：统计通道采样（保证快速分类摘要）vs 全量通道（保证 RAG 召回率）。
  - 全量通道优先级排序：先保留小文件（DEPENDENCY < BUILD < SOURCE < ...）
    确保项目分析能在 RAG 文件预算耗尽前获取依赖清单。

使用方式：
    snapshot = await RepositorySyncService().sync(
        SyncRepositoryRequest(url="https://github.com/owner/repo")
    )
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

from app.schemas.issue import GitHubIssue
from app.schemas.repository import (
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
    """Coordinate GitHub data fetching → file/issue classification → snapshot creation.

    仓库同步的核心编排类，负责将分散的数据源汇聚为一致的快照。
    """

    def __init__(self) -> None:
        self.file_classifier = FileClassifier()
        self.issue_classifier = IssueClassifier()
        self._issue_llm_limit = asyncio.Semaphore(4)

    async def sync(self, request: SyncRepositoryRequest) -> RepositorySnapshot:
        """Execute a full repository sync and return the resulting snapshot.

        Steps:
        1. Parse the GitHub URL.
        2. Fetch repo metadata, languages, README, issues, PRs, commits via API.
        3. Clone the repo locally for file tree and source content.
        4. Classify files and issues.
        5. Assemble and return the snapshot.

        完整的同步流水线入口。

        Args:
            request: 同步请求（包含 GitHub URL 和各类上限参数）。

        Returns:
            RepositorySnapshot: 组装好的完整仓库快照。
        """
        ref = parse_github_repository_url(request.url)
        clone_url = f"https://github.com/{ref.owner}/{ref.name}.git"

        # ── Phase 1: GitHub API 数据获取 ───────────────────────────────
        # 并行获取仓库元数据、语言、README、Issues、PRs、Commits
        async with GitHubClient() as client:
            repository, languages, readme, issues, pulls, commits = await asyncio.gather(
                client.get_repository(ref),
                client.get_languages(ref),
                client.get_readme(ref),
                client.get_issues(ref, request.max_issues),
                client.get_pull_requests(ref, request.max_pull_requests),
                client.get_commits(ref, request.max_commits),
            )
            branch = repository.get("default_branch") or "main"

        # -- File classification + source content from git clone --------------
        async with GitCloneService(clone_url, token=settings.github_token) as git_clone:
            source_revision = await asyncio.to_thread(git_clone.head_revision)
            # Channel A: random sample for accurate category statistics
            tree = await asyncio.to_thread(
                git_clone.walk_files, request.max_tree_items,
            )
            files, file_categories = self.file_classifier.classify_many(
                tree, request.max_tree_items
            )

            # Channel B: full scan of all indexable files for RAG vectorization
            source_contents = await asyncio.to_thread(
                self._clone_all_indexable_files,
                git_clone,
                self.file_classifier,
                settings.rag_max_source_files,
                settings.rag_max_source_file_bytes,
            )

        classified_issues = list(await asyncio.gather(
            *(self._map_issue(issue) for issue in issues)
        ))
        issue_categories = self.issue_classifier.summarize(
            [issue.classification.category for issue in classified_issues]
        )

        # ── Phase 4: 快照组装 ───────────────────────────────────────
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
            source_revision=source_revision,
            synced_at=datetime.now(timezone.utc),
        )

    # -- Source content extraction (git clone) --------------------------------
    # 源码内容提取（基于 git clone 的全量扫描）

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

        全量扫描逻辑：

        1. 遍历克隆目录中的所有文件，跳过超大文件和资源/数据文件。
        2. 按优先级分桶存储各文件路径（不立即读取内容，节省 I/O）：
            优先级：DEPENDENCY > BUILD > SOURCE > TEST > DOCS > CONFIG > CI_CD > OTHER
        3. 按优先级依次填充内容列表，直到达到 max_files 上限。

        优先级设计的考虑：
          依赖清单（DEPENDENCY）先于源码（SOURCE）填充，确保在大型仓库中
          RAG 的文件预算耗尽之前，项目分析至少能获取依赖信息。

        Args:
            git_clone:  GitCloneService 实例（已克隆完成）。
            classifier: FileClassifier 实例用于分类。
            max_files:  最多保留的源文件数量。
            max_bytes:  单文件最大字节数（超过则跳过）。

        Returns:
            按优先级排序的 RepositoryFileContent 列表。
        """
        # 排除资源文件和数据文件（对 RAG 无意义）
        excluded = {FileCategory.ASSET, FileCategory.DATA}
        # 按优先级从高到低排列的文件类别
        priority_order = [
            FileCategory.DEPENDENCY,     # 依赖清单优先（小文件，为项目分析提供关键信息）
            FileCategory.BUILD,
            FileCategory.SOURCE,
            FileCategory.TEST,
            FileCategory.DOCUMENTATION,
            FileCategory.CONFIGURATION,
            FileCategory.CI_CD,
            FileCategory.OTHER,
        ]
        # 按类别分桶存储候选文件
        buckets: dict[FileCategory, list[dict]] = {c: [] for c in priority_order}

        for item in git_clone.walk_files():  # 无限制 —— 遍历所有文件
            path = item["path"]
            size = item.get("size")
            # 跳过超大文件
            if size is not None and size > max_bytes:
                continue

            category = classifier.classify(path)
            if category in excluded:
                continue

            buckets.setdefault(category, []).append(item)

        # 按优先级填充内容列表
        contents: list[RepositoryFileContent] = []
        seen: set[str] = set()  # 防止同一文件重复添加

        for category in priority_order:
            for item in buckets.get(category, []):
                path = item["path"]
                if path in seen:
                    continue
                seen.add(path)

                # 按需读取文件内容（此时才真正读磁盘）
                content, truncated = git_clone.read_file(path, max_bytes)
                if content is None or not content.strip():
                    continue  # 跳过二进制文件或空文件

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
                    return contents  # 达到上限，提前终止

        return contents

    # -- Mapping helpers (GitHub API → Pydantic models) --------------------
    # 数据映射辅助方法：将 GitHub API 原始数据映射为 Pydantic 模型

    async def _map_issue(self, payload: dict[str, Any]) -> GitHubIssue:
        """Map a GitHub API issue object to our ``GitHubIssue`` model.

        转换过程：
          1. 提取 labels 名称列表。
          2. 调用 issue_classifier.async_classify() 进行两阶段分类。
          3. 将分类结果嵌入 GitHubIssue 模型。

        Args:
            payload: GitHub API 返回的 Issue 原始数据。

        Returns:
            已分类的 GitHubIssue 模型。
        """
        labels = [label["name"] for label in payload.get("labels", []) if "name" in label]
        async with self._issue_llm_limit:
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
        """Map a GitHub API PR object to our ``PullRequestSummary`` model.

        Args:
            payload: GitHub API 返回的 PR 原始数据。

        Returns:
            PullRequestSummary 模型。
        """
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
        """Map a GitHub API commit object to our ``CommitSummary`` model.

        注意：
          - SHA 截取前 12 位（常规短 SHA 格式）。
          - Commit message 只取第一行（忽略空行后的详细描述）。

        Args:
            payload: GitHub API 返回的 Commit 原始数据。

        Returns:
            CommitSummary 模型。
        """
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
    """Parse an ISO-8601 datetime string, handling the trailing 'Z'.

    解析 ISO-8601 格式的时间字符串，处理 Python 不直接兼容的 'Z' 后缀。

    Args:
        value: ISO-8601 时间字符串（如 ``"2024-01-01T12:00:00Z"``）。

    Returns:
        datetime 对象（带 UTC 时区），或 None（输入为空时）。
    """
    if not value:
        return None
    # 将 'Z' 替换为 '+00:00' 以便 Python 解析为 UTC 时间
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
