"""Qdrant writes (src/embeddings/vector_store.py) against an in-memory Qdrant."""

import pytest
from qdrant_client import QdrantClient

from src.embeddings import vector_store
from src.embeddings.embedding_service import EMBEDDING_DIM

COLLECTION = "test_chunks"


@pytest.fixture
def qdrant(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    return client


def vec(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i % EMBEDDING_DIM] = 1.0
    return v


def chunks(source: str, n: int, prefix: str = "chunk") -> list[dict]:
    return [{"text": f"{prefix} {source} {i}", "metadata": {"source_id": source, "i": i}} for i in range(n)]


def count(client, source=None) -> int:
    points, _ = client.scroll(COLLECTION, limit=10_000, with_payload=True)
    return len([p for p in points if source is None or p.payload.get("source_id") == source])


def upsert(items, **kw):
    vector_store.upsert_chunks(items, [vec(i) for i in range(len(items))], collection_name=COLLECTION, **kw)


class TestSources:
    def test_two_ifc_files_do_not_overwrite_each_other(self, qdrant):
        """Regression: ids used to be 0..n-1 for every upload, so file B replaced file A."""
        vector_store.upsert([vec(i) for i in range(3)], chunks("x", 3), COLLECTION, source_id="ifc:a.ifc")
        vector_store.upsert([vec(i) for i in range(2)], chunks("y", 2), COLLECTION, source_id="ifc:b.ifc")
        assert count(qdrant, "ifc:a.ifc") == 3
        assert count(qdrant, "ifc:b.ifc") == 2

    def test_reupsert_replaces_a_source_without_leftovers(self, qdrant):
        upsert(chunks("std-1", 5))
        upsert(chunks("std-2", 2))
        upsert(chunks("std-1", 3, prefix="v2"))
        assert count(qdrant, "std-1") == 3
        assert count(qdrant, "std-2") == 2
        texts = {p.payload["text"] for p in qdrant.scroll(COLLECTION, limit=100)[0] if p.payload["source_id"] == "std-1"}
        assert all(t.startswith("v2") for t in texts)

    def test_ids_are_deterministic(self, qdrant):
        upsert(chunks("std-1", 2))
        first = sorted(str(p.id) for p in qdrant.scroll(COLLECTION, limit=10)[0])
        upsert(chunks("std-1", 2))
        assert sorted(str(p.id) for p in qdrant.scroll(COLLECTION, limit=10)[0]) == first
        assert vector_store.point_id(COLLECTION, "std-1", 0, {}) in first

    def test_chunks_without_source_are_idempotent(self, qdrant):
        items = [{"text": "mẫu 1", "metadata": {"standard_code": "X"}}, {"text": "mẫu 2", "metadata": {"standard_code": "X"}}]
        upsert(items)
        upsert(items)
        assert count(qdrant) == 2

    def test_prune_keeps_only_listed_sources(self, qdrant):
        upsert(chunks("keep", 2))
        upsert(chunks("old", 2))
        upsert([{"text": "sample without source", "metadata": {}}])
        vector_store.prune_sources({"keep"}, COLLECTION)
        assert count(qdrant) == 2 and count(qdrant, "keep") == 2


def test_search_returns_payload_without_text_in_metadata(qdrant):
    upsert(chunks("std-1", 3))
    hits = vector_store.search(vec(1), top_k=1, collection_name=COLLECTION)
    assert hits[0]["text"] == "chunk std-1 1"
    assert hits[0]["metadata"]["source_id"] == "std-1"
    assert "text" not in hits[0]["metadata"]
