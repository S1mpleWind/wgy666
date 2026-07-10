"""PostgreSQL-backed repository snapshot store."""

from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from app.schemas.repository import RepositoryListItem, RepositorySnapshot
from app.services.knowledge_graph import KnowledgeGraphService
from app.storage.database import (
    commits,
    create_database_engine,
    initialize_database,
    issues,
    knowledge_chunks,
    knowledge_edges,
    knowledge_nodes,
    pull_requests,
    repositories,
    repository_files,
    repository_snapshots,
    sync_runs,
)


class PostgresRepositoryStore:
    """Persist synced repositories in PostgreSQL.

    The store writes both a faithful snapshot JSON and normalized core tables.
    Current API reads reconstruct snapshots from JSON for compatibility; later
    RAG and analytics features can query the normalized tables directly.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or create_database_engine()
        initialize_database(self.engine)

    def save(self, snapshot: RepositorySnapshot) -> None:
        with self.engine.begin() as connection:
            repository_id = self._upsert_repository(connection, snapshot)

            connection.execute(
                delete(repository_snapshots).where(repository_snapshots.c.repository_id == repository_id)
            )
            connection.execute(
                insert(repository_snapshots).values(
                    repository_id=repository_id,
                    snapshot=snapshot.model_dump(mode="json"),
                    synced_at=snapshot.synced_at,
                )
            )

            self._replace_files(connection, repository_id, snapshot)
            self._replace_issues(connection, repository_id, snapshot)
            self._replace_pull_requests(connection, repository_id, snapshot)
            self._replace_commits(connection, repository_id, snapshot)
            self._replace_knowledge_graph(connection, repository_id, snapshot)
            self._record_sync_run(connection, repository_id, snapshot)

    def get(self, owner: str, name: str) -> RepositorySnapshot | None:
        statement = (
            select(repository_snapshots.c.snapshot)
            .select_from(
                repository_snapshots.join(
                    repositories,
                    repository_snapshots.c.repository_id == repositories.c.id,
                )
            )
            .where(repositories.c.owner == owner, repositories.c.name == name)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).first()
        if row is None:
            return None
        return RepositorySnapshot.model_validate(row.snapshot)

    def list(self) -> list[RepositoryListItem]:
        statement = (
            select(
                repositories.c.owner,
                repositories.c.name,
                repositories.c.full_name,
                repositories.c.html_url,
                repositories.c.description,
                repositories.c.synced_at,
                repository_snapshots.c.snapshot,
            )
            .select_from(
                repositories.join(
                    repository_snapshots,
                    repository_snapshots.c.repository_id == repositories.c.id,
                )
            )
            .order_by(repositories.c.synced_at.desc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).all()

        items: list[RepositoryListItem] = []
        for row in rows:
            snapshot = RepositorySnapshot.model_validate(row.snapshot)
            items.append(
                RepositoryListItem(
                    owner=row.owner,
                    name=row.name,
                    full_name=row.full_name,
                    html_url=row.html_url,
                    description=row.description,
                    synced_at=row.synced_at,
                    issue_count=len(snapshot.issues),
                    file_count=len(snapshot.files),
                )
            )
        return items

    def _upsert_repository(self, connection, snapshot: RepositorySnapshot) -> int:
        identity = snapshot.identity
        stats = snapshot.stats
        values = {
            "owner": identity.owner,
            "name": identity.name,
            "full_name": identity.full_name,
            "html_url": str(identity.html_url),
            "default_branch": identity.default_branch,
            "description": snapshot.description,
            "primary_language": stats.primary_language,
            "stars": stats.stars,
            "forks": stats.forks,
            "watchers": stats.watchers,
            "open_issues": stats.open_issues,
            "size_kb": stats.size_kb,
            "languages": stats.languages,
            "topics": snapshot.topics,
            "synced_at": snapshot.synced_at,
        }
        row = connection.execute(
            select(repositories.c.id).where(
                repositories.c.owner == identity.owner,
                repositories.c.name == identity.name,
            )
        ).first()
        if row is None:
            return connection.execute(insert(repositories).values(**values).returning(repositories.c.id)).scalar_one()

        connection.execute(
            update(repositories)
            .where(repositories.c.id == row.id)
            .values(**values)
        )
        return row.id

    def _replace_files(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        connection.execute(delete(repository_files).where(repository_files.c.repository_id == repository_id))
        if not snapshot.files:
            return
        connection.execute(
            insert(repository_files),
            [
                {
                    "repository_id": repository_id,
                    "path": file.path,
                    "category": file.category.value,
                    "size": file.size,
                }
                for file in snapshot.files
            ],
        )

    def _replace_issues(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        connection.execute(delete(issues).where(issues.c.repository_id == repository_id))
        if not snapshot.issues:
            return
        connection.execute(
            insert(issues),
            [
                {
                    "repository_id": repository_id,
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "html_url": str(issue.html_url),
                    "author": issue.author,
                    "labels": issue.labels,
                    "comments": issue.comments,
                    "classification_category": issue.classification.category.value,
                    "classification_confidence": round(issue.classification.confidence * 100),
                    "classification": issue.classification.model_dump(mode="json"),
                    "created_at": issue.created_at,
                    "updated_at": issue.updated_at,
                }
                for issue in snapshot.issues
            ],
        )

    def _replace_pull_requests(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        connection.execute(delete(pull_requests).where(pull_requests.c.repository_id == repository_id))
        if not snapshot.pull_requests:
            return
        connection.execute(
            insert(pull_requests),
            [
                {
                    "repository_id": repository_id,
                    "number": pull.number,
                    "title": pull.title,
                    "state": pull.state,
                    "html_url": str(pull.html_url),
                    "author": pull.author,
                    "created_at": pull.created_at,
                    "updated_at": pull.updated_at,
                }
                for pull in snapshot.pull_requests
            ],
        )

    def _replace_commits(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        connection.execute(delete(commits).where(commits.c.repository_id == repository_id))
        if not snapshot.recent_commits:
            return
        connection.execute(
            insert(commits),
            [
                {
                    "repository_id": repository_id,
                    "sha": commit.sha,
                    "message": commit.message,
                    "author": commit.author,
                    "html_url": str(commit.html_url) if commit.html_url else None,
                    "committed_at": commit.committed_at,
                }
                for commit in snapshot.recent_commits
            ],
        )


    def _replace_knowledge_graph(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        graph = KnowledgeGraphService().build(snapshot)
        connection.execute(delete(knowledge_edges).where(knowledge_edges.c.repository_id == repository_id))
        connection.execute(delete(knowledge_chunks).where(knowledge_chunks.c.repository_id == repository_id))
        connection.execute(delete(knowledge_nodes).where(knowledge_nodes.c.repository_id == repository_id))

        if graph.nodes:
            connection.execute(
                insert(knowledge_nodes),
                [
                    {
                        "repository_id": repository_id,
                        "node_key": node.key,
                        "node_type": node.type,
                        "name": node.name,
                        "path": node.path,
                        "summary": node.summary,
                        "metadata_json": node.metadata,
                    }
                    for node in graph.nodes
                ],
            )
        if graph.edges:
            connection.execute(
                insert(knowledge_edges),
                [
                    {
                        "repository_id": repository_id,
                        "source_key": edge.source,
                        "target_key": edge.target,
                        "relation": edge.relation,
                        "metadata_json": edge.metadata,
                    }
                    for edge in graph.edges
                ],
            )
        if graph.chunks:
            connection.execute(
                insert(knowledge_chunks),
                [
                    {
                        "repository_id": repository_id,
                        "chunk_key": chunk.key,
                        "title": chunk.title,
                        "content": chunk.content,
                        "source_type": chunk.source_type,
                        "source_path": chunk.source_path,
                        "node_keys": chunk.node_keys,
                        "metadata_json": chunk.metadata,
                    }
                    for chunk in graph.chunks
                ],
            )

    def _record_sync_run(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        now = datetime.now(timezone.utc)
        connection.execute(
            insert(sync_runs).values(
                repository_id=repository_id,
                status="success",
                started_at=snapshot.synced_at,
                finished_at=now,
                summary={
                    "files": len(snapshot.files),
                    "issues": len(snapshot.issues),
                    "pull_requests": len(snapshot.pull_requests),
                    "commits": len(snapshot.recent_commits),
                },
            )
        )
