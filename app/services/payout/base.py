"""
Payout provider interface: artisan bank payouts and bank-account lookups.

Separate from the escrow seam on purpose. Escrow decides whose money is held; payouts move
the artisan's withdrawn wallet balance to their bank account. Both are Paystack-only for now.
"""

from abc import ABC, abstractmethod
from decimal import Decimal


class PayoutProvider(ABC):
    """Stateless. Methods return the provider's raw objects, in the shape the callers read."""

    name: str

    @abstractmethod
    def list_banks(self):
        """Supported banks."""

    @abstractmethod
    def resolve_account(self, account_number: str, bank_code: str) -> dict:
        """Resolve a bank account to ``{"account_name", "account_number"}``."""

    @abstractmethod
    def create_recipient(self, name: str, account_number: str, bank_code: str) -> dict:
        """Register a payout destination; returns ``{"recipient_code", ...}``."""

    @abstractmethod
    def transfer(self, recipient_code: str, amount: Decimal, reason: str, reference: str) -> dict:
        """Send money to a recipient under OUR ``reference`` (so a retry can never double-pay)."""

    @abstractmethod
    def verify_transfer(self, reference: str) -> dict:
        """Fetch a transfer by our reference. ``ProviderError.status_code == 404`` = not found."""
