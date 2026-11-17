"""Refund safety: intent is committed before Paystack is called, ambiguous outcomes are reconciled
against Paystack, release_to_artisan is blocked while any refund exists, and Paystack's async
refund events are applied."""

import pytest
from sqlalchemy import text

from app.db.models.admin import DisputeResolution
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.user import UserType
from app.services.admin import handle_refund_event
from app.services.paystack import PaystackError, PaystackService
from tests.admin.conftest import make_booking, make_user
from tests.conftest import engine

TIMEOUT = PaystackError("Paystack API request failed: timeout")  # no status code: ambiguous
ALREADY_REVERSED = PaystackError("Transaction has been fully reversed", status_code=400)


class FakePaystack:
    """Scripted PaystackService.refund / list_refunds. Items are results or exceptions."""

    def __init__(self, monkeypatch):
        self.refunds = []  # script for refund()
        self.lists = []  # script for list_refunds()
        self.refund_calls = []
        self.list_calls = []
        self.on_refund = None  # hook run inside refund() before answering
        monkeypatch.setattr(PaystackService, "refund", staticmethod(self._refund))
        monkeypatch.setattr(PaystackService, "list_refunds", staticmethod(self._list))

    def _refund(self, transaction_reference, **kw):
        self.refund_calls.append(transaction_reference)
        if self.on_refund:
            self.on_refund()
        item = self.refunds.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def _list(self, transaction_reference):
        self.list_calls.append(transaction_reference)
        item = self.lists.pop(0) if self.lists else []
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def ps(monkeypatch):
    return FakePaystack(monkeypatch)


@pytest.fixture()
def disputed(db, service):
    return make_booking(db, service, make_user(db), make_user(db, user_type=UserType.ARTISAN))


def resolve(client, headers, booking_id, resolution="refund_customer", note="Artisan no-show"):
    return client.post(
        f"/api/v1/admin/bookings/{booking_id}/resolve-dispute",
        headers=headers,
        json={"resolution": resolution, "note": note},
    )


def states(db, booking_id):
    db.expire_all()
    b = db.get(Booking, booking_id)
    p = db.query(Payment).one()
    r = db.query(DisputeResolution).first()
    return b.status, p.status, (r.refund_status if r else None)


# ------------------------------------------------------- intent before the call


def test_refund_intent_is_committed_before_paystack_is_called(client, db, admin_h, disputed, ps):
    seen = {}

    def peek():
        with engine.connect() as other:  # a different connection sees only COMMITTED rows
            seen["row"] = other.execute(
                text("select refund_status from dispute_resolutions")
            ).fetchall()

    ps.on_refund = peek
    ps.refunds = [{"id": 4242, "status": "pending"}]
    assert resolve(client, admin_h, disputed.id).status_code == 200
    assert seen["row"] == [("requested",)]


def test_successful_refund_completes_with_status(client, db, admin_h, disputed, ps, notifications):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    r = resolve(client, admin_h, disputed.id)
    body = r.json()
    assert r.status_code == 200
    assert body["refund_status"] == "pending" and body["refund_reference"] == "4242"
    assert body["booking_status"] == "cancelled" and body["payment_status"] == "refunded"
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")


# ------------------------------------------------- ambiguous outcomes: reconcile


def test_timeout_after_paystack_processed_is_reconciled_not_lost(client, db, admin_h, disputed, ps):
    ps.refunds = [TIMEOUT]
    ps.lists = [[{"id": 77, "status": "processed"}]]  # Paystack did process it
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 200, r.text
    assert r.json()["refund_reference"] == "77" and r.json()["refund_status"] == "processed"
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "processed")
    assert ps.list_calls == [db.query(Payment).one().paystack_reference]


def test_timeout_and_nothing_found_keeps_intent_and_blocks_release(
    client, db, admin_h, disputed, ps
):
    ps.refunds = [TIMEOUT]
    ps.lists = [[]]
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "refund_unconfirmed"
    # still disputed / held, but the refund intent exists
    assert states(db, disputed.id) == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS, "requested")

    # the double-spend: releasing now would pay the artisan money that may have been refunded
    rel = resolve(client, admin_h, disputed.id, "release_to_artisan")
    assert rel.status_code == 409 and rel.json()["detail"]["code"] == "refund_in_progress"
    db.expire_all()
    b = db.get(Booking, disputed.id)
    assert b.completion_confirmed_by_client_at is None and b.completion_disputed_at is not None


