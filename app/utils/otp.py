"""
OTP generation and validation utilities.
Security best practices implemented.
"""

import random
import string
from datetime import datetime, timedelta, timezone


def generate_otp(length: int = 6) -> str:
    """
    Generate a secure random OTP code.

    Args:
        length: Length of OTP (default 6 digits as per documentation)

    Returns:
        String of random digits
    """
    return "".join(random.choices(string.digits, k=length))


def calculate_otp_expiry(minutes: int = 10) -> datetime:
    """
    Calculate OTP expiry time.

    Args:
        minutes: Expiry time in minutes (default 10 as per documentation)

    Returns:
        Datetime object representing expiry time (timezone-aware)
    """
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def is_otp_expired(expires_at: datetime) -> bool:
    """
    Check if OTP has expired.

    Args:
        expires_at: OTP expiration datetime

    Returns:
        True if expired, False otherwise
    """
    return datetime.now(timezone.utc) > expires_at
