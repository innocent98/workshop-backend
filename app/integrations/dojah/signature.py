"""
Dojah webhook signature check.

Per https://docs.dojah.io/api-reference/core-concepts/webhooks-signatures.md the
``x-dojah-signature`` header is the HMAC-SHA256 hex digest of the RAW request body keyed with
the per-subscription webhook secret (Dojah dashboard > Developers > Webhooks). Compared in
constant time. Fails closed when the secret or the header is missing.
"""

import hashlib
import hmac
from typing import Optional

from app.core.config import settings


def verify_dojah_signature(raw_body: bytes, signature: Optional[str]) -> bool:
    secret = settings.DOJAH_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest().encode()
    try:
        # Compare BYTES: hmac.compare_digest raises TypeError on a non-ASCII str, which would
        # turn a junk header into a 500 instead of a 401.
        return hmac.compare_digest(expected, signature.strip().lower().encode("utf-8"))
    except (TypeError, ValueError, UnicodeError):
        return False