def test_retry_after_unconfirmed_refund_goes_through(client, db, admin_h, disputed, ps):
    ps.refunds = [TIMEOUT, {"id": 9, "status": "pending"}]
    ps.lists = [[], []]
    assert resolve(client, admin_h, disputed.id).status_code == 502
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 200 and r.json()["already_resolved"] is False
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")
    assert len(ps.refund_calls) == 2


def test_reconcile_call_failing_keeps_intent(client, db, admin_h, disputed, ps):
    ps.refunds = [TIMEOUT]
    ps.lists = [PaystackError("also down")]
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "refund_unconfirmed"
    assert states(db, disputed.id)[2] == "requested"
    assert resolve(client, admin_h, disputed.id, "release_to_artisan").status_code == 409


def test_definite_rejection_with_no_refund_found_rolls_the_intent_back(
    client, db, admin_h, disputed, ps
):
    ps.refunds = [PaystackError("Transaction not found", status_code=404)]
    ps.lists = [[]]
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "refund_failed"
    assert db.query(DisputeResolution).count() == 0
    assert states(db, disputed.id)[:2] == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS)
    # nothing was refunded, so the admin may now release instead
    assert resolve(client, admin_h, disputed.id, "release_to_artisan").status_code == 200


def test_already_reversed_rejection_is_reconciled_to_the_existing_refund(
    client, db, admin_h, disputed, ps
):
    ps.refunds = [ALREADY_REVERSED]
    ps.lists = [[{"id": 55, "status": "processing"}]]
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 200 and r.json()["refund_reference"] == "55"
    assert states(db, disputed.id) == (
        BookingStatus.CANCELLED,
        PaymentStatus.REFUNDED,
        "processing",
    )


def test_failed_refund_in_list_is_not_treated_as_success(client, db, admin_h, disputed, ps):
    ps.refunds = [TIMEOUT]
    ps.lists = [[{"id": 1, "status": "failed"}]]
    assert resolve(client, admin_h, disputed.id).status_code == 502
    assert states(db, disputed.id)[:2] == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS)


def test_commit_failure_after_paystack_success_cannot_lead_to_a_release(
    client, db, admin_h, disputed, ps, monkeypatch
):
    from app.services import admin as admin_service

    ps.refunds = [{"id": 4242, "status": "pending"}, ALREADY_REVERSED]
    ps.lists = [[{"id": 4242, "status": "pending"}]]
    real = admin_service._complete_refund
    monkeypatch.setattr(
        admin_service,
        "_complete_refund",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    with pytest.raises(RuntimeError):
        resolve(client, admin_h, disputed.id)
    # money is on its way back to the customer but the DB never heard: intent protects it
    assert states(db, disputed.id) == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS, "requested")
    assert resolve(client, admin_h, disputed.id, "release_to_artisan").status_code == 409

    monkeypatch.setattr(admin_service, "_complete_refund", real)
    r = resolve(
        client, admin_h, disputed.id
    )  # retry: Paystack says "already reversed" -> reconcile
    assert r.status_code == 200
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")


@pytest.mark.parametrize("final", ["pending", "processing", "processed"])
def test_release_blocked_for_every_accepted_refund_state(client, db, admin_h, disputed, ps, final):
    ps.refunds = [{"id": 4242, "status": final}]
    assert resolve(client, admin_h, disputed.id).status_code == 200
    rel = resolve(client, admin_h, disputed.id, "release_to_artisan")
    assert rel.status_code == 409


def test_repeating_an_accepted_refund_is_idempotent(client, db, admin_h, disputed, ps):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    again = resolve(client, admin_h, disputed.id)
    assert again.status_code == 200 and again.json()["already_resolved"] is True
    assert len(ps.refund_calls) == 1


# ------------------------------------------------------------- async refund events


