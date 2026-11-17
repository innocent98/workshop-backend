"""Escrow/payout provider seam: Paystack wire format -> normalised events -> same settlement."""

import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.db.models.payment import PaymentStatus
from app.db.models.user import UserType
from app.services.escrow import UnknownProviderError, get_escrow_provider
from app.services.escrow.base import (
    HoldFailed,
    HoldFunded,
    HoldPending,
    Ignored,
    PayoutFailed,
    PayoutSucceeded,
    RefundUpdated,
    WebhookRejected,
)
from app.services.escrow.paystack import PaystackEscrowProvider
from app.services.payment_service import (
    OUTCOME_ALREADY,
    OUTCOME_MISMATCH,
    OUTCOME_PROCESSED,
    apply_charge_success,
)
from app.services.payout import get_payout_provider
from app.services.payout.paystack import PaystackPayoutProvider
from app.services.paystack import PaystackError, PaystackService
from app.services.provider_errors import DuplicateReferenceError, ProviderError
from tests.factories import make_booking, make_payment, make_service, make_user

SECRET = "whsec_seam"


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_WEBHOOK_SECRET", SECRET)


def _signed(event, data):
    body = json.dumps({"event": event, "data": data}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    return {"X-Paystack-Signature": sig}, body


def _parse(event, data):
    headers, body = _signed(event, data)
    return PaystackEscrowProvider().verify_and_parse_webhook(headers, body)


# ---- registry -------------------------------------------------------------------------------


def test_registry_defaults_to_paystack(monkeypatch):
    monkeypatch.setattr(settings, "ESCROW_PROVIDER", "paystack")
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER", "paystack")
    assert isinstance(get_escrow_provider(), PaystackEscrowProvider)
    assert isinstance(get_payout_provider(), PaystackPayoutProvider)


def test_registry_fails_fast_on_an_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "ESCROW_PROVIDER", "nope")
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER", "nope")
    with pytest.raises(UnknownProviderError):
        get_escrow_provider()
    with pytest.raises(UnknownProviderError):
        get_payout_provider()


def test_paystack_error_is_a_provider_error_with_its_status_code():
    err = PaystackError("boom", status_code=400)
    assert isinstance(err, ProviderError)
    assert (err.message, err.status_code) == ("boom", 400)


# ---- webhook: signature + normalisation -----------------------------------------------------


def test_missing_wrong_or_unconfigured_signature_is_rejected_with_401():
    _, body = _signed("charge.success", {"reference": "r"})
    provider = PaystackEscrowProvider()
    for headers in ({}, {"x-paystack-signature": "bad"}):
        with pytest.raises(WebhookRejected) as exc:
            provider.verify_and_parse_webhook(headers, body)
        assert (exc.value.status_code, exc.value.detail) == (401, "Invalid webhook signature")


def test_signature_header_lookup_is_case_insensitive():
    headers, body = _signed("charge.success", {"reference": "r"})
    lowered = {k.lower(): v for k, v in headers.items()}
    assert isinstance(PaystackEscrowProvider().verify_and_parse_webhook(lowered, body), HoldFunded)


def test_no_webhook_secret_rejects_even_a_matching_signature(monkeypatch):
    headers, body = _signed("charge.success", {"reference": "r"})
    monkeypatch.setattr(settings, "PAYSTACK_WEBHOOK_SECRET", None)
    with pytest.raises(WebhookRejected) as exc:
        PaystackEscrowProvider().verify_and_parse_webhook(headers, body)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]"])
def test_signed_but_malformed_payload_is_rejected_with_400(body):
    sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    with pytest.raises(WebhookRejected) as exc:
        PaystackEscrowProvider().verify_and_parse_webhook({"x-paystack-signature": sig}, body)
    assert (exc.value.status_code, exc.value.detail) == (400, "Invalid JSON payload")


