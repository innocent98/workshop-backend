# Import all models here so Alembic can detect them
from app.db.models.user import User, UserType
from app.db.models.otp import OTP, OTPType
from app.db.models.service import Service, UserService
from app.db.models.password_reset import PasswordResetToken

__all__ = [
    "User",
    "UserType",
    "OTP",
    "OTPType",
    "Service",
    "UserService",
    "PasswordResetToken",
]
