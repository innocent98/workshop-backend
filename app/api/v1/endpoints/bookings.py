"""
Booking endpoints for managing service bookings.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from geoalchemy2.elements import WKTElement
from datetime import datetime, timedelta, timezone
import json

from app.db.session import get_db
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models.user import User, UserType
from app.db.models.booking import Booking, BookingStatus
from app.db.models.service import Service
from app.db.models.artisan_profile import ArtisanProfile
from app.schemas.booking import (
    CreateBookingRequest,
    AcceptBookingRequest,
    RejectBookingRequest,
    CancelBookingRequest,
    CompleteBookingRequest,
    DisputeCompletionRequest,
    BookingResponse,
    BookingListResponse,
    BookingStatsResponse,
)
from app.utils.booking_reference import generate_booking_reference


router = APIRouter()


def _booking_to_response(booking: Booking, db: Session) -> dict:
    """Convert Booking model to response dict with lat/lng extraction"""
    # Extract latitude and longitude from PostGIS POINT
    job_latitude = None
    job_longitude = None

    if booking.job_location:
        try:
            # Use SQLAlchemy to extract coordinates from PostGIS POINT
            result = db.execute(
                func.ST_Y(func.ST_AsText(booking.job_location)),
            ).scalar()
            job_latitude = float(result) if result else None

            result = db.execute(
                func.ST_X(func.ST_AsText(booking.job_location)),
            ).scalar()
            job_longitude = float(result) if result else None
        except Exception:
            # Fallback: coordinates will be None
            pass

    # Parse completion_images JSON
    completion_images = None
    if booking.completion_images:
        try:
            completion_images = json.loads(booking.completion_images)
        except json.JSONDecodeError:
            completion_images = None

    return {
        "id": booking.id,
        "booking_reference": booking.booking_reference,
        "customer_id": booking.customer_id,
        "artisan_id": booking.artisan_id,
        "service_id": booking.service_id,
        "customer_name": booking.customer.full_name if booking.customer else None,
        "customer_profile_picture_url": booking.customer.profile_picture_url if booking.customer else None,
        "customer_phone_number": booking.customer.phone_number if booking.customer else None,
        "artisan_name": booking.artisan.full_name if booking.artisan else None,
        "artisan_profile_picture_url": booking.artisan.profile_picture_url if booking.artisan else None,
        "artisan_phone_number": booking.artisan.phone_number if booking.artisan else None,
        "service_name": booking.service.name if booking.service else None,
        "service_image": booking.service.image if booking.service else None,
        "job_description": booking.job_description,
        "job_date": booking.job_date,
        "job_address": booking.job_address,
        "job_latitude": job_latitude,
        "job_longitude": job_longitude,
        "budget_min": booking.budget_min,
        "budget_max": booking.budget_max,
        "agreed_amount": booking.agreed_amount,
        "status": booking.status.value,
        "accepted_at": booking.accepted_at,
        "paid_at": booking.paid_at,
        "started_at": booking.started_at,
        "completed_at": booking.completed_at,
        "cancelled_at": booking.cancelled_at,
        "completion_notes": booking.completion_notes,
        "completion_images": completion_images,
        "completion_marked_by_artisan_at": booking.completion_marked_by_artisan_at,
        "completion_confirmed_by_client_at": booking.completion_confirmed_by_client_at,
        "completion_confirmation_deadline_at": booking.completion_confirmation_deadline_at,
        "completion_disputed_at": booking.completion_disputed_at,
        "completion_dispute_reason": booking.completion_dispute_reason,
        "cancellation_reason": booking.cancellation_reason,
        "rejection_reason": booking.rejection_reason,
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
    }


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: CreateBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new booking request.

    Only customers can create bookings.
    """
    # Only customers can create bookings
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create bookings"
        )

    # Verify artisan exists and is active
    artisan = db.query(User).filter(
        User.id == request.artisan_id,
        User.user_type == UserType.ARTISAN,
        User.is_active == True
    ).first()
    if not artisan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artisan not found or inactive"
        )

    # Verify service exists
    service = db.query(Service).filter(Service.id == request.service_id).first()
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service not found"
        )

    # Generate booking reference
    booking_reference = generate_booking_reference(db)

    # Create PostGIS POINT from latitude and longitude
    job_location = WKTElement(f'POINT({request.job_longitude} {request.job_latitude})', srid=4326)

    # Create booking
    booking = Booking(
        booking_reference=booking_reference,
        customer_id=current_user.id,
        artisan_id=request.artisan_id,
        service_id=request.service_id,
        job_description=request.job_description,
        job_date=request.job_date,
        job_location=job_location,
        job_address=request.job_address,
        budget_min=request.budget_min,
        budget_max=request.budget_max,
        status=BookingStatus.PENDING
    )

    db.add(booking)
    db.commit()
    db.refresh(booking)

    return _booking_to_response(booking, db)


