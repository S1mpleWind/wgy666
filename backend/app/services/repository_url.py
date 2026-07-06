"""GitHub repository URL parser.

Supports HTTPS URLs, git@ SSH URLs, and bare ``owner/name`` strings.
"""

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class RepositoryRef:
    """Parsed repository reference with owner and name components."""

    owner: str
    name: str


def parse_github_repository_url(value: str) -> RepositoryRef:
    """Parse a GitHub repository URL or identifier into ``RepositoryRef``.

    Accepts:
    - ``https://github.com/owner/name``
    - ``git@github.com:owner/name.git``
    - ``owner/name`` (bare format)
    """
    candidate = value.strip()
    if candidate.startswith("git@github.com:"):
        path = candidate.removeprefix("git@github.com:")
    elif "://" not in candidate and candidate.count("/") >= 1:
        path = candidate
    else:
        parsed = urlparse(candidate)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Only GitHub repository links are supported.")
        path = parsed.path

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("Expected a GitHub repository URL like https://github.com/owner/repo.")

    owner = parts[0]
    name = parts[1].removesuffix(".git")
    if not owner or not name:
        raise ValueError("Repository owner and name are required.")
    return RepositoryRef(owner=owner, name=name)
