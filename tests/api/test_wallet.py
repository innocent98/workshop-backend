from decimal import Decimal

import pytest

from app.api.deps import get_current_user
from app.db.models.payment import PaymentStatus
from app.db.models.user import User, UserType
from app.main import app
from app.services import withdrawal_service as wsvc
from tests.factories import make_service, make_user, make_withdrawable

BODY = {
    "amount": "9000.00",
    "account_number": "0123456789",
    "bank_code": "057",
    "account_name": "Jane Artisan",
}


@pytest.fixture
def artisan(db):
    user = make_user(db, UserType.ARTISAN)
    customer = make_user(db, UserType.CLIENT)
    service = make_service(db)
    _, payment = make_withdrawable(db, user, customer, service, amount="10000.00")
    _, payment2 = make_withdrawable(db, user, customer, service, amount="10000.00", paid_days_ago=2)
    db.commit()
    user_id = user.id
    app.dependency_overrides[get_current_user] = lambda: db.get(User, user_id)
    yield user
    app.dependency_overrides.pop(get_current_user, None)


def test_balance_before_and_after_withdrawal(client, artisan, paystack):
    before = client.get("/api/v1/wallet/balance").json()
    assert Decimal(before["pending_release"]) == Decimal("18000.00")
    assert Decimal(before["available_balance"]) == Decimal("18000.00")
    assert Decimal(before["pending_withdrawal"]) == 0
    # original field names are all still present
    for key in (
        "total_earned",
        "pending_release",
        "total_platform_fee",
        "total_jobs_completed",
        "total_jobs_paid",
        "lifetime_earnings",
    ):
        assert key in before

    r = client.post("/api/v1/wallet/payout/request", json=BODY)
    assert r.status_code == 200, r.text

    after = client.get("/api/v1/wallet/balance").json()
    assert Decimal(after["pending_release"]) == Decimal("9000.00")
    assert Decimal(after["pending_withdrawal"]) == Decimal("9000.00")
    assert Decimal(after["total_earned"]) == 0  # nothing released until transfer.success


def test_payout_request_response_states_actual_amount_and_replays(client, artisan, paystack):
    headers = {"Idempotency-Key": "double-tap-1"}
    body = dict(BODY, amount="13000.00")  # only one 9000 payment fits

    first = client.post("/api/v1/wallet/payout/request", json=body, headers=headers)
    second = client.post("/api/v1/wallet/payout/request", json=body, headers=headers)

    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert Decimal(a["amount"]) == Decimal("9000.00")  # actual, not requested
    assert Decimal(a["requested_amount"]) == Decimal("13000.00")
    assert a["status"] == "processing"
    assert a["payout_reference"].startswith("wdr_")
    assert a["idempotent_replay"] is False and b["idempotent_replay"] is True
    assert a["withdrawal_id"] == b["withdrawal_id"]
    assert len(paystack.transfer_calls) == 1


def test_payout_no_fit_is_400_with_hint(client, artisan, paystack):
    r = client.post("/api/v1/wallet/payout/request", json=dict(BODY, amount="5000.00"))
    assert r.status_code == 400
    assert "₦9,000.00" in r.json()["detail"]


def test_payout_below_minimum(client, artisan, paystack):
    r = client.post("/api/v1/wallet/payout/request", json=dict(BODY, amount="100.00"))
    assert r.status_code == 400
    assert "Minimum payout" in r.json()["detail"]


def test_payouts_and_earnings_expose_withdrawals(client, artisan, paystack, db):
    client.post("/api/v1/wallet/payout/request", json=BODY)
    payouts = client.get("/api/v1/wallet/payouts").json()
    assert payouts["payouts"] == []  # nothing RELEASED yet (original shape preserved)
    assert len(payouts["withdrawals"]) == 1
    assert payouts["withdrawals"][0]["status"] == "processing"
    assert payouts["withdrawals"][0]["account_number_last4"] == "6789"

    earnings = client.get("/api/v1/wallet/earnings").json()
    linked = [e for e in earnings["earnings"] if e["withdrawal_id"] is not None]
    assert len(linked) == 1 and linked[0]["withdrawal_status"] == "processing"
    assert linked[0]["status"] == "success"

    stats = client.get("/api/v1/wallet/stats").json()
    assert stats["total_transactions"] == 2
    assert stats["pending_withdrawal"] == "9000.00"
    assert stats["available_balance"] == "9000.00"


def test_released_payments_show_in_payouts_after_transfer_success(client, artisan, paystack, db):
    r = client.post("/api/v1/wallet/payout/request", json=BODY).json()
    ref = r["payout_reference"]
    wsvc.settle_transfer_success(db, {"reference": ref, "amount": 900_000})
    payouts = client.get("/api/v1/wallet/payouts").json()
    assert len(payouts["payouts"]) == 1
    assert payouts["payouts"][0]["payout_reference"].startswith(ref)
    assert payouts["withdrawals"][0]["status"] == "success"
    bal = client.get("/api/v1/wallet/balance").json()
    assert Decimal(bal["total_earned"]) == Decimal("9000.00")
    assert Decimal(bal["pending_withdrawal"]) == 0


def test_only_artisans_can_use_the_wallet(client, db):
    customer = make_user(db, UserType.CLIENT)
    db.commit()
    cid = customer.id
    app.dependency_overrides[get_current_user] = lambda: db.get(User, cid)
    try:
        assert client.get("/api/v1/wallet/balance").status_code == 403
        assert client.post("/api/v1/wallet/payout/request", json=BODY).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_release_endpoint_is_forbidden_for_everyone(client, artisan, db):
    from app.db.models.payment import Payment

    payment = db.query(Payment).first()
    r = client.post(f"/api/v1/payments/{payment.id}/release", json={})
    assert r.status_code == 403
    db.refresh(payment)
    assert payment.status == PaymentStatus.SUCCESS  # nothing was released
