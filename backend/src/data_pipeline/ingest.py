"""Ingestion pipeline for QCVN/TCVN standards: chunk, embed, upsert to Qdrant."""

from pathlib import Path
import os
import structlog

from src.data_pipeline.chunker import chunk_from_json_file
from src.embeddings.embedding_service import embed_texts
from src.embeddings.vector_store import (
    ensure_collection,
    prune_sources,
    upsert_chunks,
)

logger = structlog.get_logger()


def chunk_json_dir(json_dir: Path) -> list[dict]:
    """Chunk all standard JSON files in a directory (files starting with '_' are reports)."""
    p = Path(json_dir)
    if not p.is_dir():
        logger.warning("chunk_json_dir_not_found", directory=str(p))
        return []
    json_files = sorted(f for f in os.listdir(p) if f.endswith(".json") and not f.startswith("_"))
    all_chunks: list[dict] = []
    for filename in json_files:
        filepath = p / filename
        chunks = chunk_from_json_file(str(filepath))
        all_chunks.extend(chunks)
    logger.info("chunk_json_dir_complete", directory=str(p), files=len(json_files), chunks=len(all_chunks))
    return all_chunks


def embed_and_upsert(chunks: list[dict], batch_size: int = 256) -> None:
    """Embed chunks in batches and upsert to Qdrant."""
    if not chunks:
        return
    texts = [c["text"] for c in chunks]
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        all_embeddings.extend(embed_texts(batch_texts))
    upsert_chunks(chunks, all_embeddings)
    logger.info("embed_and_upsert_complete", chunks=len(chunks), embeddings=len(all_embeddings))


def ingest_json_dir(json_dir: Path, prune: bool = True) -> dict[str, int]:
    """Ensure vector collection, chunk standard JSON files, embed and upsert, and optionally prune.

    Args:
        json_dir: Directory containing parsed standard JSON files.
        prune: Whether to remove sources not present in this run.

    Returns:
        Summary dict {"chunks": int, "sources": int}.

    Raises:
        ValueError: If no chunks are found in the directory.
    """
    json_dir = Path(json_dir)
    ensure_collection()
    chunks = chunk_json_dir(json_dir)
    if not chunks:
        raise ValueError(f"No chunks found in {json_dir}")

    embed_and_upsert(chunks)

    sources = {c["metadata"]["source_id"] for c in chunks}
    if prune:
        prune_sources(sources)

    logger.info("ingest_json_dir_complete", directory=str(json_dir), chunks=len(chunks), sources=len(sources), prune=prune)
    return {"chunks": len(chunks), "sources": len(sources)}