@router.get("", response_model=BookingListResponse)
async def list_bookings(
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List user's bookings.

    - Customers see bookings they created
    - Artisans see bookings assigned to them
    """
    # Base query based on user type
    if current_user.user_type == UserType.CLIENT:
        query = db.query(Booking).options(
            joinedload(Booking.customer),
            joinedload(Booking.artisan),
            joinedload(Booking.service),
        ).filter(Booking.customer_id == current_user.id)
    else:
        query = db.query(Booking).options(
            joinedload(Booking.customer),
            joinedload(Booking.artisan),
            joinedload(Booking.service),
        ).filter(Booking.artisan_id == current_user.id)

    # Apply status filter
    if status_filter:
        try:
            status_enum = BookingStatus(status_filter)
            query = query.filter(Booking.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}"
            )

    # Get total count
    total = query.count()

    # Apply pagination
    bookings = query.order_by(Booking.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "bookings": [_booking_to_response(b, db) for b in bookings],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/stats", response_model=BookingStatsResponse)
async def get_booking_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user's booking statistics.

    Returns counts for each booking status.
    """
    # Base query based on user type
    if current_user.user_type == UserType.CLIENT:
        base_query = db.query(Booking).filter(Booking.customer_id == current_user.id)
    else:
        base_query = db.query(Booking).filter(Booking.artisan_id == current_user.id)

    # Get counts for each status
    stats = {
        "total_bookings": base_query.count(),
        "pending_bookings": base_query.filter(Booking.status == BookingStatus.PENDING).count(),
        "accepted_bookings": base_query.filter(Booking.status == BookingStatus.ACCEPTED).count(),
        "paid_bookings": base_query.filter(Booking.status == BookingStatus.PAID).count(),
        "in_progress_bookings": base_query.filter(Booking.status == BookingStatus.IN_PROGRESS).count(),
        "completed_bookings": base_query.filter(Booking.status == BookingStatus.COMPLETED).count(),
        "cancelled_bookings": base_query.filter(Booking.status == BookingStatus.CANCELLED).count(),
        "rejected_bookings": base_query.filter(Booking.status == BookingStatus.REJECTED).count(),
        "disputed_bookings": base_query.filter(Booking.status == BookingStatus.DISPUTED).count(),
    }

    return stats


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get booking details.

    Only customer or artisan involved in the booking can view it.
    """
    booking = db.query(Booking).options(
        joinedload(Booking.customer),
        joinedload(Booking.artisan),
        joinedload(Booking.service),
    ).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this booking"
        )

    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
async def accept_booking(
    booking_id: int,
    request: AcceptBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Artisan accepts a booking.

    Sets agreed_amount and changes status to ACCEPTED.
    """
    # Only artisans can accept bookings
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can accept bookings"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check if artisan is assigned to this booking
    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this booking"
        )

    # Check if booking is in PENDING status
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot accept booking in {booking.status.value} status"
        )

    # Validate agreed_amount is within budget range
    if not (booking.budget_min <= request.agreed_amount <= booking.budget_max):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agreed amount must be between {booking.budget_min} and {booking.budget_max}"
        )

    # Update booking
    booking.agreed_amount = request.agreed_amount
    booking.status = BookingStatus.ACCEPTED
    booking.accepted_at = func.now()

    db.commit()
    db.refresh(booking)

    # TODO: Send notification to customer

    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/reject", response_model=BookingResponse)
