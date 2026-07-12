"""In-memory storage adapter for repository snapshots.

This is a temporary implementation that stores data in a Python dictionary.
Data is lost on server restart.
"""

from __future__ import annotations

from app.schemas.repository import RepositoryListItem, RepositorySnapshot


class InMemoryRepositoryStore:
    """Dict-backed store mapping ``owner/name`` → ``RepositorySnapshot``."""

    def __init__(self) -> None:
        self._snapshots: dict[str, RepositorySnapshot] = {}

    def save(self, snapshot: RepositorySnapshot) -> None:
        """Persist (or overwrite) a snapshot keyed by ``owner/name``."""
        self._snapshots[self._key(snapshot.identity.owner, snapshot.identity.name)] = snapshot

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

    def _key(self, owner: str, name: str) -> str:
        return f"{owner.lower()}/{name.lower()}"


# Module-level singleton — imported by routes and services.
repository_store = InMemoryRepositoryStore()
