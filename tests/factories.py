"""Small factories for building money-path test data."""

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import Service
from app.db.models.user import User, UserType
from app.utils.commission import calculate_artisan_amount, calculate_platform_fee

_counter = itertools.count(1)


def make_user(db, user_type=UserType.ARTISAN):
    n = next(_counter)
    user = User(
        id=uuid.uuid4(),
        full_name=f"Test User {n}",
        email=f"user{n}@example.test",
        phone_number=f"0800000{n:04d}",
        user_type=user_type,
        is_email_verified=True,
        is_active=True,
        registration_completed=True,
    )
    db.add(user)
    db.flush()
    return user


def make_service(db):
    service = Service(name=f"Service {next(_counter)}")
    db.add(service)
    db.flush()
    return service


def make_booking(
    db,
    artisan,
    customer,
    service,
    *,
    amount="10000.00",
    status=BookingStatus.ACCEPTED,
    confirmed=False,
    deadline_hours=None,
    disputed=False,
):
    """deadline_hours: hours from now for the dispute-window deadline (negative = elapsed)."""
    now = datetime.now(timezone.utc)
    booking = Booking(
        booking_reference=f"BK{next(_counter):06d}",
        customer_id=customer.id,
        artisan_id=artisan.id,
        service_id=service.id,
        job_date=now + timedelta(days=1),
        job_location="SRID=4326;POINT(3.3792 6.5244)",
        job_address="1 Test Street, Lagos",
        budget_min=Decimal("1000.00"),
        budget_max=Decimal("100000.00"),
        agreed_amount=Decimal(amount),
        status=status,
        completion_confirmed_by_client_at=now if confirmed else None,
        completion_confirmation_deadline_at=(
            now + timedelta(hours=deadline_hours) if deadline_hours is not None else None
        ),
        completion_disputed_at=now if disputed else None,
    )
    db.add(booking)
    db.flush()
    return booking


def make_payment(
    db,
    booking,
    *,
    amount="10000.00",
    status=PaymentStatus.PENDING,
    paid_at=None,
    commission="10.00",
):
    n = next(_counter)
    gross = Decimal(amount)
    payment = Payment(
        payment_reference=f"PAY{n:06d}",
        booking_id=booking.id,
        amount=gross,
        platform_fee=calculate_platform_fee(gross, Decimal(commission)),
        artisan_amount=calculate_artisan_amount(gross, Decimal(commission)),
        currency="NGN",
        status=status,
        customer_email="customer@example.test",
        customer_name="Test Customer",
        paid_at=paid_at,
    )
    db.add(payment)
    db.flush()
    return payment


def make_withdrawable(db, artisan, customer, service, *, amount="10000.00", paid_days_ago=1):
    """A SUCCESS payment on a COMPLETED + client-confirmed booking (ready to withdraw)."""
    booking = make_booking(
        db,
        artisan,
        customer,
        service,
        amount=amount,
        status=BookingStatus.COMPLETED,
        confirmed=True,
        deadline_hours=-1,
    )
    payment = make_payment(
        db,
        booking,
        amount=amount,
        status=PaymentStatus.SUCCESS,
        paid_at=datetime.now(timezone.utc) - timedelta(days=paid_days_ago),
    )
    return booking, payment
