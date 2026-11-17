from typing import Literal, Optional

from pydantic import BaseModel


class NinVerificationResult(BaseModel):
    """What we keep from Dojah's verification-details response. No names, DOB, NIN or images."""

    status: Literal["success", "pending", "failed"]
    id_verified: bool  # Dojah confirmed the NIN against government data
    selfie_passed: bool  # combined liveness + face match result from the widget
    nin_last4: Optional[str] = None  # only if Dojah returned the NIN; never the full number
    provider_reference: str
    dojah_status: str = ""  # raw verification_status, for logs/diagnostics only
