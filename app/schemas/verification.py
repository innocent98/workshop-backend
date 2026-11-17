from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

VerificationStatus = Literal["unverified", "pending", "verified", "failed"]


class VerificationConfigResponse(BaseModel):
    configured: bool
    app_id: Optional[str] = None
    public_key: Optional[str] = None
    widget_id: Optional[str] = None
    environment: str


class VerificationStartResponse(BaseModel):
    reference_id: str
    widget_id: str
    email: str
    attempts_remaining: int


class VerificationConfirmRequest(BaseModel):
    reference_id: str


class VerificationStatusResponse(BaseModel):
    verification_status: VerificationStatus
    is_verified: bool
    verified_at: Optional[datetime] = None
    verification_method: Optional[Literal["dojah", "admin", "legacy"]] = None
    failure_reason: Optional[str] = None
    nin_last4: Optional[str] = None
    reference_id: Optional[str] = None  # latest verification attempt
    attempts_used: int
    attempts_remaining: int
    max_attempts: int
    window_hours: int
    # Set only when attempts_remaining == 0: when the oldest attempt leaves the window.
    retry_available_at: Optional[datetime] = None
