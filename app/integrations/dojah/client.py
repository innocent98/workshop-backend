"""
Dojah client: server-side "get verification details" for the hosted Identity widget.

    GET {host}/api/v1/kyc/verification?reference_id=<ref>
    Headers: Authorization: <secret key, no "Bearer">, AppId: <app id>
    Docs: https://docs.dojah.io/api-reference/verifications/get-verification.md

Retries 5xx and transport errors (up to 3 attempts, exponential backoff); 4xx never retried.
Blocking (sync httpx): callers are plain ``def`` endpoints, which FastAPI runs in a threadpool.
Response parsing is defensive: the whole verification sits under ``entity`` and every access is a
nested ``.get``. The NIN, names, DOB and images are never stored or logged; only the last 4 digits
of the NIN are kept, and only if Dojah returns them.

NOT EXERCISED LIVE from this repo: the response shape below follows Dojah's docs and the
structure documented in the owner's Timpbills integration, which was never used in production.
"""

import time
from typing import Any, Literal, Optional

import httpx

from app.core.config import settings
from app.core.logger import logger
from app.integrations.dojah.schemas import NinVerificationResult

_Status = Literal["success", "pending", "failed"]

# Dojah's documented verification_status values. Unknown values stay "pending" so a new
# forward-compatible status can never mark someone failed or verified by accident.
STATUS_MAP: dict[str, _Status] = {
    "Completed": "success",
    "Pending": "pending",
    "Ongoing": "pending",
    "Failed": "failed",
    "Abandoned": "failed",
}

PROD_HOST = "https://api.dojah.io"
SANDBOX_HOST = "https://sandbox.dojah.io"
MAX_ATTEMPTS = 3


class DojahError(Exception):
    """Provider/config problem (timeout, 5xx, bad keys, no balance, unknown reference)."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out  # Dojah was too slow: the verification may finish moments later


def resolve_base_url() -> str:
    """DOJAH_ENVIRONMENT picks the host (sandbox keys only work on sandbox.dojah.io);
    a non-default DOJAH_BASE_URL (proxy, pinned test host) overrides."""
    configured = (settings.DOJAH_BASE_URL or "").rstrip("/")
    if configured and configured != PROD_HOST:
        return configured
    return (
        SANDBOX_HOST
        if (settings.DOJAH_ENVIRONMENT or "sandbox").lower() == "sandbox"
        else PROD_HOST
    )


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class DojahClient:
    PATH = "/api/v1/kyc/verification"

    def __init__(self, transport: Optional[httpx.BaseTransport] = None, backoff: float = 1.0):
        if not settings.DOJAH_API_KEY:
            raise RuntimeError("DOJAH_API_KEY must be set")
        self._base = resolve_base_url()
        self._headers = {
            "Authorization": settings.DOJAH_API_KEY,
            "AppId": settings.DOJAH_APP_ID or "",
        }
        self._transport = transport  # tests inject httpx.MockTransport here
        self._backoff = backoff

    def fetch_verification(
        self, reference_id: str, *, timeout: float = 15.0, max_attempts: int = MAX_ATTEMPTS
    ) -> NinVerificationResult:
        """Blocking call: endpoints that use it are plain ``def`` so FastAPI runs them in its
        threadpool and the event loop never waits on Dojah or the database."""
        last: Optional[BaseException] = None
        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=timeout, transport=self._transport) as c:
                    r = c.get(
                        f"{self._base}{self.PATH}",
                        params={"reference_id": reference_id},
                        headers=self._headers,
                    )
                    r.raise_for_status()
                return self.parse_result(r.json(), reference_id)
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                # Class / status only: exception text can echo request details.
                code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                logger.warning(
                    f"Dojah fetch failed ref={reference_id} type={type(exc).__name__} "
                    f"status={code} attempt={attempt}"
                )
                if isinstance(exc, ValueError) or not _retryable(exc) or attempt == max_attempts:
                    break
                time.sleep(self._backoff * 2 ** (attempt - 1))
        raise DojahError(
            f"Dojah verification lookup failed ({type(last).__name__})",
            timed_out=isinstance(last, httpx.TimeoutException),
        )

    @staticmethod
    def parse_result(payload: Any, reference_id: str) -> NinVerificationResult:
        entity = payload.get("entity") if isinstance(payload, dict) else None
        if not isinstance(entity, dict):
            entity = payload if isinstance(payload, dict) else {}

        dojah_status = str(entity.get("verification_status", ""))
        status: _Status = STATUS_MAP.get(dojah_status, "pending")

        data = entity.get("data") or {}
        government = data.get("government_data") or {}
        selfie = data.get("selfie") or {}
        records = government.get("data") or {}

        # Strict by design: only a real boolean True counts as a pass (never bool() of a string like
        # "false"), and the verification must explicitly be a NIN one (a BVN widget never verifies).
        is_nin = str(entity.get("verification_type") or "").lower() == "nin"
        id_verified = government.get("status") is True and is_nin
        selfie_passed = selfie.get("status") is True

        nin_value = (((records.get("nin") or {}).get("entity")) or {}).get("nin")
        digits = "".join(ch for ch in str(nin_value or "") if ch.isdigit())
        nin_last4 = digits[-4:] if len(digits) >= 4 else None

        return NinVerificationResult(
            status=status,
            id_verified=id_verified,
            selfie_passed=selfie_passed,
            nin_last4=nin_last4,
            provider_reference=str(entity.get("reference_id") or reference_id),
            dojah_status=dojah_status,
        )


def get_dojah_client() -> Optional[DojahClient]:
    """FastAPI dependency (override in tests). None when Dojah is not configured."""
    if not settings.DOJAH_API_KEY:
        return None
    return DojahClient()
