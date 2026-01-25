"""
Service Category models for organizing services.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ServiceCategory(Base):
    """
    Service categories for organizing services.

    Examples:
    - Plumbing
    - Electrical
    - Carpentry
    - AC/HVAC
    - Painting
    - Cleaning
    """
    __tablename__ = "service_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)  # Icon name/emoji for UI
    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)  # For sorting in UI
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    services = relationship("Service", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ServiceCategory {self.name}>"
