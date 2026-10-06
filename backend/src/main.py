"""BIM AI Agent — FastAPI Application Entry Point."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import structlog

from src.core.config import get_settings
from src.core.logging import setup_logging
from src.core.errors import register_error_handlers
from src.database.session import init_db
from src.api.router_health import router as health_router
from src.api.router_chat import router as chat_router
from src.api.router_auth import router as auth_router
from src.api.router_documents import router as documents_router
from src.api.router_graph import router as graph_router
from src.api.router_ifc import router as ifc_router

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Configure logging first
    setup_logging(debug=settings.debug)

    # Database
    init_db()

    # Preload embedding model to avoid 60s delay on first request
    try:
        from src.embeddings.embedding_service import get_model
        get_model()
        logger.info("embedding_model_preloaded")
    except Exception as e:
        logger.warning("embedding_preload_failed", error=str(e))

    logger.info(
        "app_started",
        name=settings.app_name,
        version=settings.app_version,
        neo4j=settings.neo4j_uri,
        qdrant=f"{settings.qdrant_host}:{settings.qdrant_port}",
        agent_mode=settings.agent_mode,
    )
    yield
    # Shutdown
    logger.info("app_shutdown", name=settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI Agent cho ngành Kiến trúc, Kỹ thuật và Xây dựng (AEC)",
    lifespan=lifespan,
)

# CORS — restrict to known origins
_allowed_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3001,http://localhost:3000,http://localhost:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Exception handlers (APIError subclasses -> {"error": {"code", "message"}}; HTTPException left to FastAPI)
register_error_handlers(app)

# GZip compression for large geometry responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Routers
app.include_router(health_router, prefix="/api/v1", tags=["Health"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat_router, prefix="/api/v1", tags=["Chat"])
app.include_router(documents_router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(graph_router, prefix="/api/v1/graph", tags=["Knowledge Graph"])
app.include_router(ifc_router, tags=["IFC/BIM"])
