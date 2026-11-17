"""Escrow provider seam: ``get_escrow_provider()`` returns the configured implementation."""

from typing import Callable, Dict, Optional

from app.core.config import settings
from app.services.escrow.base import EscrowProvider
from app.services.escrow.paystack import PaystackEscrowProvider


class UnknownProviderError(ValueError):
    pass


_REGISTRY: Dict[str, Callable[[], EscrowProvider]] = {
    "paystack": PaystackEscrowProvider,
}


def get_escrow_provider(name: Optional[str] = None) -> EscrowProvider:
    """The provider named by ``settings.ESCROW_PROVIDER`` (default ``paystack``)."""
    key = (name or settings.ESCROW_PROVIDER or "paystack").strip().lower()
    try:
        return _REGISTRY[key]()
    except KeyError:
        raise UnknownProviderError(
            f"Unknown ESCROW_PROVIDER {key!r}; available: {', '.join(sorted(_REGISTRY))}"
        )
