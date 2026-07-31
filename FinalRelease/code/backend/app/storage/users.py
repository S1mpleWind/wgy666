"""Database-backed user storage with authentication and per-user config."""

from datetime import datetime, timezone
from threading import RLock
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from app.core.security import hash_password, verify_password
from app.schemas.user import UsageStats, User, UserConfig, UserConfigUpdate, UserCreate, UserUpdate


class DuplicateEmailError(ValueError):
    """Raised when a user email is already registered."""


class UserStore:
    """Persistent user store backed by the ``users`` and ``user_configs`` tables.

    Falls back to an in-memory store when no engine is provided (e.g., when
    DATABASE_URL is not configured).
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine
        self._lock = RLock()
        # In-memory fallback when database is not configured
        self._users: dict[UUID, User] = {}
        self._email_index: dict[str, UUID] = {}
        self._password_hashes: dict[UUID, str] = {}
        self._configs: dict[UUID, UserConfig] = {}
        self._raw_configs: dict[UUID, dict] = {}
        self._usage: dict[UUID, UsageStats] = {}
        self._db_available = engine is not None

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def create_user(self, name: str, email: str, password: str, role: str = "user") -> User:
        """Create a new user with a hashed password."""
        from app.storage.database import users as users_table

        now = datetime.now(timezone.utc)
        user_id = uuid4()
        pw_hash = hash_password(password)

        if self._db_available and self._engine is not None:
            with self._lock:
                self._check_duplicate_email_db(email)
                with self._engine.begin() as conn:
                    conn.execute(
                        insert(users_table).values(
                            id=str(user_id),
                            name=name,
                            email=email,
                            password_hash=pw_hash,
                            role=role,
                            created_at=now,
                            updated_at=now,
                        )
                    )
        else:
            with self._lock:
                if email in self._email_index:
                    raise DuplicateEmailError(email)
                user = User(id=user_id, name=name, email=email, role=role, created_at=now, updated_at=now)
                self._users[user_id] = user
                self._email_index[email] = user_id
                self._password_hashes[user_id] = pw_hash

        return User(id=user_id, name=name, email=email, role=role, created_at=now, updated_at=now)

    def get_user(self, user_id: UUID) -> User | None:
        """Return a user by id, or None."""
        from app.storage.database import users as users_table

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(users_table).where(users_table.c.id == str(user_id))
                ).mappings().first()
            if row is None:
                return None
            return User(
                id=UUID(row["id"]),
                name=row["name"],
                email=row["email"],
                role=row.get("role", "user"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        else:
            with self._lock:
                return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> User | None:
        """Return a user by email, or None."""
        from app.storage.database import users as users_table

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(users_table).where(users_table.c.email == email)
                ).mappings().first()
            if row is None:
                return None
            return User(
                id=UUID(row["id"]),
                name=row["name"],
                email=row["email"],
                role=row.get("role", "user"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        else:
            with self._lock:
                user_id = self._email_index.get(email)
                if user_id is None:
                    return None
                return self._users.get(user_id)

    def list_users(self) -> list[User]:
        """Return all users sorted by creation time."""
        from app.storage.database import users as users_table

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(users_table).order_by(users_table.c.created_at)
                ).mappings().all()
            return [
                User(
                    id=UUID(row["id"]),
                    name=row["name"],
                    email=row["email"],
                    role=row.get("role", "user"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
        else:
            with self._lock:
                return sorted(self._users.values(), key=lambda u: u.created_at)

    def update_user(self, user_id: UUID, payload: UserUpdate) -> User | None:
        """Update user fields. Returns updated user or None if not found."""
        from app.storage.database import users as users_table

        changes: dict = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.email is not None:
            changes["email"] = payload.email
        if payload.password is not None:
            changes["password_hash"] = hash_password(payload.password)

        if not changes:
            return self.get_user(user_id)

        changes["updated_at"] = datetime.now(timezone.utc)

        if self._db_available and self._engine is not None:
            with self._lock:
                if "email" in changes:
                    self._check_duplicate_email_db(changes["email"], exclude_id=user_id)
                with self._engine.begin() as conn:
                    result = conn.execute(
                        update(users_table)
                        .where(users_table.c.id == str(user_id))
                        .values(**changes)
                    )
                    if result.rowcount == 0:
                        return None
        else:
            with self._lock:
                current = self._users.get(user_id)
                if current is None:
                    return None
                new_email = changes.get("email")
                existing_id = self._email_index.get(new_email) if new_email else None
                if existing_id is not None and existing_id != user_id:
                    raise DuplicateEmailError(new_email)
                updated_data = current.model_dump()
                updated_data.update(changes)
                updated = User(**updated_data)
                if "email" in changes and changes["email"] != current.email:
                    del self._email_index[current.email]
                    self._email_index[updated.email] = user_id
                self._users[user_id] = updated

        return self.get_user(user_id)

    def delete_user(self, user_id: UUID) -> bool:
        """Delete a user. Returns True if deleted, False if not found."""
        from app.storage.database import users as users_table

        if self._db_available and self._engine is not None:
            with self._engine.begin() as conn:
                result = conn.execute(
                    delete(users_table).where(users_table.c.id == str(user_id))
                )
                return result.rowcount > 0
        else:
            with self._lock:
                user = self._users.pop(user_id, None)
                if user is None:
                    return False
                del self._email_index[user.email]
                self._password_hashes.pop(user_id, None)
                self._configs.pop(user_id, None)
                self._raw_configs.pop(user_id, None)
                self._usage.pop(user_id, None)
                return True

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, email: str, password: str) -> User | None:
        """Verify credentials and return the user, or None."""
        from app.storage.database import users as users_table

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(users_table).where(users_table.c.email == email)
                ).mappings().first()
            if row is None:
                return None
            if not verify_password(password, row["password_hash"]):
                return None
            return User(
                id=UUID(row["id"]),
                name=row["name"],
                email=row["email"],
                role=row.get("role", "user"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        else:
            # In-memory mode: verify password against stored hash.
            with self._lock:
                user_id = self._email_index.get(email)
                if user_id is None:
                    return None
                stored_hash = self._password_hashes.get(user_id)
                if stored_hash is None:
                    return None
                if not verify_password(password, stored_hash):
                    return None
                return self._users.get(user_id)

    # ------------------------------------------------------------------
    # Per-User Config CRUD
    # ------------------------------------------------------------------

    def get_user_config(self, user_id: UUID) -> UserConfig | None:
        """Return the config for a user, or None."""
        from app.storage.database import user_configs as configs_table

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(configs_table).where(configs_table.c.user_id == str(user_id))
                ).mappings().first()
            if row is None:
                return None
            return UserConfig(
                llm_api_base_url=row["llm_api_base_url"],
                llm_model=row["llm_model"],
                llm_api_key_configured=bool(row["llm_api_key"]),
                github_token_configured=bool(row["github_token"]),
                github_webhook_secret_configured=bool(row["github_webhook_secret"]),
            )
        else:
            with self._lock:
                return self._configs.get(user_id)

    def upsert_user_config(self, user_id: UUID, payload: UserConfigUpdate) -> UserConfig:
        """Create or update the config for a user. Returns the public config."""
        from app.storage.database import user_configs as configs_table
        if self._db_available and self._engine is not None:
            with self._engine.begin() as conn:
                existing = conn.execute(
                    select(configs_table).where(configs_table.c.user_id == str(user_id))
                ).mappings().first()

                now = datetime.now(timezone.utc)

                if existing is None:
                    # Insert new config
                    base_url = (
                        payload.llm_api_base_url
                        if payload.llm_api_base_url is not None
                        else ""
                    )
                    model = (
                        payload.llm_model
                        if payload.llm_model is not None
                        else ""
                    )
                    conn.execute(
                        insert(configs_table).values(
                            user_id=str(user_id),
                            llm_api_base_url=base_url,
                            llm_model=model,
                            llm_api_key=payload.llm_api_key,
                            github_token=payload.github_token,
                            github_webhook_secret=payload.github_webhook_secret,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    # Update existing config
                    update_values: dict = {"updated_at": now}
                    if payload.llm_api_base_url is not None:
                        update_values["llm_api_base_url"] = payload.llm_api_base_url
                    if payload.llm_model is not None:
                        update_values["llm_model"] = payload.llm_model

                    if payload.clear_llm_api_key:
                        update_values["llm_api_key"] = None
                    elif payload.llm_api_key is not None:
                        update_values["llm_api_key"] = payload.llm_api_key

                    if payload.clear_github_token:
                        update_values["github_token"] = None
                    elif payload.github_token is not None:
                        update_values["github_token"] = payload.github_token

                    if payload.clear_github_webhook_secret:
                        update_values["github_webhook_secret"] = None
                    elif payload.github_webhook_secret is not None:
                        update_values["github_webhook_secret"] = payload.github_webhook_secret

                    conn.execute(
                        update(configs_table)
                        .where(configs_table.c.user_id == str(user_id))
                        .values(**update_values)
                    )

        else:
            # In-memory fallback
            with self._lock:
                now = datetime.now(timezone.utc)
                current_cfg = self._configs.get(user_id)
                base_url = (
                    payload.llm_api_base_url
                    if payload.llm_api_base_url is not None
                    else current_cfg.llm_api_base_url if current_cfg
                    else ""
                )
                model = (
                    payload.llm_model
                    if payload.llm_model is not None
                    else current_cfg.llm_model if current_cfg
                    else ""
                )
                current_raw = (
                    self._raw_configs.get(user_id) if hasattr(self, "_raw_configs") else None
                ) or {}
                api_key = (
                    None if payload.clear_llm_api_key
                    else payload.llm_api_key if payload.llm_api_key is not None
                    else current_raw.get("llm_api_key")
                )
                gh_token = (
                    None if payload.clear_github_token
                    else payload.github_token if payload.github_token is not None
                    else current_raw.get("github_token")
                )
                gh_secret = (
                    None if payload.clear_github_webhook_secret
                    else payload.github_webhook_secret if payload.github_webhook_secret is not None
                    else current_raw.get("github_webhook_secret")
                )
                self._raw_configs[user_id] = {
                    "llm_api_key": api_key,
                    "github_token": gh_token,
                    "github_webhook_secret": gh_secret,
                }
                self._configs[user_id] = UserConfig(
                    llm_api_base_url=base_url,
                    llm_model=model,
                    llm_api_key_configured=bool(api_key),
                    github_token_configured=bool(gh_token),
                    github_webhook_secret_configured=bool(gh_secret),
                )

        return self.get_user_config(user_id) or UserConfig(
            llm_api_base_url="",
            llm_model="",
            llm_api_key_configured=False,
            github_token_configured=False,
            github_webhook_secret_configured=False,
        )

    def _get_raw_config(self, user_id: UUID) -> dict | None:
        """Return the raw user config row including secret values. Internal use only."""
        from app.storage.database import user_configs as configs_table

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(configs_table).where(configs_table.c.user_id == str(user_id))
                ).mappings().first()
            return dict(row) if row else None
        else:
            with self._lock:
                return self._raw_configs.get(user_id)

    def record_usage(
        self,
        user_id: UUID,
        service: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> UsageStats:
        """Increment accumulated LLM or GitHub usage for a user."""
        from app.storage.database import integration_usage

        now = datetime.now(timezone.utc)
        llm_delta = 1 if service == "llm" else 0
        github_delta = 1 if service == "github" else 0
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total_tokens = max(0, int(total_tokens or prompt_tokens + completion_tokens))

        if self._db_available and self._engine is not None:
            with self._lock, self._engine.begin() as conn:
                row = conn.execute(
                    select(integration_usage).where(integration_usage.c.user_id == str(user_id))
                ).mappings().first()
                values = {
                    "llm_requests": int(row["llm_requests"] if row else 0) + llm_delta,
                    "github_requests": int(row["github_requests"] if row else 0) + github_delta,
                    "prompt_tokens": int(row["prompt_tokens"] if row else 0) + prompt_tokens,
                    "completion_tokens": int(row["completion_tokens"] if row else 0) + completion_tokens,
                    "total_tokens": int(row["total_tokens"] if row else 0) + total_tokens,
                    "updated_at": now,
                }
                if row is None:
                    conn.execute(insert(integration_usage).values(user_id=str(user_id), **values))
                else:
                    conn.execute(
                        update(integration_usage)
                        .where(integration_usage.c.user_id == str(user_id))
                        .values(**values)
                    )
        else:
            with self._lock:
                current = self._usage.get(user_id, UsageStats())
                self._usage[user_id] = UsageStats(
                    llm_requests=current.llm_requests + llm_delta,
                    github_requests=current.github_requests + github_delta,
                    prompt_tokens=current.prompt_tokens + prompt_tokens,
                    completion_tokens=current.completion_tokens + completion_tokens,
                    total_tokens=current.total_tokens + total_tokens,
                    updated_at=now,
                )
        return self.get_usage(user_id)

    def get_usage(self, user_id: UUID) -> UsageStats:
        """Return accumulated integration usage for a user."""
        from app.storage.database import integration_usage

        if self._db_available and self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(integration_usage).where(integration_usage.c.user_id == str(user_id))
                ).mappings().first()
            if row is None:
                return UsageStats()
            return UsageStats(
                llm_requests=row["llm_requests"],
                github_requests=row["github_requests"],
                prompt_tokens=row["prompt_tokens"],
                completion_tokens=row["completion_tokens"],
                total_tokens=row["total_tokens"],
                updated_at=row["updated_at"],
            )
        with self._lock:
            return self._usage.get(user_id, UsageStats())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_duplicate_email_db(self, email: str, exclude_id: UUID | None = None) -> None:
        """Raise DuplicateEmailError if email already exists in DB."""
        from app.storage.database import users as users_table

        if self._engine is None:
            return
        with self._engine.connect() as conn:
            stmt = select(users_table).where(users_table.c.email == email)
            if exclude_id is not None:
                stmt = stmt.where(users_table.c.id != str(exclude_id))
            existing = conn.execute(stmt).first()
            if existing is not None:
                raise DuplicateEmailError(email)

    def clear(self) -> None:
        """Remove all users and configs; intended for isolated tests."""
        with self._lock:
            self._users.clear()
            self._email_index.clear()
            self._password_hashes.clear()
            self._configs.clear()
            self._raw_configs.clear()
            self._usage.clear()


# ------------------------------------------------------------------
# Singleton — lazily initialized with engine from settings
# ------------------------------------------------------------------

_user_store: UserStore | None = None


# Default admin credentials (change in production via DB or environment)
DEFAULT_ADMIN_EMAIL = "admin@issuescope.local"
DEFAULT_ADMIN_PASSWORD = "admin123456"
DEFAULT_ADMIN_NAME = "Admin"


def _seed_admin(store: UserStore) -> None:
    """Ensure an initial admin user exists in the database."""
    try:
        existing = store.get_user_by_email(DEFAULT_ADMIN_EMAIL)
        if existing is None:
            store.create_user(
                name=DEFAULT_ADMIN_NAME,
                email=DEFAULT_ADMIN_EMAIL,
                password=DEFAULT_ADMIN_PASSWORD,
                role="admin",
            )
    except Exception:
        pass  # Don't crash app startup if seeding fails


def get_user_store() -> UserStore:
    """Return the singleton UserStore, creating it on first call."""
    global _user_store
    if _user_store is None:
        from app.core.config import settings
        from app.storage.database import create_database_engine, initialize_database

        if settings.database_url:
            try:
                engine = create_database_engine()
                initialize_database(engine)
                _user_store = UserStore(engine)
                _seed_admin(_user_store)
                return _user_store
            except Exception:
                pass  # fall back to in-memory
        _user_store = UserStore()
        _seed_admin(_user_store)
    return _user_store


def reset_user_store() -> None:
    """Reset the singleton (used in tests)."""
    global _user_store
    _user_store = None
