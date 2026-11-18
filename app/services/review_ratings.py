"""Single place that derives an artisan's public rating figures from their reviews.

Flagged reviews (``is_flagged``) are hidden from public listings, so they must not count toward the
average or the review count either. Every code path that creates a review or changes a flag calls
``recalculate_artisan_rating`` so the cached figures on ``artisan_profiles`` (used by search and the
profile endpoints) never disagree with what the public review listing shows.
"""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.review import Review


def recalculate_artisan_rating(db: Session, artisan_id: UUID):
    """Recompute total_ratings / average_rating from unflagged reviews. The profile row is locked
    so concurrent review creations / admin flag changes serialise. Returns the profile (None when
    the artisan has no profile row). Does not commit; flushes pending review changes first."""
    profile = (
        db.query(ArtisanProfile)
        .filter(ArtisanProfile.user_id == artisan_id)
        .with_for_update()
        .first()
    )
    if profile is None:
        return None
    db.flush()
    total, avg = (
        db.query(func.count(Review.id), func.avg(Review.rating))
        .filter(Review.artisan_id == artisan_id, Review.is_flagged.is_(False))
        .one()
    )
    profile.total_ratings = int(total or 0)
    profile.average_rating = float(avg or 0.0)
    return profile
