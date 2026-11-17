"""
Portfolio model for artisan work samples and completed projects.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Portfolio(Base):
    """
    Portfolio items showcasing artisan's previous work.
    Artisans can upload images and descriptions of their completed projects.
    """

    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True, index=True)
    artisan_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Image and details
    image_url = Column(String(500), nullable=False)  # Cloudinary or local URL
    title = Column(String(200), nullable=True)  # Optional title for the work
    description = Column(Text, nullable=True)  # Description of the project
    project_date = Column(DateTime(timezone=True), nullable=True)  # When the work was completed

    # Metadata
    display_order = Column(Integer, default=0, nullable=False)  # For sorting in UI
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    artisan = relationship(
        "ArtisanProfile",
        back_populates="portfolio",
        primaryjoin="Portfolio.artisan_id==ArtisanProfile.user_id",
        foreign_keys=[artisan_id],
    )

    def __repr__(self):
        return f"<Portfolio id={self.id} artisan_id={self.artisan_id}>"
