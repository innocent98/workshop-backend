import enum

from sqlalchemy import DECIMAL, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class WithdrawalStatus(str, enum.Enum):
    """Lifecycle of an artisan withdrawal (one Paystack transfer)."""

    PROCESSING = "processing"  # transfer initiated, awaiting Paystack confirmation
    SUCCESS = "success"  # transfer.success received, money left the platform
    FAILED = "failed"  # transfer.failed / initiation rejected, funds back in balance
    REVERSED = "reversed"  # transfer.reversed, funds back in balance
    # Money state is unclear (e.g. transfer.success after we freed the payments, or an amount
    # mismatch): payments stay as they are, an admin must resolve it.
    NEEDS_REVIEW = "needs_review"


class Withdrawal(Base):
    """
    A single payout to an artisan's bank account.

    One withdrawal = one Paystack transfer covering one or more whole Payment rows
    (linked through ``payments.withdrawal_id``).
    """

    __tablename__ = "withdrawals"
    __table_args__ = (
        UniqueConstraint("artisan_id", "idempotency_key", name="uq_withdrawals_artisan_idem_key"),
    )

    id = Column(Integer, primary_key=True, index=True)

    artisan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(DECIMAL(12, 2), nullable=False)  # exact amount transferred
    requested_amount = Column(DECIMAL(12, 2), nullable=True)  # what the artisan asked for
    currency = Column(String(3), nullable=False, default="NGN", server_default="NGN")
    status = Column(
        SQLEnum(
            WithdrawalStatus,
            values_callable=lambda x: [e.value for e in x],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=WithdrawalStatus.PROCESSING,
        index=True,
    )

    # Our own unique reference; also sent to Paystack as the transfer reference
    reference = Column(String(64), unique=True, nullable=False, index=True)
    idempotency_key = Column(String(100), nullable=True)

    # Paystack
    transfer_code = Column(String(100), nullable=True, index=True)
    recipient_code = Column(String(100), nullable=True)

    # Destination (full account number is never stored)
    bank_code = Column(String(20), nullable=False)
    account_number_last4 = Column(String(4), nullable=False)
    account_name = Column(String(255), nullable=True)

    failure_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    payments = relationship("Payment", back_populates="withdrawal")

    def __repr__(self):
        return f"<Withdrawal {self.reference} {self.amount} ({self.status})>"
