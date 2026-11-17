"""Paystack implementation of the payout seam. Delegates to ``PaystackService`` at call time."""

from decimal import Decimal

from app.services.payout.base import PayoutProvider
from app.services.paystack import PaystackService


class PaystackPayoutProvider(PayoutProvider):
    name = "paystack"

    def list_banks(self):
        return PaystackService.get_banks()

    def resolve_account(self, account_number: str, bank_code: str) -> dict:
        return PaystackService.verify_account_number(
            account_number=account_number, bank_code=bank_code
        )

    def create_recipient(self, name: str, account_number: str, bank_code: str) -> dict:
        return PaystackService.create_transfer_recipient(
            name=name, account_number=account_number, bank_code=bank_code
        )

    def transfer(self, recipient_code: str, amount: Decimal, reason: str, reference: str) -> dict:
        return PaystackService.initiate_transfer(
            recipient_code=recipient_code, amount=amount, reason=reason, reference=reference
        )

    def verify_transfer(self, reference: str) -> dict:
        return PaystackService.verify_transfer(reference)
