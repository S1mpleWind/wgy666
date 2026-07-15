"""SQLAlchemy table definitions and database bootstrap."""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from typing import Any

from sqlalchemy.types import UserDefinedType
from sqlalchemy.engine import Engine

from app.core.config import settings

class VectorType(UserDefinedType):
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"


metadata = MetaData()

repositories = Table(
    "repositories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("owner", String(255), nullable=False),
    Column("name", String(255), nullable=False),
    Column("full_name", String(512), nullable=False, unique=True),
    Column("html_url", Text, nullable=False),
    Column("default_branch", String(255), nullable=False),
    Column("description", Text),
    Column("primary_language", String(255)),
    Column("stars", Integer, nullable=False, default=0),
    Column("forks", Integer, nullable=False, default=0),
    Column("watchers", Integer, nullable=False, default=0),
    Column("open_issues", Integer, nullable=False, default=0),
    Column("size_kb", Integer, nullable=False, default=0),
    Column("languages", JSON, nullable=False, default=dict),
    Column("topics", JSON, nullable=False, default=list),
    Column("synced_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("owner", "name", name="uq_repositories_owner_name"),
)

repository_snapshots = Table(
    "repository_snapshots",
    metadata,
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True),
    Column("snapshot", JSON, nullable=False),
    Column("synced_at", DateTime(timezone=True), nullable=False),
)

repository_files = Table(
    "repository_files",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),
    Column("category", String(64), nullable=False),
    Column("size", BigInteger),
    UniqueConstraint("repository_id", "path", name="uq_repository_files_repo_path"),
)

repository_file_contents = Table(
    "repository_file_contents",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),
    Column("category", String(64), nullable=False),
    Column("content", Text, nullable=False),
    Column("size", BigInteger),
    Column("truncated", Boolean, nullable=False, default=False),
    Column("synced_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("repository_id", "path", name="uq_repository_file_contents_repo_path"),
)

issues = Table(
    "issues",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("title", Text, nullable=False),
    Column("state", String(64), nullable=False),
    Column("html_url", Text, nullable=False),
    Column("author", String(255)),
    Column("labels", JSON, nullable=False, default=list),
    Column("comments", Integer, nullable=False, default=0),
    Column("classification_category", String(64), nullable=False),
    Column("classification_confidence", Integer, nullable=False),
    Column("classification", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("repository_id", "number", name="uq_issues_repo_number"),
)

pull_requests = Table(
    "pull_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("title", Text, nullable=False),
    Column("state", String(64), nullable=False),
    Column("html_url", Text, nullable=False),
    Column("author", String(255)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("repository_id", "number", name="uq_pull_requests_repo_number"),
)

commits = Table(
    "commits",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("sha", String(64), nullable=False),
    Column("message", Text, nullable=False),
    Column("author", String(255)),
    Column("html_url", Text),
    Column("committed_at", DateTime(timezone=True)),
    UniqueConstraint("repository_id", "sha", name="uq_commits_repo_sha"),
)

sync_runs = Table(
    "sync_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(64), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("summary", JSON, nullable=False, default=dict),
)


knowledge_nodes = Table(
    "knowledge_nodes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("node_key", String(512), nullable=False),
    Column("node_type", String(128), nullable=False),
    Column("name", Text, nullable=False),
    Column("path", Text),
    Column("summary", Text, nullable=False),
    Column("metadata_json", JSON, nullable=False, default=dict),
    UniqueConstraint("repository_id", "node_key", name="uq_knowledge_nodes_repo_key"),
)

knowledge_edges = Table(
    "knowledge_edges",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("source_key", String(512), nullable=False),
    Column("target_key", String(512), nullable=False),
    Column("relation", String(128), nullable=False),
    Column("metadata_json", JSON, nullable=False, default=dict),
)

knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
    Column("chunk_key", String(512), nullable=False),
    Column("title", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("source_type", String(128), nullable=False),
    Column("source_path", Text),
    Column("node_keys", JSON, nullable=False, default=list),
    Column("metadata_json", JSON, nullable=False, default=dict),
    Column("embedding", VectorType(settings.embedding_dimensions)),
    UniqueConstraint("repository_id", "chunk_key", name="uq_knowledge_chunks_repo_key"),
)


def create_database_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    kwargs: dict[str, Any] = {
        "future": True,
    }
    if settings.database_url.startswith("postgresql"):
        kwargs["pool_pre_ping"] = True
        kwargs["connect_args"] = {"connect_timeout": 10}
    elif settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.database_url, **kwargs)


def initialize_database(engine: Engine) -> None:
    """Create all tables. Enables pgvector only when connected to PostgreSQL."""
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "postgresql":
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            metadata.create_all(connection)
            connection.execute(text(
                f"ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS "
                f"embedding vector({settings.embedding_dimensions})"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding "
                "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops)"
            ))
        else:
            # SQLite or other dialects — create tables without vector extensions.
            metadata.create_all(connection)
