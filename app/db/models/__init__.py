# Import all models here so Alembic can detect them
from app.db.models.admin import AdminAuditLog, DisputeResolution
from app.db.models.artisan_profile import ArtisanProfile, AvailabilityStatus
from app.db.models.booking import Booking, BookingStatus
from app.db.models.booking_progress_log import BookingProgressLog
from app.db.models.otp import OTP, OTPType
from app.db.models.password_reset import PasswordResetToken
from app.db.models.payment import Payment, PaymentMethod, PaymentReference, PaymentStatus
from app.db.models.portfolio import Portfolio
from app.db.models.push_device import PushDevice, PushPlatform
from app.db.models.review import Review, ReviewReport
from app.db.models.service import Service, UserService
from app.db.models.service_category import ServiceCategory
from app.db.models.user import User, UserType
from app.db.models.user_notification import UserNotification
from app.db.models.verification_record import ArtisanVerificationRecord
from app.db.models.withdrawal import Withdrawal, WithdrawalStatus

__all__ = [
    "User",
    "UserType",
    "OTP",
    "OTPType",
    "Service",
    "UserService",
    "PasswordResetToken",
    "ServiceCategory",
    "ArtisanProfile",
    "AvailabilityStatus",
    "Portfolio",
    "Booking",
    "BookingStatus",
    "Payment",
    "PaymentStatus",
    "PaymentMethod",
    "PaymentReference",
    "Withdrawal",
    "WithdrawalStatus",
    "Review",
    "ReviewReport",
    "BookingProgressLog",
    "PushDevice",
    "PushPlatform",
    "UserNotification",
    "DisputeResolution",
    "AdminAuditLog",
    "ArtisanVerificationRecord",
]
