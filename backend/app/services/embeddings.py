from __future__ import annotations

import hashlib
import math
import re

from openai import OpenAI, OpenAIError

from app.core.config import settings


class EmbeddingService:
    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or settings.embedding_dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if settings.embedding_api_key:
            try:
                return self._remote_embeddings(texts)
            except (OpenAIError, TypeError, ValueError):
                pass
        return [self._hash_embedding(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _remote_embeddings(self, texts: list[str]) -> list[list[float]]:
        client = OpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_api_base_url)
        kwargs = {"model": settings.embedding_model, "input": texts}
        if "text-embedding-3" in settings.embedding_model:
            kwargs["dimensions"] = self.dimensions
        response = client.embeddings.create(**kwargs)
        vectors = [item.embedding for item in response.data]
        if len(vectors) != len(texts):
            raise ValueError("Embedding response size does not match input size.")
        return vectors

    def _hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-zA-Z0-9_./-]+|[\u4e00-\u9fff]", text.lower())
        for token in tokens or [text[:64]]:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [round(value / norm, 8) for value in vector]
