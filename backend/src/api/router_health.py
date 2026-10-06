"""Health check router."""

from fastapi import APIRouter

from src.core.config import get_settings
from src.knowledge_graph.neo4j_client import health_check as neo4j_health
from src.embeddings.vector_store import get_collection_info

router = APIRouter()
settings = get_settings()


@router.get("/health")
def health_check():
    """Check health of all services."""
    neo4j_ok = False
    try:
        neo4j_ok = neo4j_health()
    except Exception:
        pass

    qdrant_info = get_collection_info()

    return {
        "status": "healthy" if neo4j_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "services": {
            "neo4j": "connected" if neo4j_ok else "disconnected",
            "qdrant": qdrant_info.get("status", "unknown"),
            "qdrant_vectors": qdrant_info.get("vectors_count", 0),
        },
    }
