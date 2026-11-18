"""
Review endpoints for customer ratings and feedback.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.review import Review, ReviewReport
from app.db.models.user import User, UserType
from app.db.session import get_db
from app.schemas.review import (
    ArtisanReviewStatsResponse,
    CreateReviewRequest,
    ReportReviewRequest,
    ReportReviewResponse,
    RespondToReviewRequest,
    ReviewListResponse,
    ReviewResponse,
)
from app.services.notify import notify_user as _notify_user
from app.services.review_moderation import check_review_text
from app.services.review_ratings import recalculate_artisan_rating

router = APIRouter()


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    request: CreateReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a review for a completed booking.

    Only customers can create reviews and only after job completion.
    One review per booking.
    """
    # Only customers can create reviews
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only customers can create reviews"
        )

    # Get booking
    booking = db.query(Booking).filter(Booking.id == request.booking_id).first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Check ownership
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only review your own bookings"
        )

    # Check booking status
    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Can only review completed bookings"
        )
    if booking.completion_disputed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot review a disputed booking"
        )
    if booking.completion_confirmed_by_client_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only review after completion has been confirmed",
        )

    # Check if review already exists
    existing_review = db.query(Review).filter(Review.booking_id == request.booking_id).first()
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Review already exists for this booking"
        )

    # Create review. The reviewer always gets it accepted; the first-pass word filter may hide it
    # from public listings and rating aggregates until a moderator has looked at it.
    review = Review(
        booking_id=request.booking_id,
        customer_id=current_user.id,
        artisan_id=booking.artisan_id,
        rating=request.rating,
        review_text=request.review_text,
        is_anonymous=request.is_anonymous,
    )
    hit = check_review_text(request.review_text)
    if hit:
        review.is_flagged = True
        review.flag_source = "auto"
        review.flag_reason = hit.reason
        review.flagged_at = datetime.now(timezone.utc)

    db.add(review)

    # Recalculate the artisan's public figures from the unflagged reviews (source of truth)
    artisan_profile = recalculate_artisan_rating(db, booking.artisan_id)
    if artisan_profile:
        artisan_profile.total_jobs_completed = (artisan_profile.total_jobs_completed or 0) + 1

    db.commit()
    db.refresh(review)

    if not review.is_flagged:  # a hidden review is not announced to the artisan
        _notify_user(
            booking.artisan_id,
            "New review",
            f"You received a {request.rating:g}-star review.",
            {
                "booking_id": str(booking.id),
                "review_id": str(review.id),
                "event": "review_received",
            },
        )

    # Prepare response with user details
    response = ReviewResponse.model_validate(review)
    response.customer_name = None if request.is_anonymous else current_user.full_name
    response.artisan_name = booking.artisan.full_name if booking.artisan else None

    return response


@router.get("/artisan/{artisan_id}", response_model=ReviewListResponse)
async def get_artisan_reviews(
    artisan_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Get all reviews for a specific artisan.

    Public endpoint - no authentication required.
    """
    # Verify artisan exists
    artisan = (
        db.query(User).filter(User.id == artisan_id, User.user_type == UserType.ARTISAN).first()
    )
    if not artisan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artisan not found")

    # Get reviews
    query = db.query(Review).filter(Review.artisan_id == artisan_id, Review.is_flagged == False)

    total = query.count()
    reviews = (
        query.order_by(Review.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Calculate average rating
    avg_rating = (
        db.query(func.avg(Review.rating))
        .filter(Review.artisan_id == artisan_id, Review.is_flagged == False)
        .scalar()
        or 0.0
    )

    # Calculate rating distribution
    rating_distribution = {}
    for i in range(1, 6):
        count = (
            db.query(func.count(Review.id))
            .filter(
                Review.artisan_id == artisan_id,
                Review.rating >= i,
                Review.rating < i + 1,
                Review.is_flagged == False,
            )
            .scalar()
            or 0
        )
        rating_distribution[str(i)] = count

    # Prepare reviews with customer names
    review_responses = []
    for review in reviews:
        customer = db.query(User).filter(User.id == review.customer_id).first()
        review_dict = ReviewResponse.model_validate(review).model_dump()
        review_dict["customer_name"] = (
            None if review.is_anonymous else (customer.full_name if customer else None)
        )
        review_dict["artisan_name"] = artisan.full_name
        review_responses.append(ReviewResponse(**review_dict))

    return {
        "reviews": review_responses,
        "total": total,
        "average_rating": float(avg_rating),
        "rating_distribution": rating_distribution,
    }


@router.get("/booking/{booking_id}", response_model=ReviewResponse)
async def get_booking_review(
    booking_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get review for a specific booking.

    Only customer or artisan involved can view.
    """
    # Get booking
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this review",
        )

    # Get review
    review = db.query(Review).filter(Review.booking_id == booking_id).first()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found for this booking"
        )

    # Prepare response
    customer = db.query(User).filter(User.id == review.customer_id).first()
    artisan = db.query(User).filter(User.id == review.artisan_id).first()

    response = ReviewResponse.model_validate(review)
    response.customer_name = (
        None if review.is_anonymous else (customer.full_name if customer else None)
    )
    response.artisan_name = artisan.full_name if artisan else None

    return response


