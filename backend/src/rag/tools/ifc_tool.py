"""IFC/BIM query tool — searches vector store and Neo4j for building elements."""

import structlog

from src.embeddings.embedding_service import embed_query
from src.embeddings.vector_store import search as vector_search

logger = structlog.get_logger()


def tool_ifc_query(question: str, entities: dict) -> list:
    """Query IFC building elements from vector store and Neo4j."""
    results = []

    # Vector search on IFC collection
    try:
        query_embedding = embed_query(question)
        ifc_results = vector_search(query_embedding, top_k=10,
                                     collection_name="ifc_elements")
        results.extend(ifc_results)
    except Exception as e:
        logger.warning("ifc_vector_search_failed", error=str(e))

    # Graph queries for IFC
    try:
        from src.knowledge_graph.ifc_to_graph import (
            query_elements_on_storey,
            query_material_usage,
            get_ifc_building_summary,
        )

        storey = entities.get("storey", "")
        if storey:
            elements = query_elements_on_storey(storey)
            if elements:
                text = f"Tầng {storey} có {len(elements)} cấu kiện:\n"
                for el in elements:
                    text += f"  - {el['type']}: {el['name']} (vật liệu: {el.get('material', 'N/A')})\n"
                results.append({
                    "text": text,
                    "metadata": {"source": "ifc_graph", "storey": storey},
                    "score": 0.95,
                })

        material = entities.get("material", "")
        if material:
            elements = query_material_usage(material)
            if elements:
                text = f"Vật liệu '{material}' được sử dụng trong {len(elements)} cấu kiện:\n"
                for el in elements:
                    text += f"  - {el['type']}: {el['name']} ({el.get('storey', '')})\n"
                results.append({
                    "text": text,
                    "metadata": {"source": "ifc_graph", "material": material},
                    "score": 0.9,
                })

        # Always include building summary if asking about IFC
        summary = get_ifc_building_summary()
        if summary.get("building"):
            text = f"Tổng quan công trình: {summary['building']}\n"
            text += f"Dự án: {summary.get('project', '')}\n"
            for etype, count in summary.get("element_counts", {}).items():
                text += f"  - {etype}: {count}\n"
            results.append({
                "text": text,
                "metadata": {"source": "ifc_graph", "type": "summary"},
                "score": 0.7,
            })

    except Exception as e:
        logger.warning("ifc_graph_query_failed", error=str(e))

    logger.info("tool_ifc_query", results=len(results))
    return results
