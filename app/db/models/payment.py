import enum
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Enum as SQLEnum, DECIMAL
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    """Payment status enumeration"""
    PENDING = "pending"         # Payment initiated
    PROCESSING = "processing"   # Being processed
    SUCCESS = "success"         # Paid, funds held by Paystack
    FAILED = "failed"          # Payment failed
    RELEASED = "released"       # Funds released to artisan
    REFUNDED = "refunded"       # Refunded to customer


class PaymentMethod(str, enum.Enum):
    """Payment method enumeration"""
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    USSD = "ussd"
    BANK_ACCOUNT = "bank_account"


class Payment(Base):
    """
    Payment model for managing Paystack transactions.

    Handles payment initialization, verification, and fund release.
    """
    __tablename__ = "payments"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Reference Numbers
    payment_reference = Column(String(20), unique=True, nullable=False, index=True)
    paystack_reference = Column(String(255), unique=True, nullable=True, index=True)
    paystack_access_code = Column(String(255), nullable=True)

    # Foreign Key (one-to-one with Booking)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )

    # Payment Details
    authorization_url = Column(String(500), nullable=True)
    amount = Column(DECIMAL(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="NGN")
    payment_method = Column(
        SQLEnum(PaymentMethod, values_callable=lambda x: [e.value for e in x]),
        nullable=True
    )

    # Status
    status = Column(
        SQLEnum(PaymentStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True
    )

    # Paystack Response Data
    paystack_response = Column(Text, nullable=True)  # JSON response from Paystack

    # Customer Info
    customer_email = Column(String(255), nullable=False)
    customer_name = Column(String(255), nullable=False)

    # Status Timestamps
    paid_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)

    # Payout Details (when releasing to artisan)
    payout_reference = Column(String(255), unique=True, nullable=True, index=True)
    payout_response = Column(Text, nullable=True)  # JSON payout response

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    booking = relationship("Booking", back_populates="payment")

    def __repr__(self):
        return f"<Payment {self.payment_reference} ({self.status})>"
