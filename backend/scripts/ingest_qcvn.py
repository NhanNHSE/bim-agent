"""Ingest QCVN/TCVN data into Qdrant vector store.

Supports both:
- JSON files (from sample_data_generator or qcvn_parser)
- PDF files (auto-parsed via qcvn_parser)

Usage:
    # Ingest sample data (auto-generated)
    docker exec bim-backend python scripts/ingest_qcvn.py

    # Ingest from specific directory
    docker exec bim-backend python scripts/ingest_qcvn.py --pdf-dir data/pdf

    # Ingest a single PDF file
    docker exec bim-backend python scripts/ingest_qcvn.py --pdf data/pdf/QCVN06.pdf
"""

import argparse
import os


from src.data_pipeline.sample_data_generator import generate_sample_data
from src.data_pipeline.qcvn_parser import parse_pdf_to_json, parse_directory
from src.data_pipeline.chunker import chunk_from_json_file
from src.embeddings.embedding_service import embed_texts
from src.embeddings.vector_store import ensure_collection, upsert_chunks, get_collection_info


def ingest_json_files(data_dir: str) -> list[dict]:
    """Chunk all JSON files in a directory."""
    json_files = [f for f in os.listdir(data_dir) if f.endswith(".json")]
    if not json_files:
        return []

    print(f"\n✂️  Chunking {len(json_files)} JSON files...")
    all_chunks = []
    for filename in sorted(json_files):
        filepath = os.path.join(data_dir, filename)
        chunks = chunk_from_json_file(filepath)
        all_chunks.extend(chunks)
        print(f"  📋 {filename}: {len(chunks)} chunks")

    return all_chunks


def ingest_pdf_files(pdf_dir: str, json_output_dir: str) -> list[dict]:
    """Parse PDFs → JSON → Chunks."""
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"⚠️ No PDF files found in {pdf_dir}")
        return []

    print(f"\n📄 Parsing {len(pdf_files)} PDF files...")
    json_paths = parse_directory(pdf_dir, json_output_dir)

    # Now chunk the parsed JSONs
    all_chunks = []
    for json_path in json_paths:
        chunks = chunk_from_json_file(json_path)
        all_chunks.extend(chunks)
        print(f"  ✂️  {os.path.basename(json_path)}: {len(chunks)} chunks")

    return all_chunks


def embed_and_upsert(chunks: list[dict]):
    """Embed chunks and upsert to Qdrant."""
    if not chunks:
        print("⚠️ No chunks to embed")
        return

    print(f"\n🧮 Embedding {len(chunks)} chunks...")
    texts = [c["text"] for c in chunks]

    # Batch embed to avoid memory issues with large datasets
    batch_size = 64
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_embeddings = embed_texts(batch)
        all_embeddings.extend(batch_embeddings)
        print(f"  ✅ Embedded batch {i // batch_size + 1}/{(len(texts) - 1) // batch_size + 1}")

    print(f"\n📥 Upserting {len(all_embeddings)} vectors into Qdrant...")
    ensure_collection()
    upsert_chunks(chunks, all_embeddings)


def main():
    parser = argparse.ArgumentParser(description="Ingest QCVN/TCVN data")
    parser.add_argument("--pdf-dir", type=str, help="Directory with PDF files to parse")
    parser.add_argument("--pdf", type=str, help="Single PDF file to parse")
    parser.add_argument("--json-dir", type=str, default="data/qcvn",
                        help="Directory with JSON files (default: data/qcvn)")
    parser.add_argument("--no-sample", action="store_true",
                        help="Don't generate sample data if no files found")
    args = parser.parse_args()

    print("=" * 60)
    print("🏗️  BIM AI Agent — QCVN/TCVN Data Ingestion")
    print("=" * 60)

    all_chunks = []

    # Option 1: Parse a single PDF
    if args.pdf:
        print(f"\n📄 Parsing single PDF: {args.pdf}")
        json_path = parse_pdf_to_json(args.pdf, args.json_dir)
        chunks = chunk_from_json_file(json_path)
        all_chunks.extend(chunks)
        print(f"  ✂️ {len(chunks)} chunks created")

    # Option 2: Parse a directory of PDFs
    elif args.pdf_dir:
        chunks = ingest_pdf_files(args.pdf_dir, args.json_dir)
        all_chunks.extend(chunks)

    # Option 3: Ingest existing JSON files (or generate samples)
    else:
        data_dir = args.json_dir
        json_files = []

        if os.path.exists(data_dir):
            json_files = [f for f in os.listdir(data_dir) if f.endswith(".json")]

        if not json_files and not args.no_sample:
            print("\n📄 No data found. Generating sample QCVN/TCVN data...")
            generate_sample_data(data_dir)

        chunks = ingest_json_files(data_dir)
        all_chunks.extend(chunks)

    # Embed and upsert
    if all_chunks:
        embed_and_upsert(all_chunks)

        # Show collection info
        info = get_collection_info()
        print("\n" + "=" * 60)
        print("✅ Ingestion complete!")
        print(f"   Total chunks: {len(all_chunks)}")
        print(f"   Qdrant collection: {info.get('name', 'N/A')}")
        print(f"   Total vectors: {info.get('vectors_count', 'N/A')}")
        print("=" * 60)
    else:
        print("\n⚠️ No data to ingest. Provide PDFs or JSON files.")
        print("   Usage:")
        print("     python scripts/ingest_qcvn.py --pdf-dir data/pdf")
        print("     python scripts/ingest_qcvn.py --pdf path/to/file.pdf")


if __name__ == "__main__":
    main()
