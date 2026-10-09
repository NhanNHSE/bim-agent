"""Ingest QCVN/TCVN data into the Qdrant vector store.

Default source is the real regulations crawled from vbpl.vn (scripts/crawl_vbpl_bxd.py):
data/vbpl_bxd is parsed into data/vbpl_bxd/parsed/*.json (one file per regulation), chunked,
embedded and upserted. Each regulation replaces its own previous vectors, and vectors of
sources that are no longer in the corpus (e.g. old sample data) are removed.

Usage:
    # Real data (crawl first if data/vbpl_bxd/catalog.json is missing)
    docker exec bim-backend python scripts/ingest_qcvn.py

    # Hand-written sample data (dev / demo only)
    docker exec bim-backend python scripts/ingest_qcvn.py --sample

    # Existing JSON files, or arbitrary PDFs
    docker exec bim-backend python scripts/ingest_qcvn.py --json-dir data/vbpl_bxd/parsed --skip-parse
    docker exec bim-backend python scripts/ingest_qcvn.py --pdf path/to/QCVN.pdf

    # Start from an empty collection (after changing the embedding model)
    docker exec bim-backend python scripts/ingest_qcvn.py --recreate
"""

import argparse
import json
import os
import sys
from pathlib import Path

from src.data_pipeline.chunker import chunk_from_json_file
from src.embeddings.embedding_service import embed_texts
from src.embeddings.vector_store import (
    ensure_collection,
    get_client,
    get_collection_info,
    prune_sources,
    upsert_chunks,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
VBPL_DIR = DATA_DIR / "vbpl_bxd"
PARSED_DIR = VBPL_DIR / "parsed"
SAMPLE_DIR = DATA_DIR / "qcvn"


def chunk_json_dir(data_dir: Path) -> list[dict]:
    """Chunk all standard JSON files in a directory (files starting with "_" are reports)."""
    json_files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json") and not f.startswith("_"))
    print(f"\n✂️  Chunking {len(json_files)} JSON files from {data_dir}...")
    all_chunks = []
    for filename in json_files:
        chunks = chunk_from_json_file(str(data_dir / filename))
        all_chunks.extend(chunks)
    print(f"  📋 {len(all_chunks)} chunks")
    return all_chunks


def embed_and_upsert(chunks: list[dict]):
    """Embed chunks and upsert to Qdrant (each source replaces its previous vectors)."""
    print(f"\n🧮 Embedding {len(chunks)} chunks...")
    texts = [c["text"] for c in chunks]
    batch_size = 256
    all_embeddings = []
    total_batches = (len(texts) - 1) // batch_size + 1
    for i in range(0, len(texts), batch_size):
        all_embeddings.extend(embed_texts(texts[i:i + batch_size]))
        print(f"  ✅ Embedded batch {i // batch_size + 1}/{total_batches}")

    print(f"\n📥 Upserting {len(all_embeddings)} vectors into Qdrant...")
    upsert_chunks(chunks, all_embeddings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest QCVN/TCVN data into Qdrant")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--sample", action="store_true", help="Use hand-written sample data (data/qcvn)")
    source.add_argument("--json-dir", type=Path, help="Ingest existing standard JSON files")
    source.add_argument("--pdf", type=Path, help="Parse and ingest a single PDF")
    source.add_argument("--pdf-dir", type=Path, help="Parse and ingest every PDF in a directory")
    parser.add_argument("--skip-parse", action="store_true", help="Reuse data/vbpl_bxd/parsed as is")
    parser.add_argument("--recreate", action="store_true", help="Drop the collection first")
    parser.add_argument("--no-prune", action="store_true",
                        help="Keep vectors of sources that are not part of this run")
    args = parser.parse_args()

    print("=" * 60)
    print("🏗️  BIM AI Agent — QCVN Data Ingestion")
    print("=" * 60)

    prune = not args.no_prune
    if args.sample:
        from src.data_pipeline.sample_data_generator import generate_sample_data

        if not SAMPLE_DIR.exists() or not any(SAMPLE_DIR.glob("*.json")):
            generate_sample_data(str(SAMPLE_DIR))
        chunks = chunk_json_dir(SAMPLE_DIR)
    elif args.json_dir:
        chunks = chunk_json_dir(args.json_dir)
    elif args.pdf or args.pdf_dir:
        from src.data_pipeline.qcvn_parser import parse_directory, parse_pdf_to_json

        out = DATA_DIR / "pdf_parsed"
        if args.pdf:
            parse_pdf_to_json(str(args.pdf), str(out))
        else:
            parse_directory(str(args.pdf_dir), str(out))
        chunks = chunk_json_dir(out)
        prune = False  # an ad-hoc PDF adds to the corpus, it does not replace it
    else:
        if not (VBPL_DIR / "catalog.json").exists():
            print(f"❌ {VBPL_DIR / 'catalog.json'} not found — run scripts/crawl_vbpl_bxd.py first "
                  "(or use --sample for demo data).")
            return 1
        if not args.skip_parse:
            from src.data_pipeline.vbpl_corpus import build_corpus

            print(f"\n📚 Parsing crawled regulations in {VBPL_DIR}...")
            report = build_corpus(VBPL_DIR, PARSED_DIR)
            print(f"  ✅ {report['standards']} regulations ({report['full_text']} with full text), "
                  f"{report['articles']} articles from {report['documents']} documents")
            for item in report["items"]:
                if "error" in item:
                    print(f"  ⚠️ {item['doc_num']}: {item['error']}")
        chunks = chunk_json_dir(PARSED_DIR)

    if not chunks:
        print("\n⚠️ No data to ingest.")
        return 1

    if args.recreate:
        print("\n🗑️  Dropping collection...")
        get_client().delete_collection(get_collection_info()["name"])
    ensure_collection()
    embed_and_upsert(chunks)
    if prune:
        keep = {c["metadata"]["source_id"] for c in chunks}
        prune_sources(keep)
        print(f"🧹 Removed vectors of sources outside this run (kept {len(keep)} sources)")

    info = get_collection_info()
    print("\n" + "=" * 60)
    print("✅ Ingestion complete!")
    print(f"   Total chunks: {len(chunks)}")
    print(f"   Qdrant collection: {info.get('name', 'N/A')}")
    print(f"   Points: {info.get('points_count', 'N/A')}")
    print("=" * 60)
    expired = sum(1 for c in chunks if c["metadata"].get("chunk_type") == "overview" and c["metadata"].get("expired"))
    print(json.dumps({"chunks": len(chunks), "expired_regulations": expired}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
