"""
Artisan response-time stat: average minutes from a booking request to the artisan accepting it.

Recomputed from the artisan's last ``RESPONSE_TIME_WINDOW`` accepted bookings (``accepted_at`` set)
rather than kept as a running average: it stays correct if a booking row is ever corrected, needs no
counter column, and the window makes it reflect how the artisan responds NOW, not two years ago.
Rejected, cancelled-before-accept and expired requests never get an ``accepted_at`` so they are not
counted. The artisan's profile row is locked for the recompute, so two bookings accepted at the same
moment cannot overwrite each other with an average that misses one of them.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking


def compute_response_time_avg_minutes(db: Session, artisan_id: UUID) -> Optional[int]:
    """Average request-to-acceptance minutes over the last N accepted bookings, or None.

    Whole minutes, never below 1 once the artisan has any accepted booking (0 would read as "no
    data" to a falsy check; "1" shows as "about a minute"). A negative gap (clock skew) counts as 0.
    """
    recent = (
        db.query(Booking.created_at.label("created_at"), Booking.accepted_at.label("accepted_at"))
        .filter(Booking.artisan_id == artisan_id, Booking.accepted_at.is_not(None))
        .order_by(Booking.accepted_at.desc(), Booking.id.desc())
        .limit(settings.RESPONSE_TIME_WINDOW)
        .subquery()
    )
    avg_seconds = db.query(
        func.avg(
            func.greatest(func.extract("epoch", recent.c.accepted_at - recent.c.created_at), 0)
        )
    ).scalar()
    if avg_seconds is None:
        return None
    return max(1, int(round(float(avg_seconds) / 60)))


def record_acceptance(db: Session, booking: Booking) -> Optional[int]:
    """Refresh the artisan's stat after ``booking.accepted_at`` was set. Call inside the accept
    transaction (the booking row is already locked): it commits with the acceptance or not at all.
    No profile row means nothing to update (it is not created here)."""
    profile = (
        db.query(ArtisanProfile)
        .filter(ArtisanProfile.user_id == booking.artisan_id)
        .with_for_update(key_share=True)  # FOR NO KEY UPDATE: serialises recomputes, blocks less
        .first()
    )
    if profile is None:
        return None
    db.flush()  # make this booking's accepted_at visible to the aggregate
    profile.response_time_avg_minutes = compute_response_time_avg_minutes(db, booking.artisan_id)
    return profile.response_time_avg_minutes