async def reject_booking(
    booking_id: int,
    request: RejectBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Artisan rejects a booking.

    Changes status to REJECTED with reason.
    """
    # Only artisans can reject bookings
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can reject bookings"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check if artisan is assigned to this booking
    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this booking"
        )

    # Check if booking is in PENDING status
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject booking in {booking.status.value} status"
        )

    # Update booking
    booking.status = BookingStatus.REJECTED
    booking.rejection_reason = request.rejection_reason

    db.commit()
    db.refresh(booking)

    # TODO: Send notification to customer

    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/start", response_model=BookingResponse)
async def start_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Artisan marks booking as started.

    Changes status from PAID to IN_PROGRESS.
    """
    # Only artisans can start bookings
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can start bookings"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check if artisan is assigned to this booking
    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this booking"
        )

    # Check if booking is in PAID status
    if booking.status != BookingStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start booking in {booking.status.value} status. Payment must be completed first."
        )

    # Update booking
    booking.status = BookingStatus.IN_PROGRESS
    booking.started_at = func.now()

    db.commit()
    db.refresh(booking)

    # TODO: Send notification to customer

    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/complete", response_model=BookingResponse)
async def complete_booking(
    booking_id: int,
    request: CompleteBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Artisan marks booking as completed.

    Changes status from IN_PROGRESS to COMPLETED with optional notes and images.
    """
    # Only artisans can complete bookings
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can complete bookings"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check if artisan is assigned to this booking
    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this booking"
        )

    # Check if booking is in IN_PROGRESS status
    if booking.status != BookingStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete booking in {booking.status.value} status"
        )

    # Update booking
    booking.status = BookingStatus.COMPLETED
    now_utc = datetime.now(timezone.utc)
    booking.completed_at = now_utc
    booking.completion_marked_by_artisan_at = now_utc
    booking.completion_confirmation_deadline_at = now_utc + timedelta(
        hours=settings.COMPLETION_DISPUTE_WINDOW_HOURS
    )
    booking.completion_confirmed_by_client_at = None
    booking.completion_disputed_at = None
    booking.completion_dispute_reason = None
    booking.completion_notes = request.completion_notes

    # Store completion images as JSON
    if request.completion_images:
        booking.completion_images = json.dumps(request.completion_images)

    db.commit()
    db.refresh(booking)

    # TODO: Send notification to customer to confirm completion

    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/confirm-completion", response_model=BookingResponse)
async def confirm_booking_completion(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Customer confirms completed job.

    This marks job completion as verified by customer and makes payout eligible.
    """
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can confirm completion"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't own this booking"
        )

    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm completion for booking in {booking.status.value} status"
        )

    if booking.completion_disputed_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completion is disputed and cannot be confirmed"
        )

    booking.completion_confirmed_by_client_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(booking)
    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/dispute-completion", response_model=BookingResponse)
async def dispute_booking_completion(
    booking_id: int,
    request: DisputeCompletionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Customer disputes a completion marked by artisan.

    Disputes are only accepted during the dispute window.
    """
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can dispute completion"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't own this booking"
        )

    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot dispute completion for booking in {booking.status.value} status"
        )

    if booking.completion_confirmed_by_client_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completion already confirmed"
        )

    now_utc = datetime.now(timezone.utc)
    if (
        booking.completion_confirmation_deadline_at
        and now_utc > booking.completion_confirmation_deadline_at
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispute window has elapsed"
        )

    booking.status = BookingStatus.DISPUTED
    booking.completion_disputed_at = now_utc
    booking.completion_dispute_reason = request.dispute_reason

    db.commit()
    db.refresh(booking)
    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: int,
    request: CancelBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Customer cancels a booking.

    Can only cancel before payment (PENDING or ACCEPTED status).
    """
    # Only customers can cancel bookings
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can cancel bookings"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check if customer owns this booking
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't own this booking"
        )

    # Check if booking can be cancelled
    if booking.status not in [BookingStatus.PENDING, BookingStatus.ACCEPTED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel booking in {booking.status.value} status. Contact support for paid bookings."
        )

    # Update booking
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = func.now()
    booking.cancellation_reason = request.cancellation_reason

    db.commit()
    db.refresh(booking)

    # TODO: Send notification to artisan

    return _booking_to_response(booking, db)
