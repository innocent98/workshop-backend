from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func


def generate_payment_reference(db: Session) -> str:
    """
    Generate a unique payment reference in the format: PAY-YYYY-XXXXXX

    Example: PAY-2025-000001

    Args:
        db: Database session

    Returns:
        Unique payment reference string
    """
    from app.db.models.payment import Payment

    # Get current year
    current_year = datetime.now().year

    # Get the count of payments created this year
    year_start = datetime(current_year, 1, 1)
    count = db.query(func.count(Payment.id)).filter(
        Payment.created_at >= year_start
    ).scalar() or 0

    # Generate reference with next number
    next_number = count + 1
    reference = f"PAY-{current_year}-{next_number:06d}"

    # Check if reference exists (edge case for concurrent requests)
    while db.query(Payment).filter(Payment.payment_reference == reference).first():
        next_number += 1
        reference = f"PAY-{current_year}-{next_number:06d}"

    return reference
