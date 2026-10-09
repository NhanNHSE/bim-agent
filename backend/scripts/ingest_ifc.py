"""IFC Ingestion Script — Parse IFC files and load into vector store + knowledge graph.

Usage:
    python scripts/ingest_ifc.py --ifc data/ifc/sample.ifc
    python scripts/ingest_ifc.py --ifc-dir data/ifc/
    python scripts/ingest_ifc.py --generate-sample  # Generate sample IFC first
"""

import argparse
import glob
import json
import os
import sys


from src.data_pipeline.ifc_parser import parse_ifc, get_ifc_summary
from src.knowledge_graph.ifc_to_graph import build_ifc_graph
from src.embeddings.embedding_service import embed_texts
from src.embeddings.vector_store import upsert


def ingest_ifc_file(filepath: str, collection: str = "ifc_elements"):
    """Parse a single IFC file and ingest into Qdrant + Neo4j."""
    print(f"\n📐 Parsing IFC: {filepath}")

    # Step 1: Parse IFC
    parsed = parse_ifc(filepath, extract_geometry=False)
    print(f"  ✅ Project: {parsed.project_name}")
    print(f"  ✅ Building: {parsed.building_name}")
    print(f"  ✅ Storeys: {len(parsed.storeys)}")
    print(f"  ✅ Elements: {len(parsed.elements)}")
    print(f"  ✅ Spaces: {len(parsed.spaces)}")
    print(f"  ✅ Materials: {len(parsed.materials)}")

    # Step 2: Create text chunks for vector embedding
    print("\n✂️  Creating text chunks...")
    chunks = []

    # Building summary chunk
    summary = get_ifc_summary(parsed)
    chunks.append({
        "text": summary,
        "metadata": {
            "source": "ifc",
            "filename": parsed.filename,
            "type": "building_summary",
        },
    })

    # Per-element chunks
    for el in parsed.elements:
        text_parts = [
            f"[{parsed.building_name}] {el['ifc_type']}: {el['name']}",
            f"Tầng: {el['storey']}" if el.get("storey") else "",
            f"Vật liệu: {el['material']}" if el.get("material") else "",
        ]
        if el.get("properties"):
            for k, v in el["properties"].items():
                text_parts.append(f"{k}: {v}")

        text = "\n".join(p for p in text_parts if p)
        chunks.append({
            "text": text,
            "metadata": {
                "source": "ifc",
                "filename": parsed.filename,
                "ifc_type": el["ifc_type"],
                "global_id": el["global_id"],
                "storey": el.get("storey", ""),
                "material": el.get("material", ""),
            },
        })

    # Per-space chunks
    for space in parsed.spaces:
        text = (
            f"[{parsed.building_name}] Không gian: {space['name']}\n"
            f"Tên đầy đủ: {space.get('long_name', '')}\n"
            f"Tầng: {space.get('storey', '')}\n"
            f"Diện tích: {space.get('area', 0):.1f} m²"
        )
        chunks.append({
            "text": text,
            "metadata": {
                "source": "ifc",
                "filename": parsed.filename,
                "type": "space",
                "storey": space.get("storey", ""),
            },
        })

    print(f"  📋 Total chunks: {len(chunks)}")

    # Step 3: Embed and upsert to Qdrant
    print("\n🧮 Embedding chunks...")
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)
    print(f"  ✅ Embedded {len(embeddings)} chunks")

    print("\n📥 Upserting into Qdrant...")
    upsert(
        embeddings=embeddings,
        documents=chunks,
        collection_name=collection,
        source_id=f"ifc:{os.path.basename(filepath)}",
    )
    print(f"  ✅ Upserted {len(chunks)} chunks into collection '{collection}'")

    # Step 4: Build knowledge graph
    print("\n🕸️  Building IFC Knowledge Graph...")
    stats = build_ifc_graph(parsed.to_dict())
    print(f"  ✅ Created {stats['nodes']} nodes, {stats['relationships']} relationships")

    # Save parsed JSON for reference
    json_path = filepath.replace(".ifc", "_parsed.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(parsed.to_json())
    print(f"  💾 Saved parsed data: {json_path}")

    return parsed


def main():
    parser = argparse.ArgumentParser(description="Ingest IFC files into BIM AI Agent")
    parser.add_argument("--ifc", help="Path to a single IFC file")
    parser.add_argument("--ifc-dir", help="Directory containing IFC files")
    parser.add_argument("--generate-sample", action="store_true",
                        help="Generate a sample IFC file first")
    parser.add_argument("--collection", default="ifc_elements",
                        help="Qdrant collection name (default: ifc_elements)")
    args = parser.parse_args()

    if args.generate_sample:
        print("📄 Generating sample IFC file...")
        from scripts.generate_sample_ifc import generate_sample_ifc
        sample_path = generate_sample_ifc()
        ingest_ifc_file(sample_path, args.collection)
        return

    if args.ifc:
        if not os.path.exists(args.ifc):
            print(f"❌ File not found: {args.ifc}")
            sys.exit(1)
        ingest_ifc_file(args.ifc, args.collection)

    elif args.ifc_dir:
        ifc_files = glob.glob(os.path.join(args.ifc_dir, "*.ifc"))
        if not ifc_files:
            print(f"❌ No IFC files found in: {args.ifc_dir}")
            sys.exit(1)
        print(f"📂 Found {len(ifc_files)} IFC files")
        for f in ifc_files:
            ingest_ifc_file(f, args.collection)

    else:
        print("Usage: python scripts/ingest_ifc.py --ifc <file.ifc>")
        print("       python scripts/ingest_ifc.py --generate-sample")
        sys.exit(1)

    print("\n🎉 IFC ingestion complete!")


if __name__ == "__main__":
    main()
