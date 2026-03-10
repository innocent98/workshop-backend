"""
Booking endpoints for managing service bookings.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
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
from app.db.models.booking_progress_log import BookingProgressLog
from app.db.models.service import Service, UserService
from app.db.models.artisan_profile import ArtisanProfile
from app.schemas.booking import (
    CreateBookingRequest,
    AcceptBookingRequest,
    RejectBookingRequest,
    CancelBookingRequest,
    CompleteBookingRequest,
    NegotiateBookingRequest,
    NegotiateResponseRequest,
    DisputeCompletionRequest,
    BookingProgressLogResponse,
    BookingResponse,
    BookingListResponse,
    BookingStatsResponse,
)
from app.utils.booking_reference import generate_booking_reference
from app.utils.file_upload import save_booking_progress_image
from app.tasks.notification_tasks import send_push_notification


router = APIRouter()
NEGOTIATION_STATUS_NONE = "none"
NEGOTIATION_STATUS_PENDING_CLIENT = "pending_client"
NEGOTIATION_STATUS_PENDING_ARTISAN = "pending_artisan"
NEGOTIATION_STATUS_AGREED = "agreed"
NEGOTIATION_STATUS_DECLINED = "declined"
NEGOTIATION_MAX_ROUNDS_PER_SIDE = 2

def _notify_user(user_id, title: str, body: str, data: Optional[dict] = None) -> None:
    try:
        send_push_notification.delay(
            user_id=str(user_id),
            title=title,
            body=body,
            data=data or {},
        )
    except Exception:
        # Notifications must not break booking flow
        pass


def _ensure_pending_booking(booking: Booking, action: str) -> None:
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot {action} booking in {booking.status.value} status",
        )


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

    progress_logs = []
    for log in booking.progress_logs or []:
        progress_logs.append(
            {
                "id": log.id,
                "booking_id": log.booking_id,
                "artisan_id": log.artisan_id,
                "description": log.description,
                "image_url": log.image_url,
                "created_at": log.created_at,
            }
        )

    selected_service_ids = []
    selected_service_names = []
    if booking.selected_service_ids:
        try:
            selected_service_ids = json.loads(booking.selected_service_ids)
            if not isinstance(selected_service_ids, list):
                selected_service_ids = []
        except json.JSONDecodeError:
            selected_service_ids = []

    if selected_service_ids:
        selected_services = (
            db.query(Service.id, Service.name)
            .filter(Service.id.in_(selected_service_ids))
            .all()
        )
        by_id = {sid: name for sid, name in selected_services}
        selected_service_names = [
            by_id[sid] for sid in selected_service_ids if sid in by_id
        ]
    elif booking.service_id:
        selected_service_ids = [booking.service_id]
        if booking.service:
            selected_service_names = [booking.service.name]

    return {
        "id": booking.id,
        "booking_reference": booking.booking_reference,
        "customer_id": booking.customer_id,
        "artisan_id": booking.artisan_id,
        "service_id": booking.service_id,
        "selected_service_ids": selected_service_ids,
        "selected_service_names": selected_service_names,
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
        "negotiated_amount": booking.negotiated_amount,
        "negotiation_condition": booking.negotiation_condition,
        "negotiation_status": booking.negotiation_status or NEGOTIATION_STATUS_NONE,
        "negotiation_last_offer_by": booking.negotiation_last_offer_by,
        "artisan_negotiation_rounds_used": booking.artisan_negotiation_rounds_used or 0,
        "client_negotiation_rounds_used": booking.client_negotiation_rounds_used or 0,
        "negotiation_started_at": booking.negotiation_started_at,
        "negotiation_updated_at": booking.negotiation_updated_at,
        "negotiation_agreed_at": booking.negotiation_agreed_at,
        "negotiation_declined_at": booking.negotiation_declined_at,
        "negotiated_override": bool(booking.negotiated_override),
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
        "progress_logs": progress_logs,
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

    requested_service_ids = request.service_ids or (
        [request.service_id] if request.service_id is not None else []
    )
    requested_service_ids = list(dict.fromkeys(requested_service_ids))
    if not requested_service_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one service must be selected",
        )

    selected_services = (
        db.query(Service)
        .filter(Service.id.in_(requested_service_ids))
        .all()
    )
    if len(selected_services) != len(requested_service_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more selected services were not found",
        )

    artisan_service_ids = {
        service_id
        for (service_id,) in db.query(UserService.service_id)
        .filter(UserService.user_id == artisan.id)
        .all()
    }
    if not artisan_service_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Artisan has no configured services",
        )
    if not set(requested_service_ids).issubset(artisan_service_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected services must be offered by this artisan",
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
        service_id=requested_service_ids[0],
        selected_service_ids=json.dumps(requested_service_ids),
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

    _notify_user(
        artisan.id,
        "New booking request",
        f"{current_user.full_name} requested {', '.join([s.name for s in selected_services])}.",
        {"booking_id": str(booking.id), "event": "booking_created"},
    )

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
            joinedload(Booking.progress_logs),
        ).filter(Booking.customer_id == current_user.id)
    else:
        query = db.query(Booking).options(
            joinedload(Booking.customer),
            joinedload(Booking.artisan),
            joinedload(Booking.service),
            joinedload(Booking.progress_logs),
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
        joinedload(Booking.progress_logs),
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


@router.patch("/{booking_id}/negotiate", response_model=BookingResponse)
async def negotiate_booking(
    booking_id: int,
    request: NegotiateBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Artisan starts/counters negotiation on a pending booking.

    Rules:
    - Only artisan can initiate the first offer.
    - Max 2 negotiation rounds per side.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can negotiate booking price"
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this booking"
        )

    _ensure_pending_booking(booking, "negotiate")

    now_utc = datetime.now(timezone.utc)
    current_status = booking.negotiation_status or NEGOTIATION_STATUS_NONE

    if current_status in {NEGOTIATION_STATUS_AGREED, NEGOTIATION_STATUS_DECLINED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Negotiation is already closed for this booking"
        )

    if booking.negotiation_last_offer_by == "artisan" and current_status == NEGOTIATION_STATUS_PENDING_CLIENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Waiting for client response to your last offer"
        )

    if booking.artisan_negotiation_rounds_used >= NEGOTIATION_MAX_ROUNDS_PER_SIDE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Artisan negotiation rounds exhausted (max 2)"
        )

    # First offer must come from artisan; this endpoint enforces artisan identity already.
    if current_status == NEGOTIATION_STATUS_NONE:
        booking.negotiation_started_at = now_utc

    booking.negotiated_amount = request.negotiated_amount
    booking.negotiation_condition = request.negotiation_condition.strip()
    booking.negotiation_status = NEGOTIATION_STATUS_PENDING_CLIENT
    booking.negotiation_last_offer_by = "artisan"
    booking.artisan_negotiation_rounds_used = (booking.artisan_negotiation_rounds_used or 0) + 1
    booking.negotiation_updated_at = now_utc
    booking.negotiation_agreed_at = None
    booking.negotiation_declined_at = None
    booking.negotiated_override = False

    db.commit()
    db.refresh(booking)

    _notify_user(
        booking.customer_id,
        "New price negotiation",
        f"Artisan proposed ₦{float(request.negotiated_amount):.0f}. Round {booking.artisan_negotiation_rounds_used}/2.",
        {"booking_id": str(booking.id), "event": "booking_negotiation_proposed"},
    )

    return _booking_to_response(booking, db)


@router.patch("/{booking_id}/negotiate/respond", response_model=BookingResponse)
async def respond_to_negotiation(
    booking_id: int,
    request: NegotiateResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Client responds to artisan negotiation (agree/counter/decline).

    Rules:
    - Client can only respond after artisan sends first negotiation.
    - Decline immediately cancels booking.
    - Client has max 2 rounds for counter-offers.
    """
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can respond to negotiation"
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

    _ensure_pending_booking(booking, "respond to negotiation")

    current_status = booking.negotiation_status or NEGOTIATION_STATUS_NONE
    now_utc = datetime.now(timezone.utc)
    action = request.action.lower()

    if current_status in {NEGOTIATION_STATUS_NONE, NEGOTIATION_STATUS_DECLINED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active artisan negotiation to respond to"
        )

    if current_status == NEGOTIATION_STATUS_PENDING_ARTISAN and action != "decline":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Waiting for artisan response; you can only decline now"
        )

    if action == "agree":
        if booking.negotiated_amount is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No negotiated amount available to agree on"
            )

        booking.agreed_amount = booking.negotiated_amount
        booking.negotiation_status = NEGOTIATION_STATUS_AGREED
        booking.negotiation_last_offer_by = "client"
        booking.negotiation_agreed_at = now_utc
        booking.negotiation_updated_at = now_utc
        booking.negotiated_override = not (
            booking.budget_min <= booking.agreed_amount <= booking.budget_max
        )

        db.commit()
        db.refresh(booking)

        _notify_user(
            booking.artisan_id,
            "Negotiation agreed",
            "Client agreed to the negotiated price. You can now accept the booking.",
            {"booking_id": str(booking.id), "event": "booking_negotiation_agreed"},
        )
        return _booking_to_response(booking, db)

    if action == "counter":
        if request.negotiated_amount is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="negotiated_amount is required for counter action"
            )
        if not request.negotiation_condition:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="negotiation_condition is required for counter action"
            )
        if booking.client_negotiation_rounds_used >= NEGOTIATION_MAX_ROUNDS_PER_SIDE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Client negotiation rounds exhausted (max 2)"
            )

        booking.negotiated_amount = request.negotiated_amount
        booking.negotiation_condition = request.negotiation_condition.strip()
        booking.negotiation_status = NEGOTIATION_STATUS_PENDING_ARTISAN
        booking.negotiation_last_offer_by = "client"
        booking.client_negotiation_rounds_used = (booking.client_negotiation_rounds_used or 0) + 1
        booking.negotiation_updated_at = now_utc

        db.commit()
        db.refresh(booking)

        _notify_user(
            booking.artisan_id,
            "Client counter-offer received",
            f"Client proposed ₦{float(request.negotiated_amount):.0f}. Round {booking.client_negotiation_rounds_used}/2.",
            {"booking_id": str(booking.id), "event": "booking_negotiation_countered"},
        )
        return _booking_to_response(booking, db)

    # decline
    booking.negotiation_status = NEGOTIATION_STATUS_DECLINED
    booking.negotiation_last_offer_by = "client"
    booking.negotiation_declined_at = now_utc
    booking.negotiation_updated_at = now_utc
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now_utc
    booking.cancellation_reason = "Client declined negotiated price"

    db.commit()
    db.refresh(booking)

    _notify_user(
        booking.artisan_id,
        "Negotiation declined",
        "Client declined the negotiation. Booking has been cancelled.",
        {"booking_id": str(booking.id), "event": "booking_negotiation_declined"},
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

    _ensure_pending_booking(booking, "accept")

    # If negotiation has reached client counter/agreement state, artisan accepts
    # the latest negotiated amount (outside budget range allowed with override).
    if (
        booking.negotiated_amount is not None and
        (booking.negotiation_status in {NEGOTIATION_STATUS_PENDING_ARTISAN, NEGOTIATION_STATUS_AGREED})
    ):
        booking.agreed_amount = booking.negotiated_amount
        booking.negotiated_override = not (
            booking.budget_min <= booking.agreed_amount <= booking.budget_max
        )
        booking.negotiation_status = NEGOTIATION_STATUS_AGREED
        booking.negotiation_agreed_at = datetime.now(timezone.utc)
        booking.negotiation_updated_at = datetime.now(timezone.utc)
    else:
        # Non-negotiated acceptance must stay inside customer range.
        if not (booking.budget_min <= request.agreed_amount <= booking.budget_max):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Agreed amount must be between {booking.budget_min} and {booking.budget_max}"
            )
        booking.agreed_amount = request.agreed_amount
        booking.negotiated_override = False

    booking.status = BookingStatus.ACCEPTED
    booking.accepted_at = func.now()

    db.commit()
    db.refresh(booking)

    _notify_user(
        booking.customer_id,
        "Booking accepted",
        "Your booking was accepted by the artisan.",
        {"booking_id": str(booking.id), "event": "booking_accepted"},
    )

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

    _notify_user(
        booking.customer_id,
        "Booking rejected",
        "Your booking request was rejected by the artisan.",
        {"booking_id": str(booking.id), "event": "booking_rejected"},
    )

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

    _notify_user(
        booking.customer_id,
        "Job started",
        "The artisan has started your job.",
        {"booking_id": str(booking.id), "event": "booking_started"},
    )

    return _booking_to_response(booking, db)


