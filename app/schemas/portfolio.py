"""
Pydantic schemas for Artisan Portfolio.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PortfolioBase(BaseModel):
    """Base schema for Portfolio"""
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    project_date: Optional[datetime] = None
    display_order: int = 0


class PortfolioCreate(PortfolioBase):
    """Schema for creating portfolio item (image_url will be set after upload)"""
    pass


class PortfolioUpdate(BaseModel):
    """Schema for updating portfolio item"""
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    project_date: Optional[datetime] = None
    display_order: Optional[int] = None


class PortfolioResponse(PortfolioBase):
    """Schema for portfolio response"""
    id: int
    artisan_id: str  # User UUID
    image_url: str
    created_at: datetime

    class Config:
        from_attributes = True
