"""Payout provider seam: ``get_payout_provider()`` returns the configured implementation."""

from typing import Callable, Dict, Optional

from app.core.config import settings
from app.services.escrow import UnknownProviderError
from app.services.payout.base import PayoutProvider
from app.services.payout.paystack import PaystackPayoutProvider

_REGISTRY: Dict[str, Callable[[], PayoutProvider]] = {
    "paystack": PaystackPayoutProvider,
}


def get_payout_provider(name: Optional[str] = None) -> PayoutProvider:
    """The provider named by ``settings.PAYOUT_PROVIDER`` (default ``paystack``)."""
    key = (name or settings.PAYOUT_PROVIDER or "paystack").strip().lower()
    try:
        return _REGISTRY[key]()
    except KeyError:
        raise UnknownProviderError(
            f"Unknown PAYOUT_PROVIDER {key!r}; available: {', '.join(sorted(_REGISTRY))}"
        )
