"""
Review endpoints for customer ratings and feedback.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from uuid import UUID

from app.db.session import get_db
from app.api.deps import get_current_user
from app.db.models.user import User, UserType
from app.db.models.booking import Booking, BookingStatus
from app.db.models.review import Review
from app.db.models.artisan_profile import ArtisanProfile
from app.services.notify import notify_user as _notify_user
from app.schemas.review import (
    CreateReviewRequest,
    RespondToReviewRequest,
    ReviewResponse,
    ReviewListResponse,
    ArtisanReviewStatsResponse,
)


router = APIRouter()


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    request: CreateReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a review for a completed booking.

    Only customers can create reviews and only after job completion.
    One review per booking.
    """
    # Only customers can create reviews
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create reviews"
        )

    # Get booking
    booking = db.query(Booking).filter(Booking.id == request.booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check ownership
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only review your own bookings"
        )

    # Check booking status
    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only review completed bookings"
        )
    if booking.completion_disputed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot review a disputed booking"
        )
    if booking.completion_confirmed_by_client_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only review after completion has been confirmed"
        )

    # Check if review already exists
    existing_review = db.query(Review).filter(Review.booking_id == request.booking_id).first()
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Review already exists for this booking"
        )

    # Create review
    review = Review(
        booking_id=request.booking_id,
        customer_id=current_user.id,
        artisan_id=booking.artisan_id,
        rating=request.rating,
        review_text=request.review_text,
        is_anonymous=request.is_anonymous
    )

    db.add(review)

    # Update artisan statistics
    artisan_profile = db.query(ArtisanProfile).filter(
        ArtisanProfile.user_id == booking.artisan_id
    ).first()

    if artisan_profile:
        # Flush the new review so aggregate queries include it
        db.flush()

        # Recalculate ratings from source of truth
        total_reviews, avg_rating = db.query(
            func.count(Review.id),
            func.avg(Review.rating),
        ).filter(
            Review.artisan_id == booking.artisan_id,
            Review.is_flagged == False,  # noqa: E712
        ).one()

        # Update profile
        artisan_profile.total_ratings = int(total_reviews or 0)
        artisan_profile.average_rating = float(avg_rating or 0.0)
        artisan_profile.total_jobs_completed = (artisan_profile.total_jobs_completed or 0) + 1

    db.commit()
    db.refresh(review)

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
    db: Session = Depends(get_db)
):
    """
    Get all reviews for a specific artisan.

    Public endpoint - no authentication required.
    """
    # Verify artisan exists
    artisan = db.query(User).filter(
        User.id == artisan_id,
        User.user_type == UserType.ARTISAN
    ).first()
    if not artisan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artisan not found"
        )

    # Get reviews
    query = db.query(Review).filter(
        Review.artisan_id == artisan_id,
        Review.is_flagged == False
    )

    total = query.count()
    reviews = query.order_by(Review.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Calculate average rating
    avg_rating = db.query(func.avg(Review.rating)).filter(
        Review.artisan_id == artisan_id,
        Review.is_flagged == False
    ).scalar() or 0.0

    # Calculate rating distribution
    rating_distribution = {}
    for i in range(1, 6):
        count = db.query(func.count(Review.id)).filter(
            Review.artisan_id == artisan_id,
            Review.rating >= i,
            Review.rating < i + 1,
            Review.is_flagged == False
        ).scalar() or 0
        rating_distribution[str(i)] = count

    # Prepare reviews with customer names
    review_responses = []
    for review in reviews:
        customer = db.query(User).filter(User.id == review.customer_id).first()
        review_dict = ReviewResponse.model_validate(review).model_dump()
        review_dict['customer_name'] = None if review.is_anonymous else (customer.full_name if customer else None)
        review_dict['artisan_name'] = artisan.full_name
        review_responses.append(ReviewResponse(**review_dict))

    return {
        "reviews": review_responses,
        "total": total,
        "average_rating": float(avg_rating),
        "rating_distribution": rating_distribution
    }


@router.get("/booking/{booking_id}", response_model=ReviewResponse)
async def get_booking_review(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get review for a specific booking.

    Only customer or artisan involved can view.
    """
    # Get booking
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this review"
        )

    # Get review
    review = db.query(Review).filter(Review.booking_id == booking_id).first()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found for this booking"
        )

    # Prepare response
    customer = db.query(User).filter(User.id == review.customer_id).first()
    artisan = db.query(User).filter(User.id == review.artisan_id).first()

    response = ReviewResponse.model_validate(review)
    response.customer_name = None if review.is_anonymous else (customer.full_name if customer else None)
    response.artisan_name = artisan.full_name if artisan else None

    return response


@router.patch("/{review_id}/respond", response_model=ReviewResponse)
async def respond_to_review(
    review_id: int,
    request: RespondToReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Artisan responds to a review.

    Only the artisan who received the review can respond.
    """
    # Only artisans can respond to reviews
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can respond to reviews"
        )

    # Get review
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )

    # Check if artisan owns this review
    if review.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only respond to reviews about you"
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
    response.customer_name = None if review.is_anonymous else (customer.full_name if customer else None)
    response.artisan_name = current_user.full_name

    return response


@router.get("/artisan/{artisan_id}/stats", response_model=ArtisanReviewStatsResponse)
async def get_artisan_review_stats(
    artisan_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get review statistics for an artisan.

    Public endpoint - no authentication required.
    """
    # Verify artisan exists
    artisan = db.query(User).filter(
        User.id == artisan_id,
        User.user_type == UserType.ARTISAN
    ).first()
    if not artisan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artisan not found"
        )

    # Get artisan profile
    artisan_profile = db.query(ArtisanProfile).filter(
        ArtisanProfile.user_id == artisan_id
    ).first()

    # Get total reviews
    total_reviews = db.query(func.count(Review.id)).filter(
        Review.artisan_id == artisan_id,
        Review.is_flagged == False
    ).scalar() or 0

    # Calculate average rating
    avg_rating = db.query(func.avg(Review.rating)).filter(
        Review.artisan_id == artisan_id,
        Review.is_flagged == False
    ).scalar() or 0.0

    # Calculate rating distribution
    rating_distribution = {}
    for i in range(1, 6):
        count = db.query(func.count(Review.id)).filter(
            Review.artisan_id == artisan_id,
            Review.rating >= i,
            Review.rating < i + 1,
            Review.is_flagged == False
        ).scalar() or 0
        rating_distribution[str(i)] = count

    return {
        "artisan_id": artisan_id,
        "total_reviews": total_reviews,
        "average_rating": float(avg_rating),
        "rating_distribution": rating_distribution,
        "total_jobs_completed": artisan_profile.total_jobs_completed if artisan_profile else 0
    }
