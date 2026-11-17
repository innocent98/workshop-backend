"""
Small per-key failure counter on top of the shared Redis client. Used to cap credential guessing
on sensitive endpoints per USER, in addition to the per-IP limiter.

Two modes, chosen by the caller:

- fail OPEN (default, like the token blacklist and the login limiter): when Redis is down the
  counter reads 0 and writes are skipped, so a Redis outage never locks users out of signing in.
- fail CLOSED (``fail_closed=True``): when Redis is down, raise ``LimiterUnavailable`` so the
  caller answers 503. Used for account deletion and change-password, where "no limiter" would let
  a stolen token guess the password without bound, and a short refusal is harmless.

``begin_attempt`` is the atomic path: it counts the attempt BEFORE the credential is checked
(one Lua INCR + expiry), so N concurrent guesses cannot all slip past a read-then-write check.
The caller ``clear``s on success and ``release_attempt``s when the request failed for a reason
that is not a wrong credential.
"""

from typing import Optional

from app.core.logger import logger
from app.core.token_blacklist import redis_client

DEFAULT_MAX = 5
DEFAULT_WINDOW_SECONDS = 15 * 60

# INCR and set the window in one atomic step. The expiry is set when the key is created (or has
# somehow lost its TTL) and is NOT refreshed by later attempts, so hammering a locked key cannot
# extend the lockout, and a crash between two commands cannot leave a key that never expires.
_INCR_WITH_WINDOW = """
local count = redis.call('INCR', KEYS[1])
if count == 1 or redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

# DECR but never below zero (an expired window must not go negative).
_DECR_FLOOR = """
local count = redis.call('DECR', KEYS[1])
if count <= 0 then
  redis.call('DEL', KEYS[1])
  return 0
end
return count
"""


class LimiterUnavailable(Exception):
    """Redis is unreachable and the caller asked the limiter to fail closed."""


def _key(scope: str, key: str) -> str:
    return f"attempts:{scope}:{key}"


def _unavailable(action: str, scope: str, exc: Optional[BaseException], fail_closed: bool) -> None:
    reason = type(exc).__name__ if exc is not None else "no redis client"
    if fail_closed:
        logger.error(
            f"attempt_limit {action} failed for scope '{scope}' ({reason}): "
            "failing CLOSED, request refused with 503"
        )
        raise LimiterUnavailable(scope)
    logger.warning(f"attempt_limit {action} failed ({reason})")


def failures(scope: str, key: str, fail_closed: bool = False) -> int:
    if not redis_client:
        _unavailable("read", scope, None, fail_closed)
        return 0
    try:
        value: Optional[str] = redis_client.get(_key(scope, key))
        return int(value) if value else 0
    except Exception as exc:  # noqa: BLE001
        _unavailable("read", scope, exc, fail_closed)
        return 0


def is_locked(
    scope: str, key: str, max_failures: int = DEFAULT_MAX, fail_closed: bool = False
) -> bool:
    return failures(scope, key, fail_closed) >= max_failures


def register_failure(
    scope: str,
    key: str,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    fail_closed: bool = False,
) -> None:
    if not redis_client:
        _unavailable("write", scope, None, fail_closed)
        return
    try:
        redis_client.eval(_INCR_WITH_WINDOW, 1, _key(scope, key), window_seconds)
    except Exception as exc:  # noqa: BLE001
        _unavailable("write", scope, exc, fail_closed)


def begin_attempt(
    scope: str,
    key: str,
    max_failures: int = DEFAULT_MAX,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    fail_closed: bool = False,
) -> bool:
    """
    Atomically count one attempt. Returns False when ``key`` already used up its ``max_failures``
    (the attempt is refused and must not be processed). The count stays until ``clear`` (success),
    ``release_attempt`` (not a credential failure) or the window ends.
    """
    if not redis_client:
        _unavailable("write", scope, None, fail_closed)
        return True
    try:
        count = int(redis_client.eval(_INCR_WITH_WINDOW, 1, _key(scope, key), window_seconds))
    except Exception as exc:  # noqa: BLE001
        _unavailable("write", scope, exc, fail_closed)
        return True
    return count <= max_failures


def release_attempt(scope: str, key: str) -> None:
    """Give back an attempt counted by ``begin_attempt`` (the request was not a bad credential)."""
    if not redis_client:
        return
    try:
        redis_client.eval(_DECR_FLOOR, 1, _key(scope, key))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"attempt_limit release failed: {type(exc).__name__}")


def clear(scope: str, key: str) -> None:
    if not redis_client:
        return
    try:
        redis_client.delete(_key(scope, key))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"attempt_limit clear failed: {type(exc).__name__}")