@router.post(
    "/{booking_id}/progress-logs",
    response_model=BookingProgressLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_booking_progress_log(
    booking_id: int,
    description: str = Form(...),
    image: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Artisan logs progress update for a booking.

    Allowed when booking is PAID or IN_PROGRESS. Image is optional.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can log booking progress",
        )

    description = (description or "").strip()
    if len(description) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Progress description must be at least 5 characters",
        )
    if len(description) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Progress description must not exceed 1000 characters",
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this booking",
        )

    if booking.status not in [BookingStatus.PAID, BookingStatus.IN_PROGRESS]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot log progress for booking in {booking.status.value} status",
        )

    image_url = None
    if image is not None:
        image_url = await save_booking_progress_image(
            image,
            str(current_user.id),
            booking.id,
        )
        if not image_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload progress image",
            )

    progress_log = BookingProgressLog(
        booking_id=booking.id,
        artisan_id=current_user.id,
        description=description,
        image_url=image_url,
    )
    db.add(progress_log)
    db.commit()
    db.refresh(progress_log)

    _notify_user(
        booking.customer_id,
        "New job progress",
        "Artisan posted a new progress update on your booking.",
        {"booking_id": str(booking.id), "event": "progress_logged"},
    )

    return progress_log


@router.get(
    "/{booking_id}/progress-logs",
    response_model=List[BookingProgressLogResponse],
)
async def list_booking_progress_logs(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List booking progress logs.

    Visible to customer and artisan involved in the booking.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this booking progress",
        )

    logs = (
        db.query(BookingProgressLog)
        .filter(BookingProgressLog.booking_id == booking.id)
        .order_by(BookingProgressLog.created_at.asc())
        .all()
    )
    return logs


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

    progress_count = db.query(func.count(BookingProgressLog.id)).filter(
        BookingProgressLog.booking_id == booking.id
    ).scalar() or 0
    if progress_count < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Log at least one progress update before completing this booking",
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

    _notify_user(
        booking.customer_id,
        "Job completed",
        "The artisan marked your job as completed. Please confirm completion.",
        {"booking_id": str(booking.id), "event": "booking_completed"},
    )

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
    _notify_user(
        booking.artisan_id,
        "Completion confirmed",
        "Client confirmed job completion.",
        {"booking_id": str(booking.id), "event": "completion_confirmed"},
    )
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

    _notify_user(
        booking.artisan_id,
        "Booking cancelled",
        "A customer cancelled a booking request.",
        {"booking_id": str(booking.id), "event": "booking_cancelled"},
    )

    return _booking_to_response(booking, db)
