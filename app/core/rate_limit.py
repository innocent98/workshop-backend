"""
Single shared rate limiter.

Every router that uses ``@limiter.limit(...)`` and the FastAPI app (``app.state.limiter``)
must use THIS instance, so limits are counted once and stored in Redis (shared across all
API workers/containers) instead of per-process memory.

If Redis is unreachable at request time slowapi falls back to in-memory limiting rather than
failing the request (rate limiting must never take login down).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI or settings.REDIS_URL,
    in_memory_fallback_enabled=True,
)
