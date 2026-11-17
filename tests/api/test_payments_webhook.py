import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from app.core.config import settings
from app.db.models.booking import BookingStatus
from app.db.models.payment import PaymentStatus
from app.db.models.user import UserType
from app.db.models.withdrawal import WithdrawalStatus
from app.services import withdrawal_service as wsvc
from app.services.paystack import PaystackService
from tests.factories import make_booking, make_payment, make_service, make_user, make_withdrawable

SECRET = "whsec_test"


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_WEBHOOK_SECRET", SECRET)


def _post(client, event, data, signature=None):
    body = json.dumps({"event": event, "data": data}).encode()
    if signature is None:
        signature = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    return client.post(
        "/api/v1/payments/webhook",
        content=body,
        headers={"x-paystack-signature": signature, "content-type": "application/json"},
    )


@pytest.fixture
def pending_payment(db):
    artisan = make_user(db, UserType.ARTISAN)
    customer = make_user(db, UserType.CLIENT)
    booking = make_booking(db, artisan, customer, make_service(db), amount="10000.00")
    payment = make_payment(db, booking, amount="10000.00")
    db.commit()
    return booking, payment


def _charge(payment, **kw):
    data = {
        "reference": payment.payment_reference,
        "status": "success",
        "amount": 1_000_000,
        "currency": "NGN",
        "channel": "mobile_money",
    }
    data.update(kw)
    return data


def test_bad_signature_is_rejected(client, pending_payment):
    _, payment = pending_payment
    r = _post(client, "charge.success", _charge(payment), signature="bad")
    assert r.status_code == 401


def test_charge_success_with_non_enum_channel_marks_paid(client, db, pending_payment):
    booking, payment = pending_payment
    r = _post(client, "charge.success", _charge(payment))
    assert r.status_code == 200
    assert r.json() == {"status": "success", "message": "Payment processed"}
    db.refresh(payment), db.refresh(booking)
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.payment_method.value == "mobile_money"
    assert booking.status == BookingStatus.PAID


def test_charge_success_redelivery_is_idempotent(client, db, pending_payment, notifications):
    booking, payment = pending_payment
    _post(client, "charge.success", _charge(payment))
    r = _post(client, "charge.success", _charge(payment))
    assert r.json()["message"] == "Payment already processed"
    assert len(notifications) == 1


def test_charge_success_amount_mismatch_returns_200_but_does_not_settle(
    client, db, pending_payment
):
    booking, payment = pending_payment
    r = _post(client, "charge.success", _charge(payment, amount=5000))
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    db.refresh(payment), db.refresh(booking)
    assert payment.status == PaymentStatus.PENDING
    assert booking.status == BookingStatus.ACCEPTED


def test_charge_failed(client, db, pending_payment):
    _, payment = pending_payment
    r = _post(client, "charge.failed", {"reference": payment.payment_reference, "status": "failed"})
    assert r.status_code == 200
    db.refresh(payment)
    assert payment.status == PaymentStatus.FAILED


def test_unknown_reference_and_unhandled_event_are_ignored(client):
    assert (
        _post(
            client, "charge.success", {"reference": "ghost", "amount": 1, "currency": "NGN"}
        ).json()["status"]
        == "ignored"
    )
    assert _post(client, "customeridentification.success", {}).json()["status"] == "ignored"


def test_verify_endpoint_and_webhook_behave_identically(client, db, pending_payment, monkeypatch):
    """verify (customer polling) and the webhook share one settlement function."""
    booking, payment = pending_payment
    customer_id = booking.customer_id

    from app.api.deps import get_current_user
    from app.db.models.user import User
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: db.get(User, customer_id)
    monkeypatch.setattr(
        PaystackService, "verify_transaction", staticmethod(lambda ref: _charge(payment))
    )
    try:
        r = client.get(f"/api/v1/payments/verify/{payment.payment_reference}")
        assert r.status_code == 200
        assert r.json()["paid"] is True
        # then the webhook arrives for the same payment: no-op
        r2 = _post(client, "charge.success", _charge(payment))
        assert r2.json()["message"] == "Payment already processed"
        # and verify again is a no-op too
        assert (
            client.get(f"/api/v1/payments/verify/{payment.payment_reference}").json()["paid"]
            is True
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    db.refresh(booking)
    assert booking.status == BookingStatus.PAID


def test_verify_abandoned_transaction_does_not_mark_failed(
    client, db, pending_payment, monkeypatch
):
    booking, payment = pending_payment
    from app.api.deps import get_current_user
    from app.db.models.user import User
    from app.main import app

    customer_id = booking.customer_id
    app.dependency_overrides[get_current_user] = lambda: db.get(User, customer_id)
    monkeypatch.setattr(
        PaystackService, "verify_transaction", staticmethod(lambda ref: {"status": "abandoned"})
    )
    try:
        r = client.get(f"/api/v1/payments/verify/{payment.payment_reference}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert r.json()["paid"] is False
    db.refresh(payment)
    assert payment.status == PaymentStatus.PENDING


def test_transfer_webhooks_end_to_end(client, db, paystack):
    artisan = make_user(db, UserType.ARTISAN)
    customer = make_user(db, UserType.CLIENT)
    service = make_service(db)
    _, payment = make_withdrawable(db, artisan, customer, service, amount="10000.00")
    db.commit()
    result = wsvc.request_withdrawal(
        db,
        artisan_id=artisan.id,
        amount=Decimal("9000"),
        account_number="0123456789",
        bank_code="057",
        account_name="Jane",
        idempotency_key=None,
    )
    w = result.withdrawal

    ok = {"reference": w.reference, "transfer_code": w.transfer_code, "amount": 900_000}
    assert _post(client, "transfer.success", ok).status_code == 200
    db.expire_all()
    assert db.get(type(w), w.id).status == WithdrawalStatus.SUCCESS
    assert db.get(type(payment), payment.id).status == PaymentStatus.RELEASED

    assert _post(client, "transfer.reversed", {"reference": w.reference}).status_code == 200
    db.expire_all()
    assert db.get(type(w), w.id).status == WithdrawalStatus.REVERSED
    assert db.get(type(payment), payment.id).status == PaymentStatus.SUCCESS
