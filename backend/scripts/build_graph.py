"""Build the knowledge graph in Neo4j from QCVN/TCVN data.

Default source: data/vbpl_bxd/parsed (written by scripts/ingest_qcvn.py). Regulations that
were built from data before but are no longer in the corpus (e.g. old sample data) are
removed; placeholder Standard nodes that only exist as references are kept.

Usage:
    docker exec bim-backend python scripts/build_graph.py
    docker exec bim-backend python scripts/build_graph.py --sample     # hand-written demo data
    docker exec bim-backend python scripts/build_graph.py --json-dir DIR --no-prune
"""

import argparse
import json
import os
import sys
from pathlib import Path

from src.knowledge_graph.graph_builder import build_graph_from_directory
from src.knowledge_graph.graph_query import get_graph_stats
from src.knowledge_graph.neo4j_client import run_write_query

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PARSED_DIR = DATA_DIR / "vbpl_bxd" / "parsed"
SAMPLE_DIR = DATA_DIR / "qcvn"


def prune_standards(keep: set[str]) -> None:
    """Delete regulations (with their content) built earlier but absent from this corpus."""
    run_write_query(
        """
        MATCH (s:Standard)-[:CONTAINS]->(:Chapter)
        WHERE NOT s.code IN $keep
        WITH DISTINCT s
        OPTIONAL MATCH (s)-[:CONTAINS]->(ch:Chapter)
        OPTIONAL MATCH (ch)-[:HAS_SECTION]->(sec:Section)
        OPTIONAL MATCH (sec)-[:HAS_ARTICLE]->(a:Article)
        OPTIONAL MATCH (a)-[:SPECIFIES]->(r:Requirement)
        DETACH DELETE r, a, sec, ch, s
        """,
        {"keep": sorted(keep)},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the QCVN knowledge graph")
    parser.add_argument("--sample", action="store_true", help="Use hand-written sample data (data/qcvn)")
    parser.add_argument("--json-dir", type=Path, help="Directory of standard JSON files")
    parser.add_argument("--no-prune", action="store_true", help="Keep regulations not in this corpus")
    args = parser.parse_args()

    print("=" * 60)
    print("🕸️  BIM AI Agent — Knowledge Graph Builder")
    print("=" * 60)

    if args.sample:
        from src.data_pipeline.sample_data_generator import generate_sample_data

        data_dir = SAMPLE_DIR
        if not data_dir.exists() or not any(data_dir.glob("*.json")):
            generate_sample_data(str(data_dir))
    else:
        data_dir = args.json_dir or PARSED_DIR
    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json") and not f.startswith("_")) \
        if data_dir.exists() else []
    if not files:
        print(f"❌ No standard JSON in {data_dir} — run scripts/ingest_qcvn.py first (or use --sample).")
        return 1

    print(f"\n🔨 Building knowledge graph from {len(files)} files in {data_dir}...")
    result = build_graph_from_directory(str(data_dir))
    if not args.no_prune:
        keep = {json.loads((data_dir / f).read_text(encoding="utf-8"))["standard_code"] for f in files}
        prune_standards(keep)
        print(f"🧹 Removed regulations outside this corpus (kept {len(keep)})")

    print("\n📊 Graph Statistics:")
    try:
        stats = get_graph_stats()
        for label, count in stats.items():
            if label == "_relationships":
                print("\n  Relationships:")
                for rel_type, rel_count in count.items():
                    print(f"    {rel_type}: {rel_count}")
            else:
                print(f"  {label}: {count}")
    except Exception as e:
        print(f"  ⚠️ Could not get stats: {e}")

    print("\n" + "=" * 60)
    print("✅ Graph build complete!")
    print(f"   Nodes written: {result['nodes']}")
    print(f"   Relationships written: {result['relationships']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
