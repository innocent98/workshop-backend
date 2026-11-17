from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session


def generate_booking_reference(db: Session) -> str:
    """
    Generate a unique booking reference in the format: BK-YYYY-XXXXXX

    Example: BK-2025-000001

    Args:
        db: Database session

    Returns:
        Unique booking reference string
    """
    from app.db.models.booking import Booking

    # Get current year
    current_year = datetime.now().year

    # Get the count of bookings created this year
    year_start = datetime(current_year, 1, 1)
    count = db.query(func.count(Booking.id)).filter(Booking.created_at >= year_start).scalar() or 0

    # Generate reference with next number
    next_number = count + 1
    reference = f"BK-{current_year}-{next_number:06d}"

    # Check if reference exists (edge case for concurrent requests)
    while db.query(Booking).filter(Booking.booking_reference == reference).first():
        next_number += 1
        reference = f"BK-{current_year}-{next_number:06d}"

    return reference