def test_events_are_normalised_and_keep_the_raw_data_the_settlement_code_reads():
    data = {"reference": "WC-1", "amount": 500000, "currency": "NGN", "channel": "card"}
    funded = _parse("charge.success", data)
    assert funded == HoldFunded("WC-1", data)
    assert _parse("charge.failed", data) == HoldFailed("WC-1", data)
    assert _parse("charge.success", {}) == HoldFunded(None, {})
    assert _parse("transfer.success", {"reference": "T"}) == PayoutSucceeded({"reference": "T"})
    assert _parse("transfer.failed", {"reference": "T"}) == PayoutFailed({"reference": "T"}, False)
    assert _parse("transfer.reversed", {"reference": "T"}) == PayoutFailed({"reference": "T"}, True)
    for name in ("refund.pending", "refund.processing", "refund.processed", "refund.failed"):
        assert _parse(name, {"id": 1}) == RefundUpdated(name, {"id": 1})
    assert _parse("subscription.create", {}) == Ignored("subscription.create")


# ---- the provider's events feed the SAME settlement code, with the same guards ---------------


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
        "channel": "card",
    }
    data.update(kw)
    return data


def test_funded_event_settles_the_payment_and_a_replay_is_idempotent(db, pending_payment):
    booking, payment = pending_payment
    event = _parse("charge.success", _charge(payment))
    assert isinstance(event, HoldFunded)

    first = apply_charge_success(db, event.reference, event.data)
    assert first.outcome == OUTCOME_PROCESSED
    db.refresh(payment)
    assert payment.status == PaymentStatus.SUCCESS

    replay = apply_charge_success(db, event.reference, event.data)
    assert replay.outcome == OUTCOME_ALREADY


@pytest.mark.parametrize("override", [{"amount": 999_999}, {"currency": "USD"}])
def test_funded_event_with_wrong_amount_or_currency_is_not_settled(db, pending_payment, override):
    _, payment = pending_payment
    event = _parse("charge.success", _charge(payment, **override))
    result = apply_charge_success(db, event.reference, event.data)
    assert result.outcome == OUTCOME_MISMATCH
    db.refresh(payment)
    assert payment.status == PaymentStatus.PENDING


# ---- fetch_status ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paystack_status,expected",
    [
        ("success", HoldFunded),
        ("failed", HoldFailed),
        ("reversed", HoldFailed),
        ("abandoned", HoldPending),
        ("ongoing", HoldPending),
        ("pending", HoldPending),
        (None, HoldPending),
    ],
)
def test_fetch_status_classifies_only_terminal_statuses_as_failed(
    monkeypatch, paystack_status, expected
):
    data = {"status": paystack_status, "reference": "WC-9"}
    monkeypatch.setattr(PaystackService, "verify_transaction", staticmethod(lambda ref: data))
    outcome = PaystackEscrowProvider().fetch_status("WC-9")
    assert isinstance(outcome, expected)
    assert outcome.data is data


def test_fetch_status_propagates_provider_errors(monkeypatch):
    def boom(ref):
        raise PaystackError("down")

    monkeypatch.setattr(PaystackService, "verify_transaction", staticmethod(boom))
    with pytest.raises(ProviderError):
        PaystackEscrowProvider().fetch_status("WC-9")


# ---- initiate_hold --------------------------------------------------------------------------


def _booking():
    return SimpleNamespace(
        id=7, booking_reference="BK-7", customer_id="c-1", artisan_id="a-1", service_id=3
    )


def test_initiate_hold_sends_the_same_request_as_before(monkeypatch):
    seen = {}

    def fake_init(**kw):
        seen.update(kw)
        return {"authorization_url": "https://pay/x", "reference": "WC-1", "access_code": "ac"}

    monkeypatch.setattr(PaystackService, "initialize_transaction", staticmethod(fake_init))
    checkout = PaystackEscrowProvider().initiate_hold(
        booking=_booking(), amount=Decimal("10000.00"), customer_email="c@x.test", reference="WC-1"
    )
    assert seen == {
        "email": "c@x.test",
        "amount": Decimal("10000.00"),
        "reference": "WC-1",
        "metadata": {
            "booking_id": 7,
            "booking_reference": "BK-7",
            "customer_id": "c-1",
            "artisan_id": "a-1",
            "service_id": 3,
        },
    }
    assert (checkout.authorization_url, checkout.reference, checkout.access_code) == (
        "https://pay/x",
        "WC-1",
        "ac",
    )
    assert checkout.raw["reference"] == "WC-1"


