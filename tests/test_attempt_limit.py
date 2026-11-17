"""Per-user attempt counter: atomic counting, expiry, and fail-open vs fail-closed on an outage."""

import threading
import uuid

import pytest

from app.core import attempt_limit
from app.core.token_blacklist import redis_client

pytestmark = pytest.mark.skipif(redis_client is None, reason="needs Redis")

SCOPE = "attempt_limit_test"


@pytest.fixture()
def key():
    k = str(uuid.uuid4())
    yield k
    attempt_limit.clear(SCOPE, k)


class BrokenRedis:
    def __getattr__(self, name):
        def boom(*args, **kwargs):
            raise ConnectionError("redis is down")

        return boom


@pytest.fixture()
def redis_down(monkeypatch):
    monkeypatch.setattr(attempt_limit, "redis_client", BrokenRedis())


def test_begin_attempt_allows_max_then_refuses(key):
    assert [attempt_limit.begin_attempt(SCOPE, key, max_failures=3) for _ in range(5)] == [
        True,
        True,
        True,
        False,
        False,
    ]


def test_concurrent_attempts_cannot_exceed_the_budget(key):
    """The old read-then-write check let N parallel guesses all pass before any was counted."""
    results = []
    barrier = threading.Barrier(20)

    def attempt():
        barrier.wait()
        results.append(attempt_limit.begin_attempt(SCOPE, key, max_failures=5))

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    [t.start() for t in threads]
    [t.join(timeout=15) for t in threads]
    assert results.count(True) == 5


def test_window_is_set_once_and_not_extended_by_later_attempts(key):
    attempt_limit.begin_attempt(SCOPE, key, window_seconds=100)
    ttl = redis_client.ttl(f"attempts:{SCOPE}:{key}")
    assert 0 < ttl <= 100
    redis_client.expire(f"attempts:{SCOPE}:{key}", 40)
    attempt_limit.begin_attempt(SCOPE, key, window_seconds=100)  # a refused-style repeat
    assert redis_client.ttl(f"attempts:{SCOPE}:{key}") <= 40


def test_a_key_that_lost_its_ttl_gets_one_again(key):
    k = f"attempts:{SCOPE}:{key}"
    redis_client.set(k, 2)  # no expiry: would otherwise lock the user forever
    attempt_limit.register_failure(SCOPE, key, window_seconds=60)
    assert 0 < redis_client.ttl(k) <= 60


def test_release_gives_an_attempt_back_and_never_goes_below_zero(key):
    attempt_limit.begin_attempt(SCOPE, key)
    attempt_limit.begin_attempt(SCOPE, key)
    attempt_limit.release_attempt(SCOPE, key)
    assert attempt_limit.failures(SCOPE, key) == 1
    attempt_limit.release_attempt(SCOPE, key)
    attempt_limit.release_attempt(SCOPE, key)
    assert attempt_limit.failures(SCOPE, key) == 0


def test_outage_fails_open_by_default(redis_down):
    assert attempt_limit.begin_attempt(SCOPE, "k") is True
    assert attempt_limit.is_locked(SCOPE, "k") is False
    attempt_limit.register_failure(SCOPE, "k")  # does not raise
    attempt_limit.release_attempt(SCOPE, "k")
    attempt_limit.clear(SCOPE, "k")


def test_outage_fails_closed_when_asked(redis_down):
    with pytest.raises(attempt_limit.LimiterUnavailable):
        attempt_limit.begin_attempt(SCOPE, "k", fail_closed=True)
    with pytest.raises(attempt_limit.LimiterUnavailable):
        attempt_limit.is_locked(SCOPE, "k", fail_closed=True)
    with pytest.raises(attempt_limit.LimiterUnavailable):
        attempt_limit.register_failure(SCOPE, "k", fail_closed=True)


def test_missing_redis_client_fails_closed_when_asked(monkeypatch):
    monkeypatch.setattr(attempt_limit, "redis_client", None)
    assert attempt_limit.begin_attempt(SCOPE, "k") is True
    with pytest.raises(attempt_limit.LimiterUnavailable):
        attempt_limit.begin_attempt(SCOPE, "k", fail_closed=True)
