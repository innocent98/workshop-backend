import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session


def generate_payment_reference(db: Session) -> str:
    """
    Generate a unique payment reference in a collision-resistant format.
    Format: PAY-YYDDDHHMMSS-RRR (max 20 chars)
    Example: PAY-26047141920-583

    Args:
        db: Database session

    Returns:
        Unique payment reference string
    """
    from app.db.models.payment import Payment

    for _ in range(20):
        now = datetime.now(timezone.utc)
        # 2(year) + 3(day_of_year) + 2(hour) + 2(minute) + 2(second) = 11 chars
        stamp = now.strftime("%y%j%H%M%S")
        rand = random.randint(100, 999)
        reference = f"PAY-{stamp}-{rand}"

        if not db.query(Payment).filter(Payment.payment_reference == reference).first():
            return reference

    # Last fallback in extremely unlikely collision scenarios.
    now = datetime.now(timezone.utc)
    return f"PAY-{now.strftime('%y%j%H%M%S')}-{random.randint(100, 999)}"
