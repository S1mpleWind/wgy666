"""Repository query facade used by assistant tools and future UI endpoints.

====================================================================
仓库查询门面服务
====================================================================

为 Agent 工具和 UI 端点提供统一的仓库数据访问接口，封装了缓存和刷新逻辑。

核心职责：
  1. get_snapshot(): 获取仓库快照，支持三种新鲜度模式：
     - FORCE_REFRESH:     强制重新同步（即使缓存未过期）。
     - REFRESH_IF_STALE:  缓存过期（> 10 分钟）时自动同步；这是默认模式。
     - CACHE_FIRST:       优先返回缓存（立即响应，不同步）。

  2. search_files():  按查询词/类别过滤仓库文件列表。
  3. list_issues():    按类别/状态过滤 Issue 列表。
  4. readme_excerpt(): 获取 README 摘要或按查询词搜索相关内容。

  5. 缓存策略：
     - 使用内存中的 repository_store 缓存最近同步的仓库快照。
     - 超过 STALE_AFTER（10 分钟）即视为过期。
     - 首次查询（缓存未命中）自动触发全量同步。

使用方式：
    svc = RepositoryQueryService()
    snapshot, from_cache = await svc.get_snapshot("owner", "repo")
"""

from datetime import datetime, timedelta, timezone

from app.schemas.assistant import FreshnessMode
from app.schemas.issue import GitHubIssue
from app.schemas.repository import ClassifiedFile, RepositorySnapshot, SyncRepositoryRequest
from app.services.repository_sync import RepositorySyncService
from app.storage import repository_store


# 缓存过期时间：超过 10 分钟不使用缓存数据
STALE_AFTER = timedelta(minutes=10)


class RepositoryQueryService:
    """Read repository state, refreshing it through sync when needed.

    仓库数据读取层，按需触发同步刷新。
    """

    async def get_snapshot(
        self,
        owner: str,
        name: str,
        freshness: FreshnessMode = FreshnessMode.CACHE_FIRST,
    ) -> tuple[RepositorySnapshot, bool]:
        """获取仓库快照，按指定新鲜度模式决定是否触发同步。

        流程：
          1. 从缓存中查找快照。
          2. 根据 freshness 模式判断是否需要同步。
          3. 如需同步 → 调用 RepositorySyncService.sync() → 存入缓存 → 返回。
          4. 缓存命中且未过期 → 直接返回（第二个返回值为 True）。

        Args:
            owner:     仓库所有者。
            name:      仓库名。
            freshness: 新鲜度模式。

        Returns:
            (snapshot, from_cache)：
              - snapshot:    仓库快照。
              - from_cache: True 表示数据来自缓存，False 表示刚刚同步。
        """
        snapshot = repository_store.get(owner, name)
        should_refresh = self._should_refresh(snapshot, freshness)

        if should_refresh:
            # 触发同步，刷新缓存
            snapshot = await RepositorySyncService().sync(
                SyncRepositoryRequest(url=f"https://github.com/{owner}/{name}")
            )
            repository_store.save(snapshot)
            return snapshot, False

        # 缓存未命中（首次查询），自动触发全量同步
        if snapshot is None:
            snapshot = await RepositorySyncService().sync(
                SyncRepositoryRequest(url=f"https://github.com/{owner}/{name}")
            )
            repository_store.save(snapshot)
            return snapshot, False

        return snapshot, True

    def search_files(
        self,
        snapshot: RepositorySnapshot,
        query: str | None = None,
        category: str | None = None,
        limit: int = 12,
    ) -> list[ClassifiedFile]:
        """按查询词和类别过滤仓库文件。

        过滤策略：
          - category 过滤：精确匹配 FileCategory 值。
          - query 过滤：大小写不敏感的路径子串匹配。

        Args:
            snapshot: 仓库快照。
            query:    文件路径搜索词（可选）。
            category: 文件类别过滤（如 ``"source_code"``）。
            limit:    最大返回数量。

        Returns:
            匹配的 ClassifiedFile 列表。
        """
        query_text = (query or "").lower().strip()
        results = snapshot.files

        if category:
            results = [file for file in results if file.category.value == category]
        if query_text:
            results = [file for file in results if query_text in file.path.lower()]

        return results[:limit]

    def list_issues(
        self,
        snapshot: RepositorySnapshot,
        category: str | None = None,
        state: str | None = None,
        limit: int = 10,
    ) -> list[GitHubIssue]:
        """按分类类别和状态过滤 Issue 列表。

        Args:
            snapshot: 仓库快照。
            category: Issue 分类类别（如 ``"bug"``、``"feature_request"``）。
            state:    Issue 状态（``"open"`` 或 ``"closed"``）。
            limit:    最大返回数量。

        Returns:
            匹配的 GitHubIssue 列表。
        """
        results = snapshot.issues

        if category:
            results = [issue for issue in results if issue.classification.category.value == category]
        if state:
            results = [issue for issue in results if issue.state == state]

        return results[:limit]

    def readme_excerpt(self, snapshot: RepositorySnapshot, query: str | None = None, limit: int = 1200) -> str | None:
        """获取 README 摘要，支持按查询词搜索相关内容。

        行为：
          - 无查询词：返回 README 前 limit 个字符。
          - 有查询词：返回包含查询词的行（最多 12 行），长度不超过 limit。

        Args:
            snapshot: 仓库快照。
            query:    可选的搜索词。
            limit:    最大字符数（默认 1200）。

        Returns:
            README 摘要文本，或 None（没有 README 时）。
        """
        if not snapshot.readme:
            return None

        if not query:
            return snapshot.readme[:limit]

        # 按查询词过滤匹配行
        lines = snapshot.readme.splitlines()
        query_text = query.lower()
        matches = [line for line in lines if query_text in line.lower()]
        if not matches:
            return snapshot.readme[:limit]  # 无匹配时返回开头部分
        return "\n".join(matches[:12])[:limit]

    def _should_refresh(self, snapshot: RepositorySnapshot | None, freshness: FreshnessMode) -> bool:
        """判断是否需要刷新仓库快照。

        决策逻辑：
          - FORCE_REFRESH:     始终刷新。
          - 快照为 None:       始终刷新（首次查询）。
          - CACHE_FIRST:       始终不刷新。
          - REFRESH_IF_STALE:  超过 STALE_AFTER（10 分钟）时刷新。

        Args:
            snapshot:  当前缓存中的快照（可能为 None）。
            freshness: 新鲜度模式。

        Returns:
            True 表示需要刷新。
        """
        if freshness == FreshnessMode.FORCE_REFRESH:
            return True
        if snapshot is None:
            return True
        if freshness == FreshnessMode.CACHE_FIRST:
            return False

        # 检查是否过期（使用 UTC 时间比较）
        synced_at = snapshot.synced_at
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - synced_at > STALE_AFTER
