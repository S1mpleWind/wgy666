"""PostgreSQL-backed repository snapshot store."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.engine import Engine

from app.schemas.repository import RepositoryListItem, RepositorySnapshot
from app.services.embeddings import EmbeddingService
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
    repository_file_contents,
    repository_files,
    repository_snapshots,
    sync_runs,
)

logger = logging.getLogger(__name__)


class PostgresRepositoryStore:
    """Persist synced repositories in PostgreSQL.

    The store writes both a faithful snapshot JSON and normalized core tables.
    Current API reads reconstruct snapshots from JSON for compatibility; later
    RAG and analytics features can query the normalized tables directly.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or create_database_engine()
        self._broken = False
        try:
            initialize_database(self.engine)
        except Exception as exc:
            self._broken = True
            logger.exception("Database initialization failed: %s", exc)

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
            self._replace_file_contents(connection, repository_id, snapshot)
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

    def _replace_file_contents(self, connection, repository_id: int, snapshot: RepositorySnapshot) -> None:
        connection.execute(
            delete(repository_file_contents).where(
                repository_file_contents.c.repository_id == repository_id
            )
        )
        if not snapshot.source_contents:
            return
        connection.execute(
            insert(repository_file_contents),
            [
                {
                    "repository_id": repository_id,
                    "path": content.path,
                    "category": content.category.value,
                    "content": content.content,
                    "size": content.size,
                    "truncated": content.truncated,
                    "synced_at": snapshot.synced_at,
                }
                for content in snapshot.source_contents
            ],
        )

    def get_file_contents(self, owner: str, name: str, path: str | None = None) -> list[dict]:
        """Return file contents for a repository, optionally filtered by path."""
        repo_subquery = (
            select(repositories.c.id)
            .where(repositories.c.owner == owner, repositories.c.name == name)
            .scalar_subquery()
        )
        statement = select(
            repository_file_contents.c.id,
            repository_file_contents.c.path,
            repository_file_contents.c.category,
            repository_file_contents.c.content,
            repository_file_contents.c.size,
            repository_file_contents.c.truncated,
            repository_file_contents.c.synced_at,
        ).where(repository_file_contents.c.repository_id == repo_subquery)

        if path:
            statement = statement.where(repository_file_contents.c.path == path)

        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    def get_file_content(self, owner: str, name: str, path: str) -> dict | None:
        """Return the content of a single file by path."""
        results = self.get_file_contents(owner, name, path)
        return results[0] if results else None

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

        is_postgres = connection.dialect.name == "postgresql"

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
            if is_postgres:
                embeddings = EmbeddingService().embed_texts([chunk.content for chunk in graph.chunks])
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
                            "embedding": self._vector_literal(embedding),
                        }
                        for chunk, embedding in zip(graph.chunks, embeddings, strict=True)
                    ],
                )
            else:
                # SQLite — insert without embedding column.
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

    def search_knowledge(self, owner: str, name: str, query: str, limit: int = 5) -> list[dict]:
        with self.engine.connect() as connection:
            is_postgres = connection.dialect.name == "postgresql"

        if is_postgres:
            return self._search_knowledge_pgvector(owner, name, query, limit)

        # SQLite fallback — use keyword matching.
        from app.services.knowledge_graph import KnowledgeGraphService
        from app.storage import repository_store as mem_store
        snapshot = mem_store.get(owner, name)
        if snapshot is None:
            return []
        results = KnowledgeGraphService().search(snapshot, query=query, limit=limit)
        return [
            {
                "chunk_key": r.chunk.key,
                "title": r.chunk.title,
                "content": r.chunk.content,
                "source_type": r.chunk.source_type,
                "source_path": r.chunk.source_path,
                "node_keys": r.chunk.node_keys,
                "metadata_json": r.chunk.metadata,
                "score": float(r.score),
            }
            for r in results
        ]

    def _search_knowledge_pgvector(self, owner: str, name: str, query: str, limit: int = 5) -> list[dict]:
        embedding = self._vector_literal(EmbeddingService().embed_query(query))
        statement = text(
            """
            SELECT
                kc.chunk_key,
                kc.title,
                kc.content,
                kc.source_type,
                kc.source_path,
                kc.node_keys,
                kc.metadata_json,
                1 - (kc.embedding <=> CAST(:embedding AS vector)) AS score
            FROM knowledge_chunks kc
            JOIN repositories r ON r.id = kc.repository_id
            WHERE r.owner = :owner
              AND r.name = :name
              AND kc.embedding IS NOT NULL
            ORDER BY kc.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                statement,
                {"owner": owner, "name": name, "embedding": embedding, "limit": limit},
            ).mappings().all()
        return [dict(row) for row in rows]

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"

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
