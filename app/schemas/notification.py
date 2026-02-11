from typing import Optional
from pydantic import BaseModel, Field


class RegisterPushDeviceRequest(BaseModel):
    fcm_token: str = Field(..., min_length=20, max_length=1024)
    platform: str = Field(..., pattern="^(android|ios|web)$")
    device_id: Optional[str] = Field(None, max_length=255)


class UnregisterPushDeviceRequest(BaseModel):
    fcm_token: str = Field(..., min_length=20, max_length=1024)


class PushDeviceResponse(BaseModel):
    success: bool
    message: str