def test_refund_events_update_status_and_never_regress(client, db, admin_h, disputed, ps):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference

    assert (
        handle_refund_event(db, "refund.processing", {"transaction_reference": ref}) == "processing"
    )
    assert states(db, disputed.id)[2] == "processing"
    assert (
        handle_refund_event(db, "refund.processed", {"transaction_reference": ref}) == "processed"
    )
    # late/duplicate earlier event must not move a processed refund backwards
    assert handle_refund_event(db, "refund.pending", {"transaction_reference": ref}) == "processed"
    assert handle_refund_event(db, "refund.failed", {"transaction_reference": ref}) == "processed"
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "processed")


def test_refund_failed_event_reopens_the_dispute_for_retry_or_release(
    client, db, admin_h, disputed, ps
):
    ps.refunds = [{"id": 4242, "status": "pending"}, {"id": 4243, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference

    ps.lists = [[{"id": 4242, "status": "failed"}]]
    assert handle_refund_event(db, "refund.failed", {"transaction": {"reference": ref}}) == "failed"
    assert states(db, disputed.id) == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS, "failed")
    db.expire_all()
    assert db.get(Booking, disputed.id).cancelled_at is None
    assert db.query(Payment).one().refunded_at is None

    # admin retries the refund...
    r = resolve(client, admin_h, disputed.id)
    assert r.status_code == 200 and r.json()["already_resolved"] is False
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")


def test_release_allowed_after_a_confirmed_failed_refund(client, db, admin_h, disputed, ps):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference
    ps.lists = [[{"id": 4242, "status": "failed"}]]
    handle_refund_event(db, "refund.failed", {"transaction_reference": ref})
    r = resolve(client, admin_h, disputed.id, "release_to_artisan", note="Refund failed; releasing")
    assert r.status_code == 200 and r.json()["resolution"] == "release_to_artisan"
    assert r.json()["refund_status"] is None
    db.expire_all()
    b = db.get(Booking, disputed.id)
    assert b.status == BookingStatus.COMPLETED and b.completion_disputed_at is None
    assert db.query(DisputeResolution).count() == 1


def test_stale_failed_event_for_an_earlier_refund_cannot_reopen_a_live_retry(
    client, db, admin_h, disputed, ps
):
    """refund #1 failed, the admin retried (refund #2 live), then #1's failed event arrives late."""
    ps.refunds = [{"id": 1, "status": "pending"}, {"id": 2, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference
    ps.lists = [[{"id": 1, "status": "failed"}]]
    assert (
        handle_refund_event(db, "refund.failed", {"transaction_reference": ref, "id": 1})
        == "failed"
    )
    resolve(client, admin_h, disputed.id)  # retry -> refund #2
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")

    ps.lists = []  # would say "nothing live" if it were consulted: it must not even be reached
    out = handle_refund_event(db, "refund.failed", {"transaction_reference": ref, "id": 1})
    assert out == "pending"
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")
    assert resolve(client, admin_h, disputed.id, "release_to_artisan").status_code == 409


def test_failed_event_is_ignored_while_a_retry_is_in_flight(client, db, admin_h, disputed, ps):
    """status 'requested' = a refund call is in flight (or its outcome unknown): a failed event
    must not reopen the dispute, even if Paystack's list says nothing live exists yet."""
    ps.refunds = [TIMEOUT]
    ps.lists = [[]]
    assert resolve(client, admin_h, disputed.id).status_code == 502  # stays 'requested'
    ref = db.query(Payment).one().paystack_reference
    ps.lists = [[]]  # "nothing live" at check time
    out = handle_refund_event(db, "refund.failed", {"transaction_reference": ref})
    assert out == "requested"
    assert states(db, disputed.id) == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS, "requested")
    assert resolve(client, admin_h, disputed.id, "release_to_artisan").status_code == 409


def test_failed_event_is_ignored_when_paystack_lists_a_live_refund(
    client, db, admin_h, disputed, ps
):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference
    ps.lists = [[{"id": 4242, "status": "processing"}]]  # event lies / is stale
    out = handle_refund_event(db, "refund.failed", {"transaction_reference": ref})
    assert out == "pending"
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")


def test_failed_event_not_applied_when_paystack_cannot_confirm(client, db, admin_h, disputed, ps):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference
    ps.lists = [PaystackError("down")]
    assert handle_refund_event(db, "refund.failed", {"transaction_reference": ref}) == "pending"
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "pending")


def test_refund_event_for_unknown_transaction_is_ignored(db):
    assert handle_refund_event(db, "refund.processed", {"transaction_reference": "nope"}) is None
    assert handle_refund_event(db, "refund.processed", {}) is None
    assert handle_refund_event(db, "charge.success", {"transaction_reference": "x"}) is None


# ------------------------------------------------------------- PaystackService


def test_paystack_refund_request_and_error_classification(monkeypatch):
    import requests

    seen = {}

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._b = status, body

        def raise_for_status(self):
            if self.status_code >= 400:
                err = requests.HTTPError("boom")
                err.response = self
                raise err

        def json(self):
            return self._b

    def ok_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json)
        return Resp(200, {"status": True, "data": {"id": 5, "status": "pending"}})

    monkeypatch.setattr(requests, "post", ok_post)
    assert PaystackService.refund("ps_ref_1", customer_note="n")["id"] == 5
    assert seen["url"].endswith("/refund") and seen["json"]["transaction"] == "ps_ref_1"

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(400, {"message": "reversed"}))
    with pytest.raises(PaystackError) as e400:
        PaystackService.refund("ps_ref_1")
    assert e400.value.status_code == 400

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(PaystackError) as eno:
        PaystackService.refund("ps_ref_1")
    assert eno.value.status_code is None  # ambiguous


