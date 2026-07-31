"""Tests for the embedding service (hash fallback, no API key needed)."""

from app.services.embeddings import EmbeddingService


def test_hash_embedding_returns_deterministic_vector():
    """Same text produces the same embedding vector."""
    service = EmbeddingService(dimensions=8)
    vec_a = service.embed_query("hello world")
    vec_b = service.embed_query("hello world")
    assert vec_a == vec_b
    assert len(vec_a) == 8


def test_hash_embedding_different_texts_differ():
    """Different texts produce different embedding vectors."""
    service = EmbeddingService(dimensions=8)
    vec_a = service.embed_query("database configuration")
    vec_b = service.embed_query("test runner setup")
    assert vec_a != vec_b


def test_hash_embedding_unit_vector():
    """Hash embedding returns a unit vector (normalized)."""
    service = EmbeddingService(dimensions=1536)
    vec = service.embed_query("some source code content")
    magnitude = sum(v * v for v in vec) ** 0.5
    assert abs(magnitude - 1.0) < 1e-6


def test_embed_texts_empty():
    """Empty input returns empty list."""
    service = EmbeddingService()
    result = service.embed_texts([])
    assert result == []
    assert len(result) == 0


def test_embed_texts_multiple():
    """Multiple texts return multiple vectors."""
    service = EmbeddingService(dimensions=4)
    results = service.embed_texts(["first", "second", "third"])
    assert len(results) == 3
    assert all(len(vec) == 4 for vec in results)
