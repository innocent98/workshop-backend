"""
Small per-key failure counter on top of the shared Redis client (fails OPEN when Redis is down,
like the token blacklist). Used to cap credential guessing on sensitive endpoints per USER, in
addition to the per-IP limiter.
"""

from typing import Optional

from app.core.logger import logger
from app.core.token_blacklist import redis_client

DEFAULT_MAX = 5
DEFAULT_WINDOW_SECONDS = 15 * 60


def _key(scope: str, key: str) -> str:
    return f"attempts:{scope}:{key}"


def failures(scope: str, key: str) -> int:
    if not redis_client:
        return 0
    try:
        value: Optional[str] = redis_client.get(_key(scope, key))
        return int(value) if value else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"attempt_limit read failed: {type(exc).__name__}")
        return 0


def is_locked(scope: str, key: str, max_failures: int = DEFAULT_MAX) -> bool:
    return failures(scope, key) >= max_failures


def register_failure(scope: str, key: str, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> None:
    if not redis_client:
        return
    try:
        k = _key(scope, key)
        pipe = redis_client.pipeline()
        pipe.incr(k)
        pipe.expire(k, window_seconds)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"attempt_limit write failed: {type(exc).__name__}")


def clear(scope: str, key: str) -> None:
    if not redis_client:
        return
    try:
        redis_client.delete(_key(scope, key))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"attempt_limit clear failed: {type(exc).__name__}")
