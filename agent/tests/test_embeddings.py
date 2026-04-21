"""Tests for embedding backends."""

from app.config import config
from app.rag import embeddings as embeddings_module
from app.rag.embeddings import LocalHashEmbeddings


def test_local_hash_embeddings_are_deterministic():
    embeddings = LocalHashEmbeddings(dimensions=32)

    first = embeddings.embed_query("RAG retrieval benchmark")
    second = embeddings.embed_query("RAG retrieval benchmark")
    other = embeddings.embed_query("Completely different topic")

    assert len(first) == 32
    assert first == second
    assert first != other


def test_get_embeddings_supports_local_provider(monkeypatch):
    embeddings_module.get_embeddings.cache_clear()
    monkeypatch.setattr(config, "embedding_provider", "local")
    monkeypatch.setattr(config, "embedding_model", "local-hash-16")
    monkeypatch.setattr(config, "local_embedding_dimensions", 16)

    embeddings = embeddings_module.get_embeddings()
    vector = embeddings.embed_query("offline embedding")

    assert isinstance(embeddings, LocalHashEmbeddings)
    assert len(vector) == 16

    embeddings_module.get_embeddings.cache_clear()