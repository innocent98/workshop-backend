from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.models.booking import BookingStatus
from app.db.models.payment import PaymentStatus
from app.db.models.user import UserType
from app.db.models.withdrawal import Withdrawal, WithdrawalStatus
from app.services import withdrawal_service as svc
from app.services.paystack import PaystackError
from tests.factories import make_booking, make_payment, make_service, make_user, make_withdrawable

ACCT = {"account_number": "0123456789", "bank_code": "057", "account_name": "Jane Artisan"}


@pytest.fixture
def world(db):
    artisan = make_user(db, UserType.ARTISAN)
    customer = make_user(db, UserType.CLIENT)
    service = make_service(db)
    db.commit()
    return artisan, customer, service


def _fund(db, world, *amounts):
    """Create one withdrawable payment per gross amount; artisan gets 90% of each."""
    artisan, customer, service = world
    payments = []
    for i, gross in enumerate(amounts):
        _, payment = make_withdrawable(
            db, artisan, customer, service, amount=gross, paid_days_ago=len(amounts) - i
        )
        payments.append(payment)
    db.commit()
    return payments


def _request(db, artisan, amount, key=None, **overrides):
    args = dict(ACCT, **overrides)
    return svc.request_withdrawal(
        db, artisan_id=artisan.id, amount=Decimal(amount), idempotency_key=key, **args
    )


# ----------------------------------------------------------------- selection (pure)


class _P:
    def __init__(self, amount):
        self.artisan_amount = Decimal(amount)


def test_select_payments_oldest_first_whole_payments_only():
    payments = [_P("4000"), _P("3000"), _P("2500")]
    chosen = svc.select_payments(payments, Decimal("7000"))
    assert [p.artisan_amount for p in chosen] == [Decimal("4000"), Decimal("3000")]


def test_select_payments_skips_a_payment_that_does_not_fit():
    payments = [_P("9000"), _P("2000"), _P("1500")]
    chosen = svc.select_payments(payments, Decimal("4000"))
    assert [p.artisan_amount for p in chosen] == [Decimal("2000"), Decimal("1500")]


def test_select_payments_never_exceeds_requested():
    payments = [_P("6000"), _P("6000")]
    assert svc.select_payments(payments, Decimal("5000")) == []
    assert svc.select_payments(payments, Decimal("12000")) == payments


# ----------------------------------------------------------------- balance


def test_available_balance_excludes_unconfirmed_disputed_and_linked(db, world, paystack):
    artisan, customer, service = world
    _fund(db, world, "10000.00")  # 9000 available
    # not completed yet
    b = make_booking(db, artisan, customer, service, status=BookingStatus.PAID)
    make_payment(db, b, status=PaymentStatus.SUCCESS)
    # completed but inside dispute window, unconfirmed
    b = make_booking(
        db, artisan, customer, service, status=BookingStatus.COMPLETED, deadline_hours=5
    )
    make_payment(db, b, status=PaymentStatus.SUCCESS)
    # disputed
    b = make_booking(
        db,
        artisan,
        customer,
        service,
        status=BookingStatus.COMPLETED,
        disputed=True,
        deadline_hours=-5,
    )
    make_payment(db, b, status=PaymentStatus.SUCCESS)
    # window elapsed, no response -> available
    b = make_booking(
        db, artisan, customer, service, status=BookingStatus.COMPLETED, deadline_hours=-5
    )
    make_payment(
        db,
        b,
        amount="10000.00",
        status=PaymentStatus.SUCCESS,
        paid_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.commit()

    assert svc.available_balance(db, artisan.id) == Decimal("18000.00")

    _request(db, artisan, "9000")
    assert svc.available_balance(db, artisan.id) == Decimal("9000.00")
    assert svc.pending_withdrawal_amount(db, artisan.id) == Decimal("9000.00")


# ----------------------------------------------------------------- request


def test_request_creates_one_withdrawal_one_transfer_for_many_payments(db, world, paystack):
    artisan, _, _ = world
    payments = _fund(db, world, "10000.00", "10000.00", "10000.00")  # 9000 each

    result = _request(db, artisan, "18500")  # fits two whole payments (18000)

    w = result.withdrawal
    assert w.amount == Decimal("18000.00")
    assert w.status == WithdrawalStatus.PROCESSING
    assert w.account_number_last4 == "6789"
    assert result.payments_count == 2
    assert len(paystack.transfer_calls) == 1  # ONE transfer, not one per payment
    assert paystack.transfer_calls[0]["amount"] == Decimal("18000.00")
    assert paystack.transfer_calls[0]["reference"] == w.reference
    assert w.transfer_code == "TRF_1"
    for p in payments:
        db.refresh(p)
    assert [p.withdrawal_id for p in payments] == [w.id, w.id, None]
    # payments stay SUCCESS until the transfer is confirmed
    assert {p.status for p in payments} == {PaymentStatus.SUCCESS}


def test_below_minimum_is_rejected(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "4999")
    assert exc.value.status_code == 400
    assert "Minimum payout" in exc.value.detail
    assert paystack.transfer_calls == []


def test_transferred_total_must_also_meet_the_minimum(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "2000.00", "2000.00")  # 1800 each, 3600 withdrawable in total
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "5000")  # requested >= minimum, but only 3600 fits
    assert exc.value.status_code == 400
    assert "below the minimum payout" in exc.value.detail
    assert paystack.verify_calls == [] and paystack.transfer_calls == []
    assert db.query(Withdrawal).count() == 0


