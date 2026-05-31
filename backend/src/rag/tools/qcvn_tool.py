"""QCVN/TCVN regulation search tools."""

import structlog

from src.core.config import get_settings
from src.embeddings.embedding_service import embed_query
from src.embeddings.vector_store import search as vector_search
from src.knowledge_graph.graph_query import (
    get_requirements_for_building_type,
    get_requirements_for_topic,
    get_material_properties,
)

logger = structlog.get_logger()
settings = get_settings()


def tool_qcvn_search(question: str, entities: dict) -> list:
    """Search QCVN/TCVN regulations via vector + graph."""
    results = []

    # Vector search
    query_embedding = embed_query(question)
    vector_results = vector_search(query_embedding, top_k=settings.retrieval_top_k,
                                   collection_name="qcvn_chunks")
    results.extend(vector_results)

    # Graph search based on entities
    building_type = entities.get("building_type", "")
    if building_type:
        for r in get_requirements_for_building_type(building_type):
            results.append({
                "text": f"[{r['standard_code']}] Điều {r['article_number']}: {r['article_title']}\n{r['content']}\n\nYêu cầu: {r['requirement']}",
                "metadata": {"standard_code": r["standard_code"], "article_number": r["article_number"], "source": "knowledge_graph"},
                "score": 0.9,
            })

    topic = entities.get("topic", "")
    if topic:
        for r in get_requirements_for_topic(topic, entities.get("standard_code")):
            results.append({
                "text": f"[{r['standard_code']}] Điều {r['article_number']}: {r['article_title']}\n{r['content']}",
                "metadata": {"standard_code": r["standard_code"], "article_number": r["article_number"], "source": "knowledge_graph"},
                "score": 0.85,
            })

    logger.info("tool_qcvn_search", results=len(results))
    return results


def tool_material_check(question: str, entities: dict) -> list:
    """Check material properties from regulations."""
    results = []
    material = entities.get("material", "")
    if material:
        mat_results = get_material_properties(material)
        for r in mat_results:
            if r.get("standard_code"):
                text = f"[{r['standard_code']}] Vật liệu: {r['material']}\nTrọng lượng riêng: {r['unit_weight']} {r['unit']}"
                if r.get("requirement_description"):
                    text += f"\n{r['requirement_description']}"
                results.append({
                    "text": text,
                    "metadata": {"standard_code": r.get("standard_code", ""), "source": "knowledge_graph"},
                    "score": 0.85,
                })
    logger.info("tool_material_check", results=len(results))
    return results
