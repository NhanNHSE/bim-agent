"""Local embedding service using FastEmbed (no API limits)."""

import os
os.environ["HF_HUB_OFFLINE"] = "1"
if not os.environ.get("FASTEMBED_CACHE_PATH"):
    os.environ["FASTEMBED_CACHE_PATH"] = "/home/appuser/.cache/fastembed"


from fastembed import TextEmbedding
import structlog

logger = structlog.get_logger()

_model = None
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384


def get_model() -> TextEmbedding:
    """Get or create the embedding model (singleton)."""
    global _model
    if _model is None:
        logger.info("loading_embedding_model", model=MODEL_NAME)
        _model = TextEmbedding(model_name=MODEL_NAME)
        logger.info("embedding_model_loaded", model=MODEL_NAME, dim=EMBEDDING_DIM)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors.
    """
    model = get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def embed_query(query: str) -> list[float]:
    """Embed a single query string.

    Args:
        query: Query text.

    Returns:
        Embedding vector.
    """
    model = get_model()
    embeddings = list(model.embed([query]))
    return embeddings[0].tolist()
