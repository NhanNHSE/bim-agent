"""Centralized LLM client — Single source of truth for Gemini API access.

All modules should import their LLM client from here instead of creating
their own. This ensures:
- Consistent API key management
- Single connection pool
- Centralized retry/fallback logic
- Easy model upgrades (change once, applies everywhere)
"""

from functools import lru_cache

from google import genai
import structlog

from src.core.config import get_settings

logger = structlog.get_logger()

_client = None


def get_llm_client() -> genai.Client:
    """Get the shared Gemini API client (lazy-initialized, singleton).

    Returns:
        Configured genai.Client instance.
    """
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. LLM features are unavailable."
            )
        _client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("llm_client_initialized", model=settings.llm_model)
    return _client


def get_model_name(fallback: bool = False) -> str:
    """Get the configured model name.

    Args:
        fallback: If True, return the fallback (lighter) model.

    Returns:
        Model name string.
    """
    settings = get_settings()
    return settings.llm_fallback_model if fallback else settings.llm_model


MAX_RETRIES = 3
"""Default retry count for LLM calls."""
