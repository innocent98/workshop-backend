from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Service(Base):
    """
    Unified Service model for both artisans and clients.

    Context changes based on user type:
    - Artisan selecting a service = "I provide this service"
    - Client selecting a service = "I need this service"

    This allows easy matching between clients seeking services and artisans providing them.
    """
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("service_categories.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)  # Optional description of the service
    image = Column(String(500), nullable=True)  # Optional image URL for the service
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    category = relationship("ServiceCategory", back_populates="services")
    user_services = relationship("UserService", back_populates="service", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Service {self.name}>"


class UserService(Base):
    """
    Many-to-many relationship between Users and Services.
    Tracks which services a user has selected during registration.
    """
    __tablename__ = "user_services"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Ensure a user can't select the same service twice
    __table_args__ = (
        UniqueConstraint('user_id', 'service_id', name='uq_user_service'),
    )

    # Relationships
    user = relationship("User", back_populates="services")
    service = relationship("Service", back_populates="user_services")

    def __repr__(self):
        return f"<UserService user_id={self.user_id} service_id={self.service_id}>"