def _err(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


@router.post(
    "/{review_id}/report", response_model=ReportReviewResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(lambda: settings.REVIEW_REPORT_IP_RATE_LIMIT)
def report_review(
    request: Request,
    review_id: int,
    body: ReportReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Report a review to the moderators (abusive, spam, fake or other).

    Any signed-in user except the review's author. One report per user per review. A report never
    hides a review by itself (so a pile-on cannot silence an honest review): it puts the review in
    the admin queue. Capped per user per hour.
    """
    # Locked so concurrent reports cannot lose an increment of the open-report counter.
    review = db.query(Review).filter(Review.id == review_id).with_for_update().first()
    if review is None:
        raise _err("review_not_found", "Review not found", status.HTTP_404_NOT_FOUND)
    if review.customer_id == current_user.id:
        raise _err(
            "cannot_report_own_review",
            "You cannot report your own review.",
            status.HTTP_403_FORBIDDEN,
        )

    already = (
        db.query(ReviewReport.id)
        .filter(ReviewReport.review_id == review_id, ReviewReport.reporter_id == current_user.id)
        .first()
    )
    if already:
        raise _err(
            "already_reported", "You have already reported this review.", status.HTTP_409_CONFLICT
        )

    recent = (
        db.query(func.count(ReviewReport.id))
        .filter(
            ReviewReport.reporter_id == current_user.id,
            ReviewReport.created_at >= datetime.now(timezone.utc) - timedelta(hours=1),
        )
        .scalar()
    )
    if recent >= settings.REVIEW_REPORTS_PER_USER_PER_HOUR:
        raise _err(
            "report_rate_limited",
            "You have reported too many reviews recently. Please try again later.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    db.add(
        ReviewReport(
            review_id=review_id,
            reporter_id=current_user.id,
            reason=body.reason,
            details=body.details.strip() if body.details else None,
        )
    )
    review.open_report_count = (review.open_report_count or 0) + 1
    try:
        db.commit()
    except IntegrityError:  # backstop for the UNIQUE (review_id, reporter_id)
        db.rollback()
        raise _err(
            "already_reported", "You have already reported this review.", status.HTTP_409_CONFLICT
        )
    return ReportReviewResponse(review_id=review_id)


@router.patch("/{review_id}/respond", response_model=ReviewResponse)
async def respond_to_review(
    review_id: int,
    request: RespondToReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Artisan responds to a review.

    Only the artisan who received the review can respond.
    """
    # Only artisans can respond to reviews
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can respond to reviews"
        )

    # Get review
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    # Check if artisan owns this review
    if review.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only respond to reviews about you",
        )

    # Update review with response
    review.artisan_response = request.artisan_response
    review.artisan_responded_at = datetime.utcnow()

    db.commit()
    db.refresh(review)

    _notify_user(
        review.customer_id,
        "Artisan responded to your review",
        f"{current_user.full_name} replied to your review.",
        {"review_id": str(review.id), "event": "review_response"},
    )

    # Prepare response
    customer = db.query(User).filter(User.id == review.customer_id).first()

    response = ReviewResponse.model_validate(review)
    response.customer_name = (
        None if review.is_anonymous else (customer.full_name if customer else None)
    )
    response.artisan_name = current_user.full_name

    return response


@router.get("/artisan/{artisan_id}/stats", response_model=ArtisanReviewStatsResponse)
async def get_artisan_review_stats(artisan_id: UUID, db: Session = Depends(get_db)):
    """
    Get review statistics for an artisan.

    Public endpoint - no authentication required.
    """
    # Verify artisan exists
    artisan = (
        db.query(User).filter(User.id == artisan_id, User.user_type == UserType.ARTISAN).first()
    )
    if not artisan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artisan not found")

    # Get artisan profile
    artisan_profile = db.query(ArtisanProfile).filter(ArtisanProfile.user_id == artisan_id).first()

    # Get total reviews
    total_reviews = (
        db.query(func.count(Review.id))
        .filter(Review.artisan_id == artisan_id, Review.is_flagged == False)
        .scalar()
        or 0
    )

    # Calculate average rating
    avg_rating = (
        db.query(func.avg(Review.rating))
        .filter(Review.artisan_id == artisan_id, Review.is_flagged == False)
        .scalar()
        or 0.0
    )

    # Calculate rating distribution
    rating_distribution = {}
    for i in range(1, 6):
        count = (
            db.query(func.count(Review.id))
            .filter(
                Review.artisan_id == artisan_id,
                Review.rating >= i,
                Review.rating < i + 1,
                Review.is_flagged == False,
            )
            .scalar()
            or 0
        )
        rating_distribution[str(i)] = count

    return {
        "artisan_id": artisan_id,
        "total_reviews": total_reviews,
        "average_rating": float(avg_rating),
        "rating_distribution": rating_distribution,
        "total_jobs_completed": artisan_profile.total_jobs_completed if artisan_profile else 0,
    }
