"""Qdrant vector store operations for QCVN/TCVN chunks."""

from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
)
import structlog

from src.core.config import get_settings
from src.embeddings.embedding_service import EMBEDDING_DIM

logger = structlog.get_logger()
settings = get_settings()

_client: Optional[QdrantClient] = None


def get_client() -> QdrantClient:
    """Get or create the Qdrant client (singleton)."""
    global _client
    if _client is None:
        _client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        logger.info("qdrant_connected", host=settings.qdrant_host)
    return _client


def ensure_collection(collection_name: str = None):
    """Create the collection if it doesn't exist.

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


def upsert_chunks(
    chunks: list[dict],
    embeddings: list[list[float]],
    collection_name: str = None,
):
    """Insert or update chunks with their embeddings into Qdrant.

    Args:
        chunks: List of chunk dicts with 'text' and 'metadata'.
        embeddings: Corresponding embedding vectors.
        collection_name: Override the default collection name.
    """
    name = collection_name or settings.qdrant_collection
    client = get_client()
    ensure_collection(name)

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        points.append(
            PointStruct(
                id=i,
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    **chunk.get("metadata", {}),
                },
            )
        )

    # Upsert in batches of 100
    batch_size = 100
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        client.upsert(collection_name=name, points=batch)

    logger.info("chunks_upserted", collection=name, count=len(points))


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


def upsert(embeddings: list, documents: list, collection_name: str = None):
    """Simplified upsert — wraps upsert_chunks for IFC/agent usage."""
    upsert_chunks(
        chunks=documents,
        embeddings=embeddings,
        collection_name=collection_name,
    )
