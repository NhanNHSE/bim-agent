"""Qdrant vector store operations for QCVN/TCVN chunks.

Point ids are deterministic (UUID5) and every point carries a `source_id` payload (one
regulation, one IFC file, ...). Upserting a source first deletes that source's old points, so
re-ingesting replaces instead of piling up stale points, and two sources never overwrite each
other (the old `id=i` scheme made every IFC upload overwrite the previous model's vectors).
"""

import json
import uuid
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
)
import structlog

from src.core.config import get_settings
from src.embeddings.embedding_service import EMBEDDING_DIM

logger = structlog.get_logger()
settings = get_settings()

_client: Optional[QdrantClient] = None

# Fixed namespace: the same (collection, source, position) always maps to the same point id
_ID_NAMESPACE = uuid.UUID("6f0d7c1e-3b0a-5f4e-9a51-7c2b1d9e4a10")


def get_client() -> QdrantClient:
    """Get or create the Qdrant client (singleton)."""
    global _client
    if _client is None:
        # Creating a collection / bulk upserts can exceed the 5 s client default on slow disks
        # (observed 9 s inside WSL2); a timeout there left the collection half-initialised.
        _client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, timeout=60)
        logger.info("qdrant_connected", host=settings.qdrant_host)
    return _client


def ensure_collection(collection_name: str = None):
    """Create the collection (and its `source_id` payload index) if it doesn't exist.

    Args:
        collection_name: Override the default collection name.
    """
    name = collection_name or settings.qdrant_collection
    client = get_client()

    collections = [c.name for c in client.get_collections().collections]
    if name not in collections:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
        logger.info("collection_created", name=name, dim=EMBEDDING_DIM)
    else:
        logger.info("collection_exists", name=name)
    try:
        client.create_payload_index(name, field_name="source_id", field_schema=PayloadSchemaType.KEYWORD)
    except Exception as e:  # already indexed, or a client mode without payload indexes
        logger.debug("payload_index_skipped", collection=name, error=str(e))


def point_id(collection: str, source_id: Optional[str], index: int, chunk: dict) -> str:
    """Deterministic point id: by (source, position) when the source is known, else by content."""
    if source_id:
        key = f"{collection}|{source_id}|{index}"
    else:
        key = f"{collection}|{chunk.get('text', '')}|{json.dumps(chunk.get('metadata', {}), sort_keys=True, ensure_ascii=False, default=str)}"
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def delete_source(source_id: str, collection_name: str = None) -> None:
    """Delete every point of one source (regulation, IFC file, ...)."""
    name = collection_name or settings.qdrant_collection
    get_client().delete(
        collection_name=name,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
        ),
    )
    logger.info("source_deleted", collection=name, source_id=source_id)


def prune_sources(keep: set[str], collection_name: str = None) -> None:
    """Delete every point whose source is not in `keep` (also points without a source_id,
    e.g. sample data or vectors written before source ids existed)."""
    name = collection_name or settings.qdrant_collection
    get_client().delete(
        collection_name=name,
        points_selector=FilterSelector(
            filter=Filter(must_not=[FieldCondition(key="source_id", match=MatchAny(any=sorted(keep)))])
        ),
    )
    logger.info("sources_pruned", collection=name, kept=len(keep))


def upsert_chunks(
    chunks: list[dict],
    embeddings: list[list[float]],
    collection_name: str = None,
    source_id: Optional[str] = None,
    replace: bool = True,
):
    """Insert or replace chunks with their embeddings in Qdrant.

    Args:
        chunks: List of chunk dicts with 'text' and 'metadata'.
        embeddings: Corresponding embedding vectors.
        collection_name: Override the default collection name.
        source_id: Source of all chunks; otherwise each chunk's `metadata["source_id"]` is used.
        replace: Delete the existing points of each source before inserting (default).
    """
    name = collection_name or settings.qdrant_collection
    client = get_client()
    ensure_collection(name)

    sources = [source_id or chunk.get("metadata", {}).get("source_id") for chunk in chunks]
    if replace:
        for sid in dict.fromkeys(s for s in sources if s):
            delete_source(sid, name)

    positions: dict[Optional[str], int] = {}
    points = []
    for chunk, embedding, sid in zip(chunks, embeddings, sources):
        index = positions.get(sid, 0)
        positions[sid] = index + 1
        payload = {"text": chunk["text"], **chunk.get("metadata", {})}
        if sid:
            payload["source_id"] = sid
        points.append(PointStruct(id=point_id(name, sid, index, chunk), vector=embedding, payload=payload))

    # Upsert in batches of 100
    batch_size = 100
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        client.upsert(collection_name=name, points=batch)

    logger.info("chunks_upserted", collection=name, count=len(points), sources=len(positions))


def search(
    query_embedding: list[float],
    top_k: int = 10,
    collection_name: str = None,
    standard_code: str = None,
) -> list[dict[str, Any]]:
    """Search for similar chunks in Qdrant.

    Args:
        query_embedding: Query vector.
        top_k: Number of results.
        collection_name: Override the default collection name.
        standard_code: Optional filter by standard code.

    Returns:
        List of matching documents with scores.
    """
    name = collection_name or settings.qdrant_collection
    client = get_client()

    query_filter = None
    if standard_code:
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="standard_code",
                    match=MatchValue(value=standard_code),
                )
            ]
        )

    try:
        results = client.search(
            collection_name=name,
            query_vector=query_embedding,
            query_filter=query_filter,
            limit=top_k,
        )
    except Exception as e:
        error_msg = str(e)
        if "doesn't exist" in error_msg or "not found" in error_msg.lower():
            logger.warning("collection_not_found", collection=name,
                           hint="Run ingest script to populate data")
            return []
        raise

    documents = []
    for hit in results:
        doc = {
            "text": hit.payload.get("text", ""),
            "score": hit.score,
            "metadata": {
                k: v for k, v in hit.payload.items() if k != "text"
            },
        }
        documents.append(doc)

    return documents


def get_collection_info(collection_name: str = None) -> dict:
    """Get collection statistics."""
    name = collection_name or settings.qdrant_collection
    client = get_client()
    try:
        info = client.get_collection(name)
        return {
            "name": name,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "status": info.status.value,
        }
    except Exception:
        return {"name": name, "status": "not_found"}


def upsert(embeddings: list, documents: list, collection_name: str = None, source_id: Optional[str] = None):
    """Simplified upsert — wraps upsert_chunks for IFC/agent usage (`source_id` = one IFC file)."""
    upsert_chunks(
        chunks=documents,
        embeddings=embeddings,
        collection_name=collection_name,
        source_id=source_id,
    )
