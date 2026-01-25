"""
Pydantic schemas for Services and Service Categories.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# Service Category Schemas
class ServiceCategoryBase(BaseModel):
    """Base schema for Service Category"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    is_active: bool = True
    display_order: int = 0


class ServiceCategoryCreate(ServiceCategoryBase):
    """Schema for creating a service category"""
    pass


class ServiceCategoryUpdate(BaseModel):
    """Schema for updating a service category"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class ServiceCategoryResponse(ServiceCategoryBase):
    """Schema for service category response"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Service Schemas
class ServiceBase(BaseModel):
    """Base schema for Service"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    category_id: Optional[int] = None


class ServiceCreate(ServiceBase):
    """Schema for creating a service"""
    pass


class ServiceUpdate(BaseModel):
    """Schema for updating a service"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    category_id: Optional[int] = None


class ServiceResponse(ServiceBase):
    """Schema for service response"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceWithCategoryResponse(ServiceResponse):
    """Schema for service response with category details"""
    category: Optional[ServiceCategoryResponse] = None

    class Config:
        from_attributes = True


class ServiceCategoryWithServicesResponse(ServiceCategoryResponse):
    """Schema for category response with its services"""
    services: List[ServiceResponse] = []

    class Config:
        from_attributes = True
