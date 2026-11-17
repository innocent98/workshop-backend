from limits.storage import RedisStorage

from app.api.v1.endpoints import auth
from app.core.rate_limit import limiter
from app.main import app


def test_app_and_auth_router_share_one_limiter():
    assert app.state.limiter is limiter
    assert auth.limiter is limiter


def test_limiter_uses_redis_storage():
    assert isinstance(limiter._storage, RedisStorage)
    assert limiter._in_memory_fallback_enabled is True


def test_custom_429_handler_is_registered():
    from slowapi.errors import RateLimitExceeded

    from app.main import custom_rate_limit_exceeded_handler

    assert app.exception_handlers[RateLimitExceeded] is custom_rate_limit_exceeded_handler