def test_paystack_list_refunds(monkeypatch):
    import requests

    seen = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"status": True, "data": [{"id": 1, "status": "processed"}]}

    def get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params)
        return Resp()

    monkeypatch.setattr(requests, "get", get)
    assert PaystackService.list_refunds("ps_ref_1") == [{"id": 1, "status": "processed"}]
    assert seen["url"].endswith("/refund") and seen["params"] == {"transaction": "ps_ref_1"}


# ---------------------------------------------------- Paystack webhook wiring (payments.py)

WEBHOOK_SECRET = "whsec_refund_test"


def _post_event(client, event, data, secret=WEBHOOK_SECRET):
    import hashlib
    import hmac
    import json

    body = json.dumps({"event": event, "data": data}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return client.post(
        "/api/v1/payments/webhook",
        content=body,
        headers={"x-paystack-signature": sig, "content-type": "application/json"},
    )


@pytest.fixture()
def webhook_secret(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PAYSTACK_WEBHOOK_SECRET", WEBHOOK_SECRET)


def test_refund_webhook_events_drive_status_through_the_real_route(
    client, db, admin_h, disputed, ps, webhook_secret
):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference

    r = _post_event(client, "refund.processed", {"transaction_reference": ref, "id": 4242})
    assert r.status_code == 200 and r.json() == {"status": "success", "message": "Refund processed"}
    assert states(db, disputed.id) == (BookingStatus.CANCELLED, PaymentStatus.REFUNDED, "processed")


def test_refund_failed_webhook_reopens_the_dispute(
    client, db, admin_h, disputed, ps, webhook_secret
):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference

    ps.lists = [[{"id": 4242, "status": "failed"}]]
    r = _post_event(client, "refund.failed", {"transaction_reference": ref})
    assert r.status_code == 200 and r.json()["message"] == "Refund failed"
    assert states(db, disputed.id) == (BookingStatus.DISPUTED, PaymentStatus.SUCCESS, "failed")


def test_refund_webhook_unknown_transaction_is_acknowledged(client, webhook_secret):
    r = _post_event(client, "refund.processed", {"transaction_reference": "not-ours"})
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_refund_webhook_requires_a_valid_paystack_signature(
    client, db, admin_h, disputed, ps, webhook_secret
):
    ps.refunds = [{"id": 4242, "status": "pending"}]
    resolve(client, admin_h, disputed.id)
    ref = db.query(Payment).one().paystack_reference
    r = _post_event(client, "refund.failed", {"transaction_reference": ref}, secret="wrong")
    assert r.status_code == 401
    assert states(db, disputed.id)[2] == "pending"  # untouched
