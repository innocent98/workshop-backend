from decimal import Decimal

from app.db.models.booking import BookingStatus
from app.db.models.payment import PaymentMethod, PaymentStatus
from app.db.models.user import UserType
from app.services import payment_service as svc
from tests.factories import make_booking, make_payment, make_service, make_user


def _setup(db, booking_status=BookingStatus.ACCEPTED, amount="10000.00"):
    artisan = make_user(db, UserType.ARTISAN)
    customer = make_user(db, UserType.CLIENT)
    booking = make_booking(
        db, artisan, customer, make_service(db), amount=amount, status=booking_status
    )
    payment = make_payment(db, booking, amount=amount)
    db.commit()
    return artisan, booking, payment


def _charge(payment, **overrides):
    data = {
        "reference": payment.payment_reference,
        "status": "success",
        "amount": int(payment.amount * 100),
        "currency": "NGN",
        "channel": "card",
    }
    data.update(overrides)
    return data


def test_charge_success_marks_paid_and_notifies(db, notifications):
    artisan, booking, payment = _setup(db)
    result = svc.apply_charge_success(db, payment.payment_reference, _charge(payment))

    assert result.outcome == svc.OUTCOME_PROCESSED
    db.refresh(payment), db.refresh(booking)
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.payment_method == PaymentMethod.CARD
    assert payment.paid_at is not None
    assert booking.status == BookingStatus.PAID
    assert len(notifications) == 1
    assert notifications[0]["user_id"] == str(artisan.id)


def test_charge_success_is_idempotent(db, notifications):
    _, booking, payment = _setup(db)
    ref = payment.payment_reference
    first = svc.apply_charge_success(db, ref, _charge(payment))
    paid_at = payment.paid_at
    second = svc.apply_charge_success(db, ref, _charge(payment))

    assert first.outcome == svc.OUTCOME_PROCESSED
    assert second.outcome == svc.OUTCOME_ALREADY
    db.refresh(payment)
    assert payment.paid_at == paid_at
    assert len(notifications) == 1  # no second notification


def test_unknown_paystack_channels_do_not_raise(db):
    for channel in ("bank", "mobile_money", "qr", "eft", "bank_transfer", "ussd", "brand_new"):
        _, _, payment = _setup(db)
        result = svc.apply_charge_success(
            db, payment.payment_reference, _charge(payment, channel=channel)
        )
        assert result.outcome == svc.OUTCOME_PROCESSED
        db.refresh(payment)
        assert payment.status == PaymentStatus.SUCCESS
        assert payment.payment_method is not None


def test_amount_mismatch_is_not_settled(db):
    _, booking, payment = _setup(db)
    result = svc.apply_charge_success(
        db, payment.payment_reference, _charge(payment, amount=100)  # 1 naira
    )
    assert result.outcome == svc.OUTCOME_MISMATCH
    db.refresh(payment), db.refresh(booking)
    assert payment.status == PaymentStatus.PENDING
    assert booking.status == BookingStatus.ACCEPTED


def test_currency_mismatch_is_not_settled(db):
    _, _, payment = _setup(db)
    result = svc.apply_charge_success(
        db, payment.payment_reference, _charge(payment, currency="USD")
    )
    assert result.outcome == svc.OUTCOME_MISMATCH
    db.refresh(payment)
    assert payment.status == PaymentStatus.PENDING


def test_missing_amount_or_currency_is_not_settled(db):
    _, _, payment = _setup(db)
    data = _charge(payment)
    del data["amount"]
    assert svc.apply_charge_success(db, payment.payment_reference, data).outcome == (
        svc.OUTCOME_MISMATCH
    )


def test_booking_never_moves_backwards(db):
    for booking_status in (
        BookingStatus.IN_PROGRESS,
        BookingStatus.COMPLETED,
        BookingStatus.CANCELLED,
    ):
        _, booking, payment = _setup(db, booking_status=booking_status)
        result = svc.apply_charge_success(db, payment.payment_reference, _charge(payment))
        assert result.outcome == svc.OUTCOME_PROCESSED
        db.refresh(booking), db.refresh(payment)
        assert booking.status == booking_status  # untouched
        assert payment.status == PaymentStatus.SUCCESS  # money was still received


def test_unknown_reference(db):
    assert svc.apply_charge_success(db, "NOPE", {}).outcome == svc.OUTCOME_NOT_FOUND
    assert svc.apply_charge_failed(db, "NOPE", {}).outcome == svc.OUTCOME_NOT_FOUND


def test_charge_failed_marks_pending_payment_failed(db):
    _, booking, payment = _setup(db)
    result = svc.apply_charge_failed(db, payment.payment_reference, {"status": "failed"})
    assert result.outcome == svc.OUTCOME_PROCESSED
    db.refresh(payment), db.refresh(booking)
    assert payment.status == PaymentStatus.FAILED
    assert payment.failed_at is not None
    assert booking.status == BookingStatus.ACCEPTED


def test_charge_failed_never_regresses_a_successful_payment(db):
    _, _, payment = _setup(db)
    svc.apply_charge_success(db, payment.payment_reference, _charge(payment))
    result = svc.apply_charge_failed(db, payment.payment_reference, {"status": "failed"})
    assert result.outcome == svc.OUTCOME_IGNORED
    db.refresh(payment)
    assert payment.status == PaymentStatus.SUCCESS


def test_late_success_after_failed_still_settles(db):
    _, booking, payment = _setup(db)
    svc.apply_charge_failed(db, payment.payment_reference, {})
    result = svc.apply_charge_success(db, payment.payment_reference, _charge(payment))
    assert result.outcome == svc.OUTCOME_PROCESSED
    db.refresh(payment), db.refresh(booking)
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.failed_at is None
    assert booking.status == BookingStatus.PAID


def test_naira_to_kobo_is_exact():
    assert svc.naira_to_kobo(Decimal("10000.00")) == 1_000_000
    assert svc.naira_to_kobo(Decimal("0.07")) == 7
    assert svc.naira_to_kobo(Decimal("1234.56")) == 123_456
