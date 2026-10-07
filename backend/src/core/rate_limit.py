"""Fixed-window rate limiter backed by Redis, with an in-process fallback.

Redis keeps counts across restarts and workers; if it is unreachable the
limiter degrades to a per-process in-memory window instead of failing open.
"""

import math
import time
from collections import defaultdict

import structlog
from fastapi import HTTPException

logger = structlog.get_logger()

_redis_client = None
_memory_store: dict[str, list[float]] = defaultdict(list)


def _get_redis():
    """Lazy-init the Redis client; None when Redis is unavailable."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            from src.core.config import get_settings
            settings = get_settings()
            _redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _redis_client.ping()
        except Exception:
            _redis_client = False  # Mark as unavailable
            logger.warning("rate_limiter_redis_unavailable", fallback="in-memory")
    return _redis_client if _redis_client is not False else None


def _reject(retry_after: float):
    seconds = max(1, math.ceil(retry_after))
    if seconds >= 3600:
        wait = f"{math.ceil(seconds / 3600)} giờ"
    elif seconds >= 60:
        wait = f"{math.ceil(seconds / 60)} phút"
    else:
        wait = f"{seconds} giây"
    raise HTTPException(
        status_code=429,
        detail=f"Quá nhiều yêu cầu. Thử lại sau {wait}.",
        headers={"Retry-After": str(seconds)},
    )


def hit(key: str, limit: int, window_seconds: int) -> None:
    """Count one request for `key`; raise HTTP 429 once `limit` is exceeded within the window."""
    full_key = f"ratelimit:{key}"

    redis_cli = _get_redis()
    if redis_cli:
        try:
            current = redis_cli.incr(full_key)
            if current == 1:
                redis_cli.expire(full_key, window_seconds)
            if current > limit:
                ttl = redis_cli.ttl(full_key)
                logger.info("rate_limited", key=key, limit=limit, window=window_seconds)
                _reject(ttl if ttl and ttl > 0 else window_seconds)
            return
        except HTTPException:
            raise
        except Exception:
            pass  # Fall through to in-memory

    now = time.time()
    hits = [t for t in _memory_store[full_key] if now - t < window_seconds]
    if len(hits) >= limit:
        _memory_store[full_key] = hits
        logger.info("rate_limited", key=key, limit=limit, window=window_seconds)
        _reject(window_seconds - (now - hits[0]))
    hits.append(now)
    _memory_store[full_key] = hits


def reset() -> None:
    """Clear in-memory counters (tests)."""
    _memory_store.clear()
