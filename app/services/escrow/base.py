"""
Escrow provider interface.

Workchop owns the booking states, the artisan wallet and withdrawal ledger, the 24h auto-confirm,
the dispute rules and the admin release/refund decision. Only the *movement of customer money*
goes through an ``EscrowProvider``: taking the hold, telling us it was funded or failed, and
giving it back.

Provider adapters translate their wire format into the small event types below. Those events feed
the existing settlement code unchanged (``apply_charge_success`` / ``apply_charge_failed`` in
``app/services/payment_service.py`` and ``handle_refund_event`` in ``app/services/admin.py``).
``data`` on each event is the provider's raw object in the shape those functions already read
(``reference``, ``amount`` in the smallest currency unit, ``currency``, ``channel``, ``status``,
``id``, ...). See ``docs/sop/escrow-provider-seam.md``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Optional, Union


@dataclass(frozen=True)
class HoldCheckout:
    """Result of starting a hold: where the customer pays and the provider's identifiers."""

    authorization_url: str
    reference: Optional[str]  # the provider's own reference for the hold
    access_code: Optional[str]
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HoldFunded:
    """The customer's money is now held."""

    reference: Optional[str]
    data: dict


@dataclass(frozen=True)
class HoldFailed:
    """The hold definitively failed (terminal: the customer was not charged)."""

    reference: Optional[str]
    data: dict


@dataclass(frozen=True)
class HoldPending:
    """``fetch_status`` only: not funded yet, but not a terminal failure either."""

    reference: Optional[str]
    data: dict


@dataclass(frozen=True)
class RefundUpdated:
    """An asynchronous refund moved (``event`` is e.g. ``refund.processed``)."""

    event: str
    data: dict


@dataclass(frozen=True)
class PayoutSucceeded:
    """A payout (artisan bank transfer) completed."""

    data: dict


@dataclass(frozen=True)
class PayoutFailed:
    """A payout failed, or was reversed after being sent (``reversed``)."""

    data: dict
    reversed: bool = False


@dataclass(frozen=True)
class Ignored:
    """A genuine provider event we do not act on (``event`` is its name)."""

    event: Optional[str]


EscrowEvent = Union[
    HoldFunded, HoldFailed, HoldPending, RefundUpdated, PayoutSucceeded, PayoutFailed, Ignored
]


class WebhookRejected(Exception):
    """The webhook must be rejected with ``status_code`` (401 bad signature, 400 bad payload)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class EscrowProvider(ABC):
    """Money movement for booking escrow. Stateless: instances hold no per-request state."""

    name: str

    @abstractmethod
    def initiate_hold(
        self,
        *,
        booking,
        amount: Decimal,
        customer_email: str,
        reference: str,
    ) -> HoldCheckout:
        """Start a hold for ``booking``. ``reference`` is our unique payment reference.

        Raises ``DuplicateReferenceError`` when the provider says the reference was already used
        (the caller retries with a fresh one) and ``ProviderError`` for any other failure.
        """

    @abstractmethod
    def verify_and_parse_webhook(self, headers: Mapping[str, str], body: bytes) -> EscrowEvent:
        """Authenticate a webhook and normalise it. Raises ``WebhookRejected`` if it is not ours."""

    @abstractmethod
    def fetch_status(self, reference: str) -> Union[HoldFunded, HoldFailed, HoldPending]:
        """Ask the provider where a hold stands (used by the verify endpoint). Raises
        ``ProviderError`` when the provider cannot be reached."""

    @abstractmethod
    def refund(
        self,
        hold_reference: str,
        amount: Optional[Decimal] = None,
        idempotency_key: Optional[str] = None,
        *,
        customer_note: Optional[str] = None,
        merchant_note: Optional[str] = None,
    ) -> dict:
        """Refund a hold (``amount`` None = in full). Returns the provider's refund object
        (``id``, ``status``). ``ProviderError.status_code`` is set for a definite rejection and
        ``None`` when the outcome is unknown; callers then reconcile with ``list_refunds``."""

    @abstractmethod
    def list_refunds(self, hold_reference: str) -> list:
        """Refunds the provider holds for a hold: how an unknown refund outcome is reconciled."""
