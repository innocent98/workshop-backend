"""Paystack implementation of the escrow seam. Wraps ``PaystackService`` without changing it.

Every call goes through ``PaystackService.<method>`` at call time (never a cached reference), so
tests that patch ``PaystackService`` keep working.
"""

import json
from decimal import Decimal
from typing import Mapping, Optional

from app.services.escrow.base import (
    EscrowEvent,
    EscrowProvider,
    HoldCheckout,
    HoldFailed,
    HoldFunded,
    HoldPending,
    Ignored,
    PayoutFailed,
    PayoutSucceeded,
    RefundUpdated,
    WebhookRejected,
)
from app.services.paystack import PaystackError, PaystackService
from app.services.provider_errors import DuplicateReferenceError

SIGNATURE_HEADER = "x-paystack-signature"

# Paystack transaction statuses that are final failures (everything else may still succeed).
TERMINAL_FAILURE_STATUSES = {"failed", "reversed"}

REFUND_WEBHOOK_EVENTS = (
    "refund.pending",
    "refund.processing",
    "refund.processed",
    "refund.failed",
)


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


class PaystackEscrowProvider(EscrowProvider):
    name = "paystack"

    def initiate_hold(
        self,
        *,
        booking,
        amount: Decimal,
        customer_email: str,
        reference: str,
    ) -> HoldCheckout:
        metadata = {
            "booking_id": booking.id,
            "booking_reference": booking.booking_reference,
            "customer_id": str(booking.customer_id),
            "artisan_id": str(booking.artisan_id),
            "service_id": booking.service_id,
        }
        try:
            data = PaystackService.initialize_transaction(
                email=customer_email,
                amount=amount,
                reference=reference,
                metadata=metadata,
            )
        except PaystackError as exc:
            if "Duplicate Transaction Reference" in str(exc):
                raise DuplicateReferenceError(exc.message, exc.status_code) from exc
            raise
        return HoldCheckout(
            authorization_url=data.get("authorization_url"),
            reference=data.get("reference"),
            access_code=data.get("access_code"),
            raw=data,
        )

    def verify_and_parse_webhook(self, headers: Mapping[str, str], body: bytes) -> EscrowEvent:
        signature = _header(headers, SIGNATURE_HEADER)
        if not signature or not PaystackService.verify_webhook_signature(signature, body):
            raise WebhookRejected(401, "Invalid webhook signature")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise WebhookRejected(400, "Invalid JSON payload")
        if not isinstance(payload, dict):
            raise WebhookRejected(400, "Invalid JSON payload")

        event = payload.get("event")
        data = payload.get("data") or {}
        if event == "charge.success":
            return HoldFunded(data.get("reference"), data)
        if event == "charge.failed":
            return HoldFailed(data.get("reference"), data)
        if event == "transfer.success":
            return PayoutSucceeded(data)
        if event in ("transfer.failed", "transfer.reversed"):
            return PayoutFailed(data, reversed=event == "transfer.reversed")
        if event in REFUND_WEBHOOK_EVENTS:
            return RefundUpdated(event, data)
        return Ignored(event)

    def fetch_status(self, reference: str):
        data = PaystackService.verify_transaction(reference)
        status = data.get("status")
        if status == "success":
            return HoldFunded(reference, data)
        if status in TERMINAL_FAILURE_STATUSES:
            return HoldFailed(reference, data)
        return HoldPending(reference, data)

    def refund(
        self,
        hold_reference: str,
        amount: Optional[Decimal] = None,
        idempotency_key: Optional[str] = None,
        *,
        customer_note: Optional[str] = None,
        merchant_note: Optional[str] = None,
    ) -> dict:
        # Paystack's /refund takes no idempotency key: a repeat is reconciled by list_refunds.
        kwargs = {"customer_note": customer_note, "merchant_note": merchant_note}
        if amount is not None:
            kwargs["amount"] = amount
        return PaystackService.refund(hold_reference, **kwargs)

    def list_refunds(self, hold_reference: str) -> list:
        return PaystackService.list_refunds(hold_reference)
