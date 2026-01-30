"""
Token blacklist using Redis for logout functionality.
"""
import redis
from datetime import timedelta
from typing import Optional

from app.core.config import settings
from app.core.logger import logger


# Initialize Redis client for token blacklist
try:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
except Exception as e:
    logger.error(f"Failed to connect to Redis for token blacklist: {e}")
    redis_client = None


def blacklist_token(token: str, expiry_minutes: int = None) -> bool:
    """
    Add token to blacklist.

    Args:
        token: JWT token to blacklist
        expiry_minutes: How long to keep in blacklist (default: token expiry time)

    Returns:
        True if successfully blacklisted, False otherwise
    """
    if not redis_client:
        logger.warning("Redis not available - token blacklist disabled")
        return False

    try:
        # Default to token expiry time if not specified
        if expiry_minutes is None:
            expiry_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

        # Store token with expiry
        key = f"blacklist:{token}"
        redis_client.setex(key, timedelta(minutes=expiry_minutes), "1")
        logger.info(f"Token blacklisted successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to blacklist token: {e}")
        return False


def is_token_blacklisted(token: str) -> bool:
    """
    Check if token is blacklisted.

    Args:
        token: JWT token to check

    Returns:
        True if blacklisted, False otherwise
    """
    if not redis_client:
        # If Redis is down, allow access (fail open for availability)
        return False

    try:
        key = f"blacklist:{token}"
        return redis_client.exists(key) > 0

    except Exception as e:
        logger.error(f"Failed to check token blacklist: {e}")
        # Fail open - allow access if Redis is unavailable
        return False


def remove_from_blacklist(token: str) -> bool:
    """
    Remove token from blacklist (for testing/admin purposes).

    Args:
        token: JWT token to remove

    Returns:
        True if successfully removed, False otherwise
    """
    if not redis_client:
        return False

    try:
        key = f"blacklist:{token}"
        redis_client.delete(key)
        return True

    except Exception as e:
        logger.error(f"Failed to remove token from blacklist: {e}")
        return False
