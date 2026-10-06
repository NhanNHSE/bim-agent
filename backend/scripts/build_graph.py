"""Build knowledge graph in Neo4j from QCVN/TCVN data.

Usage:
    docker exec bim-backend python scripts/build_graph.py
"""


from src.data_pipeline.sample_data_generator import generate_sample_data
from src.knowledge_graph.graph_builder import build_graph_from_directory
from src.knowledge_graph.graph_query import get_graph_stats
import os


def main():
    print("=" * 60)
    print("🕸️  BIM AI Agent — Knowledge Graph Builder")
    print("=" * 60)

    # Generate sample data if needed
    data_dir = "data/qcvn"
    if not os.path.exists(data_dir) or not os.listdir(data_dir):
        print("\n📄 Generating sample data...")
        generate_sample_data(data_dir)

    # Build graph
    print("\n🔨 Building knowledge graph...")
    result = build_graph_from_directory(data_dir)

    # Show stats
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
    print(f"✅ Graph build complete!")
    print(f"   Nodes created: {result['nodes']}")
    print(f"   Relationships created: {result['relationships']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
