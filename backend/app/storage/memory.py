"""In-memory storage adapter for repository snapshots.

This is a temporary implementation that stores data in a Python dictionary.
Data is lost on server restart.
"""

from __future__ import annotations

from app.schemas.architecture import ArchitectureAnalysis, ArchitectureHistoryItem
from app.schemas.repository import RepositoryListItem, RepositorySnapshot
from app.services.architecture_analysis import ArchitectureAnalysisService


class InMemoryRepositoryStore:
    """Dict-backed store mapping ``owner/name`` → ``RepositorySnapshot``."""

    def __init__(self) -> None:
        self._snapshots: dict[str, RepositorySnapshot] = {}
        self._architecture_history: dict[str, dict[str, ArchitectureAnalysis]] = {}

    def save(self, snapshot: RepositorySnapshot) -> None:
        """Persist (or overwrite) a snapshot keyed by ``owner/name``."""
        self._snapshots[self._key(snapshot.identity.owner, snapshot.identity.name)] = snapshot
        self.save_architecture_analysis(snapshot)

    def get(self, owner: str, name: str) -> RepositorySnapshot | None:
        """Retrieve a snapshot by owner and name, or ``None`` if not synced."""
        return self._snapshots.get(self._key(owner, name))

    def list(self) -> list[RepositoryListItem]:
        """Return all snapshots sorted by sync time (newest first)."""
        snapshots = sorted(self._snapshots.values(), key=lambda item: item.synced_at, reverse=True)
        return [
            RepositoryListItem(
                owner=snapshot.identity.owner,
                name=snapshot.identity.name,
                full_name=snapshot.identity.full_name,
                html_url=snapshot.identity.html_url,
                description=snapshot.description,
                synced_at=snapshot.synced_at,
                issue_count=len(snapshot.issues),
                file_count=len(snapshot.files),
            )
            for snapshot in snapshots
        ]

    def get_file_contents(self, owner: str, name: str, path: str | None = None) -> list[dict]:
        """Return file contents from the in-memory snapshot (unfiltered when path is None)."""
        snapshot = self.get(owner, name)
        if snapshot is None:
            return []
        contents = [
            {
                "path": fc.path,
                "category": fc.category.value,
                "content": fc.content,
                "size": fc.size,
                "truncated": fc.truncated,
                "synced_at": snapshot.synced_at.isoformat() if snapshot.synced_at else None,
            }
            for fc in snapshot.source_contents
        ]
        if path:
            contents = [c for c in contents if c["path"] == path]
        return contents

    def get_file_content(self, owner: str, name: str, path: str) -> dict | None:
        """Return single file content by path, or None."""
        results = self.get_file_contents(owner, name, path)
        return results[0] if results else None

    def save_architecture_analysis(
        self,
        snapshot: RepositorySnapshot,
        analysis: ArchitectureAnalysis | None = None,
    ) -> ArchitectureAnalysis:
        key = self._key(snapshot.identity.owner, snapshot.identity.name)
        revision = ArchitectureAnalysisService.revision_for(snapshot)
        history = self._architecture_history.setdefault(key, {})
        existing = history.get(revision)
        if (
            analysis is None
            and existing is not None
            and existing.coverage.indexed_files == len(snapshot.source_contents)
            and existing.parser_version == ArchitectureAnalysisService.parser_version
        ):
            return existing
        result = analysis or ArchitectureAnalysisService().analyze(snapshot)
        history[result.revision] = result
        if len(history) > 20:
            oldest = min(history.values(), key=lambda item: item.generated_at)
            history.pop(oldest.revision, None)
        return result

    def get_architecture_analysis(
        self,
        owner: str,
        name: str,
        revision: str | None = None,
    ) -> ArchitectureAnalysis | None:
        history = self._architecture_history.get(self._key(owner, name), {})
        if revision:
            return history.get(revision)
        return max(history.values(), key=lambda item: item.generated_at, default=None)

    def list_architecture_analyses(self, owner: str, name: str) -> list[ArchitectureHistoryItem]:
        history = self._architecture_history.get(self._key(owner, name), {})
        return [
            ArchitectureHistoryItem(
                revision=item.revision,
                generated_at=item.generated_at,
                symbol_count=len(item.symbols),
                relation_count=len(item.relations),
                route_count=len(item.routes),
                health_score=item.health.score,
            )
            for item in sorted(history.values(), key=lambda value: value.generated_at, reverse=True)
        ]

    def _key(self, owner: str, name: str) -> str:
        return f"{owner.lower()}/{name.lower()}"


# Module-level singleton — imported by routes and services.
repository_store = InMemoryRepositoryStore()
