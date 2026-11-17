"""Provider-neutral error types shared by the escrow and payout provider seams."""

from typing import Optional


class ProviderError(Exception):
    """A payment/escrow/payout provider call failed.

    ``status_code`` is the HTTP status when the provider answered (a definite answer, e.g. a 400
    rejection) and ``None`` for timeouts and connection errors, where the outcome is unknown.
    Callers rely on that distinction (see ``_run_refund`` and ``_initiate_transfer``).
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DuplicateReferenceError(ProviderError):
    """The provider refused a new hold because our reference was already used."""
