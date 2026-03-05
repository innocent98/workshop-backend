from datetime import datetime
from typing import Any, Dict, List, Optional
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


class UserNotificationResponse(BaseModel):
    id: int
    title: str
    body: str
    event_type: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserNotificationListResponse(BaseModel):
    notifications: List[UserNotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int


class UserNotificationActionResponse(BaseModel):
    success: bool
    message: str
