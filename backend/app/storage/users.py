"""Thread-safe in-memory user storage."""

from datetime import datetime, timezone
from threading import RLock
from uuid import UUID, uuid4

from app.schemas.user import User, UserCreate, UserUpdate


class DuplicateEmailError(ValueError):
    """Raised when a user email is already registered."""


class InMemoryUserStore:
    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}
        self._email_index: dict[str, UUID] = {}
        self._lock = RLock()

    def create(self, payload: UserCreate) -> User:
        with self._lock:
            if payload.email in self._email_index:
                raise DuplicateEmailError(payload.email)
            now = datetime.now(timezone.utc)
            user = User(id=uuid4(), **payload.model_dump(), created_at=now, updated_at=now)
            self._users[user.id] = user
            self._email_index[user.email] = user.id
            return user

    def list(self) -> list[User]:
        with self._lock:
            return sorted(self._users.values(), key=lambda user: user.created_at)

    def get(self, user_id: UUID) -> User | None:
        with self._lock:
            return self._users.get(user_id)

    def update(self, user_id: UUID, payload: UserUpdate) -> User | None:
        with self._lock:
            current = self._users.get(user_id)
            if current is None:
                return None
            changes = payload.model_dump(exclude_none=True)
            new_email = changes.get("email")
            existing_id = self._email_index.get(new_email) if new_email else None
            if existing_id is not None and existing_id != user_id:
                raise DuplicateEmailError(new_email)
            updated = current.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})
            if updated.email != current.email:
                del self._email_index[current.email]
                self._email_index[updated.email] = user_id
            self._users[user_id] = updated
            return updated

    def delete(self, user_id: UUID) -> bool:
        with self._lock:
            user = self._users.pop(user_id, None)
            if user is None:
                return False
            del self._email_index[user.email]
            return True

    def clear(self) -> None:
        """Remove all users; intended for isolated tests."""
        with self._lock:
            self._users.clear()
            self._email_index.clear()


user_store = InMemoryUserStore()