def test_initiate_hold_maps_duplicate_reference_and_passes_other_errors(monkeypatch):
    def duplicate(**kw):
        raise PaystackError("Duplicate Transaction Reference", status_code=400)

    def other(**kw):
        raise PaystackError("Invalid key", status_code=401)

    provider = PaystackEscrowProvider()
    args = dict(
        booking=_booking(), amount=Decimal("1"), customer_email="c@x.test", reference="WC-1"
    )
    monkeypatch.setattr(PaystackService, "initialize_transaction", staticmethod(duplicate))
    with pytest.raises(DuplicateReferenceError) as exc:
        provider.initiate_hold(**args)
    assert exc.value.status_code == 400

    monkeypatch.setattr(PaystackService, "initialize_transaction", staticmethod(other))
    with pytest.raises(ProviderError) as exc:
        provider.initiate_hold(**args)
    assert not isinstance(exc.value, DuplicateReferenceError)
    assert exc.value.status_code == 401


# ---- refund ---------------------------------------------------------------------------------


def test_refund_and_list_refunds_delegate_with_the_arguments_admin_used_before(monkeypatch):
    calls = []

    def fake_refund(reference, **kw):
        calls.append((reference, kw))
        return {"id": 1, "status": "pending"}

    monkeypatch.setattr(PaystackService, "refund", staticmethod(fake_refund))
    monkeypatch.setattr(PaystackService, "list_refunds", staticmethod(lambda ref: [{"id": ref}]))
    provider = PaystackEscrowProvider()

    out = provider.refund("WC-1", idempotency_key="k", customer_note="c", merchant_note="m")
    assert out == {"id": 1, "status": "pending"}
    assert calls == [("WC-1", {"customer_note": "c", "merchant_note": "m"})]  # full refund

    provider.refund("WC-1", Decimal("5.00"))
    assert calls[-1][1]["amount"] == Decimal("5.00")
    assert provider.list_refunds("WC-1") == [{"id": "WC-1"}]


# ---- payout provider ------------------------------------------------------------------------


def test_payout_provider_delegates_to_paystack_transfers(monkeypatch):
    seen = {}
    monkeypatch.setattr(PaystackService, "get_banks", staticmethod(lambda: [{"code": "057"}]))
    monkeypatch.setattr(
        PaystackService,
        "verify_account_number",
        staticmethod(lambda account_number, bank_code: {"account_name": "A"}),
    )
    monkeypatch.setattr(
        PaystackService,
        "create_transfer_recipient",
        staticmethod(lambda name, account_number, bank_code: {"recipient_code": "RCP_1"}),
    )

    def fake_transfer(recipient_code, amount, reason, reference):
        seen["transfer"] = (recipient_code, amount, reason, reference)
        return {"status": "success"}

    monkeypatch.setattr(PaystackService, "initiate_transfer", staticmethod(fake_transfer))
    monkeypatch.setattr(
        PaystackService, "verify_transfer", staticmethod(lambda ref: {"status": "pending"})
    )
    payout = PaystackPayoutProvider()
    assert payout.list_banks() == [{"code": "057"}]
    assert payout.resolve_account("0123456789", "057") == {"account_name": "A"}
    assert payout.create_recipient("A", "0123456789", "057") == {"recipient_code": "RCP_1"}
    assert payout.transfer("RCP_1", Decimal("100"), "Workchop payout", "W-1") == {
        "status": "success"
    }
    assert seen["transfer"] == ("RCP_1", Decimal("100"), "Workchop payout", "W-1")
    assert payout.verify_transfer("W-1") == {"status": "pending"}
