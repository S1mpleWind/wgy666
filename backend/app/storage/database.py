"""SQLAlchemy table definitions and database bootstrap."""

from sqlalchemy import (
    JSON,
    BigInteger,
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
from sqlalchemy.engine import Engine

from app.core.config import settings

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


def create_database_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": 10},
    )


def initialize_database(engine: Engine) -> None:
    """Create tables and enable pgvector for future RAG usage."""
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        metadata.create_all(connection)
