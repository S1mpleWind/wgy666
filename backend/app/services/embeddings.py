"""Embedding service with remote + local fallback chain.

Priority:
1. Remote embedding API  (if EMBEDDING_API_KEY is configured)
2. Local sentence-transformers model  (if LOCAL_EMBEDDING_ENABLED=true)
3. Hash-based pseudo-vectors  (deterministic, dev-only, no semantics)
"""

from __future__ import annotations

import hashlib
import logging
import math
import re

from openai import OpenAI, OpenAIError

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Multi-backend embedding with automatic fallback."""

    _last_backend = "not_used"
    _last_error: str | None = None

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or settings.embedding_dimensions

    # -- Public API ----------------------------------------------------------

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # 1. Remote API
        if settings.embedding_api_key:
            try:
                vectors = self._remote_embeddings(texts)
                type(self)._last_backend = "remote"
                type(self)._last_error = None
                return vectors
            except (OpenAIError, TypeError, ValueError) as exc:
                type(self)._last_error = str(exc)
                logger.warning("Remote embedding failed; trying fallback: %s", exc)

        # 2. Local sentence-transformers model
        local = _get_local_service()
        if local is not None:
            try:
                vectors = local.embed(texts)
                type(self)._last_backend = "local"
                return vectors
            except Exception as exc:
                type(self)._last_error = str(exc)
                logger.warning("Local embedding failed; using hash fallback: %s", exc)

        # 3. Hash fallback (deterministic, no semantics — dev only)
        type(self)._last_backend = "hash_fallback"
        return [self._hash_embedding(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    # -- Backends ------------------------------------------------------------

    def _remote_embeddings(self, texts: list[str]) -> list[list[float]]:
        client = OpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_api_base_url)
        vectors: list[list[float]] = []
        batch_size = settings.embedding_batch_size
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            kwargs: dict = {"model": settings.embedding_model, "input": batch}
            if "text-embedding-3" in settings.embedding_model:
                kwargs["dimensions"] = self.dimensions
            response = client.embeddings.create(**kwargs)
            vectors.extend(item.embedding for item in response.data)
        if len(vectors) != len(texts):
            raise ValueError("Embedding response size does not match input size.")
        return vectors

    @classmethod
    def backend_status(cls) -> tuple[str, str | None]:
        return cls._last_backend, cls._last_error

    def _hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-zA-Z0-9_./-]+|[一-鿿]", text.lower())
        for token in tokens or [text[:64]]:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [round(value / norm, 8) for value in vector]


# ---------------------------------------------------------------------------
# Lazy local embedding singleton
# ---------------------------------------------------------------------------

_local_service: object | None = None
_local_failed: bool = False


def _get_local_service():
    """Return the cached ``LocalEmbeddingService`` singleton, or ``None``."""
    global _local_service, _local_failed

    if not settings.local_embedding_enabled:
        return None
    if _local_failed:
        return None
    if _local_service is not None:
        return _local_service

    try:
        from app.services.local_embedding import LocalEmbeddingService

        _local_service = LocalEmbeddingService()
    except ImportError:
        _local_failed = True
        return None

    return _local_service
