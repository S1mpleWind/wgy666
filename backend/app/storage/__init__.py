"""Storage adapter selection.

The app uses PostgreSQL when ``DATABASE_URL`` is configured. Tests and very
lightweight local development can omit it to fall back to the in-memory store.
"""

from app.core.config import settings
from app.storage.memory import InMemoryRepositoryStore


def create_repository_store():
    if settings.database_url:
        from app.storage.postgres import PostgresRepositoryStore

        return PostgresRepositoryStore()
    return InMemoryRepositoryStore()


repository_store = create_repository_store()
