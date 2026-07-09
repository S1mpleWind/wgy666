"""Repository query facade used by assistant tools and future UI endpoints."""

from datetime import datetime, timedelta, timezone

from app.schemas.assistant import FreshnessMode
from app.schemas.issue import GitHubIssue
from app.schemas.repository import ClassifiedFile, RepositorySnapshot, SyncRepositoryRequest
from app.services.repository_sync import RepositorySyncService
from app.storage.memory import repository_store


STALE_AFTER = timedelta(minutes=10)


class RepositoryQueryService:
    """Read repository state, refreshing it through sync when needed."""

    async def get_snapshot(
        self,
        owner: str,
        name: str,
        freshness: FreshnessMode = FreshnessMode.REFRESH_IF_STALE,
    ) -> tuple[RepositorySnapshot, bool]:
        snapshot = repository_store.get(owner, name)
        should_refresh = self._should_refresh(snapshot, freshness)

        if should_refresh:
            snapshot = await RepositorySyncService().sync(
                SyncRepositoryRequest(url=f"https://github.com/{owner}/{name}")
            )
            repository_store.save(snapshot)
            return snapshot, False

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
        results = snapshot.issues

        if category:
            results = [issue for issue in results if issue.classification.category.value == category]
        if state:
            results = [issue for issue in results if issue.state == state]

        return results[:limit]

    def readme_excerpt(self, snapshot: RepositorySnapshot, query: str | None = None, limit: int = 1200) -> str | None:
        if not snapshot.readme:
            return None

        if not query:
            return snapshot.readme[:limit]

        lines = snapshot.readme.splitlines()
        query_text = query.lower()
        matches = [line for line in lines if query_text in line.lower()]
        if not matches:
            return snapshot.readme[:limit]
        return "\n".join(matches[:12])[:limit]

    def _should_refresh(self, snapshot: RepositorySnapshot | None, freshness: FreshnessMode) -> bool:
        if freshness == FreshnessMode.FORCE_REFRESH:
            return True
        if snapshot is None:
            return True
        if freshness == FreshnessMode.CACHE_FIRST:
            return False

        synced_at = snapshot.synced_at
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - synced_at > STALE_AFTER