def test_min_payout_is_a_setting(db, world, paystack, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MIN_PAYOUT_NGN", Decimal("100.00"))
    artisan, _, _ = world
    _fund(db, world, "1000.00")  # 900 available
    assert _request(db, artisan, "900").withdrawal.amount == Decimal("900.00")


def test_no_fit_returns_400_with_nearest_withdrawable_amount(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "20000.00", "30000.00")  # 18000 and 27000
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "10000")
    assert exc.value.status_code == 400
    assert "₦18,000.00" in exc.value.detail
    assert paystack.transfer_calls == []


def test_no_balance_at_all(db, world, paystack):
    artisan, _, _ = world
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "6000")
    assert exc.value.status_code == 400
    assert "no withdrawable balance" in exc.value.detail


def test_idempotency_key_replays_instead_of_creating_a_second_withdrawal(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00", "10000.00")
    first = _request(db, artisan, "9000", key="tap-1")
    second = _request(db, artisan, "9000", key="tap-1")

    assert second.replay is True
    assert second.withdrawal.id == first.withdrawal.id
    assert db.query(Withdrawal).count() == 1
    assert len(paystack.transfer_calls) == 1
    assert len(paystack.verify_calls) == 1  # replay short-circuits before Paystack


def test_idempotency_key_reuse_with_different_account_is_conflict(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00", "10000.00")
    _request(db, artisan, "9000", key="k")
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "9000", key="k", account_number="0999999999")
    assert exc.value.status_code == 409


def test_same_payment_cannot_be_withdrawn_twice_without_a_key(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")
    _request(db, artisan, "9000")
    with pytest.raises(svc.WithdrawalError):
        _request(db, artisan, "9000")
    assert len(paystack.transfer_calls) == 1


def test_account_verification_failure_creates_nothing_and_hides_paystack_error(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")
    paystack.verify_error = PaystackError("Could not resolve account name SECRET-DETAIL", 422)
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "9000")
    assert "SECRET-DETAIL" not in exc.value.detail
    assert db.query(Withdrawal).count() == 0


def test_definitive_transfer_rejection_gives_funds_back(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")
    paystack.transfer_error = PaystackError("Your balance is not enough SECRET", status_code=400)
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "9000")
    assert exc.value.status_code == 502
    assert "SECRET" not in exc.value.detail
    w = db.query(Withdrawal).one()
    assert w.status == WithdrawalStatus.FAILED
    assert svc.available_balance(db, artisan.id) == Decimal("9000.00")


def test_ambiguous_transfer_failure_stays_processing(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")
    paystack.transfer_error = PaystackError("timeout")  # no status code: outcome unknown
    result = _request(db, artisan, "9000")
    assert result.withdrawal.status == WithdrawalStatus.PROCESSING
    assert result.withdrawal.transfer_code is None  # never confirmed by Paystack
    assert svc.available_balance(db, artisan.id) == Decimal("0")  # still locked up


def test_otp_transfer_stays_processing_and_keeps_payments_locked(db, world, paystack):
    """The transfer exists at Paystack: freeing the payments would allow a double payout."""
    artisan, _, _ = world
    _fund(db, world, "10000.00")
    paystack.transfer_status = "otp"
    result = _request(db, artisan, "9000")
    assert result.withdrawal.status == WithdrawalStatus.PROCESSING
    assert result.withdrawal.transfer_code == "TRF_1"
    assert "OTP" in result.withdrawal.failure_reason
    assert svc.available_balance(db, artisan.id) == Decimal("0")


def test_replay_with_different_amount_is_conflict(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00", "10000.00")
    first = _request(db, artisan, "9000", key="amt")
    assert first.withdrawal.requested_amount == Decimal("9000")
    with pytest.raises(svc.WithdrawalError) as exc:
        _request(db, artisan, "18000", key="amt")
    assert exc.value.status_code == 409
    assert len(paystack.transfer_calls) == 1


# ----------------------------------------------------------------- settlement


def _processing(db, world, paystack, *gross):
    artisan, _, _ = world
    payments = _fund(db, world, *gross)
    result = _request(db, artisan, "100000")
    return artisan, payments, result.withdrawal


def test_transfer_success_releases_payments_and_is_idempotent(db, world, paystack, notifications):
    artisan, payments, w = _processing(db, world, paystack, "10000.00", "10000.00")
    notifications.clear()
    data = {"reference": w.reference, "transfer_code": w.transfer_code, "amount": 1_800_000}

    assert svc.settle_transfer_success(db, data) == "processed"
    assert svc.settle_transfer_success(db, data) == "already_processed"

    db.refresh(w)
    assert w.status == WithdrawalStatus.SUCCESS and w.completed_at is not None
    for p in payments:
        db.refresh(p)
        assert p.status == PaymentStatus.RELEASED
        assert p.released_at is not None
        assert p.payout_reference.startswith(w.reference)
    assert len({p.payout_reference for p in payments}) == 2  # column is unique
    assert len(notifications) == 1  # only the first delivery notifies


@pytest.mark.parametrize(
    "extra",
    [{"amount": 1}, {}, {"amount": 900_000, "currency": "USD"}],
    ids=["amount-mismatch", "amount-missing", "currency-mismatch"],
)
def test_transfer_success_with_bad_amount_or_currency_needs_review(
    db, world, paystack, notifications, extra
):
    artisan, payments, w = _processing(db, world, paystack, "10000.00")
    notifications.clear()
    assert svc.settle_transfer_success(db, {"reference": w.reference, **extra}) == "needs_review"
    db.refresh(w), db.refresh(payments[0])
    assert w.status == WithdrawalStatus.NEEDS_REVIEW
    assert payments[0].status == PaymentStatus.SUCCESS and payments[0].withdrawal_id == w.id
    assert svc.available_balance(db, artisan.id) == Decimal("0")  # still locked
    assert len(notifications) == 1


def test_pending_withdrawal_counts_needs_review_money_that_is_still_linked(db, world, paystack):
    artisan, _, w = _processing(db, world, paystack, "10000.00")
    svc.settle_transfer_success(db, {"reference": w.reference})  # missing amount
    assert svc.pending_withdrawal_amount(db, artisan.id) == Decimal("9000.00")


@pytest.mark.parametrize("first", [WithdrawalStatus.FAILED, WithdrawalStatus.REVERSED])
def test_transfer_success_after_failed_or_reversed_is_flagged_not_ignored(
    db, world, paystack, notifications, first, caplog
):
    artisan, payments, w = _processing(db, world, paystack, "10000.00")
    svc.settle_transfer_failure(db, {"reference": w.reference}, first)
    notifications.clear()

    result = svc.settle_transfer_success(db, {"reference": w.reference, "amount": 900_000})

    assert result == "needs_review"
    db.refresh(w)
    assert w.status == WithdrawalStatus.NEEDS_REVIEW
    assert first.value in w.failure_reason
    assert len(notifications) == 1
    # a second delivery is a no-op
    assert svc.settle_transfer_success(db, {"reference": w.reference, "amount": 900_000}) == (
        "already_processed"
    )


def test_transfer_success_unknown_reference(db):
    assert svc.settle_transfer_success(db, {"reference": "nope"}) == "not_found"


def test_transfer_failed_returns_money_to_balance_and_notifies(db, world, paystack, notifications):
    artisan, payments, w = _processing(db, world, paystack, "10000.00", "10000.00")
    notifications.clear()
    data = {"reference": w.reference, "reason": "Recipient bank unavailable"}

    assert svc.settle_transfer_failure(db, data, WithdrawalStatus.FAILED) == "processed"
    assert svc.settle_transfer_failure(db, data, WithdrawalStatus.FAILED) == "already_processed"

    db.refresh(w)
    assert w.status == WithdrawalStatus.FAILED
    assert w.failure_reason == "Recipient bank unavailable"
    for p in payments:
        db.refresh(p)
        assert p.withdrawal_id is None and p.status == PaymentStatus.SUCCESS
    assert svc.available_balance(db, artisan.id) == Decimal("18000.00")
    assert svc.pending_withdrawal_amount(db, artisan.id) == Decimal("0")
    assert len(notifications) == 1
    assert notifications[0]["user_id"] == str(artisan.id)

    # the freed money can be withdrawn again
    assert _request(db, artisan, "18000").withdrawal.amount == Decimal("18000.00")


def test_transfer_reversed_after_success_restores_payments(db, world, paystack):
    artisan, payments, w = _processing(db, world, paystack, "10000.00")
    svc.settle_transfer_success(db, {"reference": w.reference, "amount": 900_000})
    assert svc.settle_transfer_failure(
        db, {"reference": w.reference}, WithdrawalStatus.REVERSED
    ) == ("processed")
    db.refresh(w), db.refresh(payments[0])
    assert w.status == WithdrawalStatus.REVERSED
    assert payments[0].status == PaymentStatus.SUCCESS
    assert payments[0].released_at is None and payments[0].payout_reference is None
    assert svc.available_balance(db, artisan.id) == Decimal("9000.00")


def test_failed_event_after_success_is_ignored(db, world, paystack):
    _, payments, w = _processing(db, world, paystack, "10000.00")
    svc.settle_transfer_success(db, {"reference": w.reference, "amount": 900_000})
    assert (
        svc.settle_transfer_failure(db, {"reference": w.reference}, WithdrawalStatus.FAILED)
        == "ignored"
    )
    db.refresh(payments[0])
    assert payments[0].status == PaymentStatus.RELEASED


def test_settlement_finds_withdrawal_by_transfer_code(db, world, paystack):
    _, _, w = _processing(db, world, paystack, "10000.00")
    data = {"transfer_code": w.transfer_code, "amount": 900_000}
    assert svc.settle_transfer_success(db, data) == "processed"


# ----------------------------------------------------------------- real concurrency


def _race(artisan_id, keys):
    """Fire one request per key at the same instant from separate DB sessions."""
    import threading

    from tests.conftest import TestingSessionLocal

    barrier = threading.Barrier(len(keys))
    results = []

    def worker(key):
        session = TestingSessionLocal()
        try:
            barrier.wait()
            r = svc.request_withdrawal(
                session,
                artisan_id=artisan_id,
                amount=Decimal("9000"),
                idempotency_key=key,
                **ACCT,
            )
            results.append(("ok", r.withdrawal.id, r.replay))
        except svc.WithdrawalError as exc:
            results.append(("err", exc.status_code, None))
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    return results


def test_concurrent_double_tap_with_same_key_returns_one_withdrawal(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")

    results = _race(artisan.id, ["same-key", "same-key"])

    assert [r[0] for r in results] == ["ok", "ok"]
    assert len({r[1] for r in results}) == 1  # same withdrawal id
    assert sorted(r[2] for r in results) == [False, True]  # one real, one replay
    assert len(paystack.transfer_calls) == 1
    assert db.query(Withdrawal).count() == 1


def test_concurrent_requests_without_a_key_cannot_double_spend(db, world, paystack):
    artisan, _, _ = world
    _fund(db, world, "10000.00")

    results = _race(artisan.id, [None, None])

    assert sorted(r[0] for r in results) == ["err", "ok"]
    assert len(paystack.transfer_calls) == 1
    assert db.query(Withdrawal).count() == 1


# ----------------------------------------------------------------- reconciliation


def _age(db, withdrawal, minutes):
    withdrawal.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db.commit()


def test_reconcile_settles_success(db, world, paystack):
    artisan, payments, w = _processing(db, world, paystack, "10000.00")
    _age(db, w, 30)
    paystack.transfer_verify[w.reference] = {
        "status": "success",
        "amount": 900_000,
        "transfer_code": "TRF_1",
    }
    assert svc.reconcile_processing_withdrawals(db)["success"] == 1
    db.refresh(w), db.refresh(payments[0])
    assert w.status == WithdrawalStatus.SUCCESS
    assert payments[0].status == PaymentStatus.RELEASED


@pytest.mark.parametrize(
    "paystack_status,expected",
    [
        ("failed", WithdrawalStatus.FAILED),
        ("rejected", WithdrawalStatus.FAILED),
        ("reversed", WithdrawalStatus.REVERSED),
    ],
)
def test_reconcile_failed_frees_the_money(db, world, paystack, paystack_status, expected):
    artisan, payments, w = _processing(db, world, paystack, "10000.00")
    _age(db, w, 30)
    paystack.transfer_verify[w.reference] = {"status": paystack_status, "amount": 900_000}
    svc.reconcile_processing_withdrawals(db)
    db.refresh(w)
    assert w.status == expected
    assert svc.available_balance(db, artisan.id) == Decimal("9000.00")


def test_reconcile_transfer_that_does_not_exist_is_failed_and_unlinked(db, world, paystack):
    """Timeout where the transfer never reached Paystack (verify answers 404)."""
    artisan, payments, w = _processing(db, world, paystack, "10000.00")
    _age(db, w, 30)
    summary = svc.reconcile_processing_withdrawals(db)  # no entry -> FakePaystack raises 404
    assert summary["not_found"] == 1
    db.refresh(w)
    assert w.status == WithdrawalStatus.FAILED
    assert svc.available_balance(db, artisan.id) == Decimal("9000.00")


def test_reconcile_leaves_pending_otp_young_and_errors_alone(db, world, paystack):
    artisan, payments, w = _processing(db, world, paystack, "10000.00", "10000.00")
    other = db.query(Withdrawal).count()
    assert other == 1
    _age(db, w, 5)  # younger than the threshold: not even looked at
    assert svc.reconcile_processing_withdrawals(db)["checked"] == 0
    assert paystack.transfer_verify_calls == []

    _age(db, w, 30)
    for result in (
        {"status": "pending"},
        {"status": "otp"},
        PaystackError("boom", 500),
        PaystackError("net down"),
    ):
        paystack.transfer_verify[w.reference] = result
        svc.reconcile_processing_withdrawals(db)
        db.refresh(w)
        assert w.status == WithdrawalStatus.PROCESSING


def test_reconcile_ignores_non_processing_withdrawals(db, world, paystack):
    _, _, w = _processing(db, world, paystack, "10000.00")
    svc.settle_transfer_success(db, {"reference": w.reference, "amount": 900_000})
    _age(db, w, 60)
    assert svc.reconcile_processing_withdrawals(db)["checked"] == 0
