"""
Admin API. EVERY route sits behind ``require_admin`` (router-level dependency), so a new
route cannot accidentally be left open. List endpoints are read-only and paginated.
"""

import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_admin
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.review import Review
from app.db.models.user import User, UserType
from app.db.session import get_db
from app.schemas.admin import (
    AdminArtisanVerificationResponse,
    AdminBookingItem,
    AdminDisputeItem,
    AdminPaymentItem,
    AdminReviewDetail,
    AdminReviewItem,
    AdminUserItem,
    ArtisanRejectRequest,
    ArtisanVerifyRequest,
    Page,
    ResolveDisputeRequest,
    ResolveDisputeResponse,
    ReviewModerationRequest,
)
from app.services import admin as admin_service

router = APIRouter(dependencies=[Depends(require_admin)])

MAX_PAGE_SIZE = 100


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    ):
        self.page = page
        self.page_size = page_size


def _page(query, params: PageParams, convert, order_by) -> dict:
    total = query.order_by(None).count()
    rows = (
        query.order_by(*order_by)
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
        .all()
    )
    return {
        "items": [convert(r) for r in rows],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "pages": math.ceil(total / params.page_size) if total else 0,
    }


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# ---------------------------------------------------------------- users


@router.get("/users", response_model=Page[AdminUserItem])
def list_users(
    params: PageParams = Depends(),
    user_type: Optional[UserType] = None,
    is_active: Optional[bool] = None,
    is_admin: Optional[bool] = None,
    verification_status: Optional[str] = Query(
        None, pattern="^(unverified|pending|verified|failed)$"
    ),
    q: Optional[str] = Query(
        None, min_length=1, max_length=100, description="name / email / phone"
    ),
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    query = db.query(User).options(joinedload(User.artisan_profile))
    if user_type:
        query = query.filter(User.user_type == user_type)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if is_admin is not None:
        query = query.filter(User.is_admin == is_admin)
    if verification_status:
        query = query.join(ArtisanProfile, ArtisanProfile.user_id == User.id).filter(
            ArtisanProfile.verification_status == verification_status
        )
    if q:
        like = _like(q)
        query = query.filter(
            or_(
                User.full_name.ilike(like, escape="\\"),
                User.email.ilike(like, escape="\\"),
                User.phone_number.ilike(like, escape="\\"),
            )
        )
    if created_from:
        query = query.filter(User.created_at >= created_from)
    if created_to:
        query = query.filter(User.created_at <= created_to)

    def convert(u: User) -> AdminUserItem:
        p = u.artisan_profile
        return AdminUserItem(
            id=str(u.id),
            full_name=u.full_name,
            email=u.email,
            phone_number=u.phone_number,
            user_type=u.user_type.value,
            is_active=u.is_active,
            is_admin=u.is_admin,
            is_email_verified=u.is_email_verified,
            created_at=u.created_at,
            is_verified=p.is_verified if p else None,
            verification_status=p.verification_status if p else None,
        )

    return _page(query, params, convert, [User.created_at.desc(), User.id])


# ------------------------------------------------------------- bookings


def _booking_filters(query, status, customer_id, artisan_id, created_from, created_to, q):
    if status:
        query = query.filter(Booking.status == status)
    if customer_id:
        query = query.filter(Booking.customer_id == customer_id)
    if artisan_id:
        query = query.filter(Booking.artisan_id == artisan_id)
    if created_from:
        query = query.filter(Booking.created_at >= created_from)
    if created_to:
        query = query.filter(Booking.created_at <= created_to)
    if q:
        query = query.filter(Booking.booking_reference.ilike(_like(q), escape="\\"))
    return query


@router.get("/bookings", response_model=Page[AdminBookingItem])
def list_bookings(
    params: PageParams = Depends(),
    status: Optional[BookingStatus] = None,
    customer_id: Optional[UUID] = None,
    artisan_id: Optional[UUID] = None,
    q: Optional[str] = Query(None, min_length=1, max_length=50, description="booking reference"),
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Booking).options(
        joinedload(Booking.customer), joinedload(Booking.artisan), joinedload(Booking.payment)
    )
    query = _booking_filters(query, status, customer_id, artisan_id, created_from, created_to, q)

    def convert(b: Booking) -> AdminBookingItem:
        return AdminBookingItem(
            id=b.id,
            booking_reference=b.booking_reference,
            status=b.status.value,
            customer_id=str(b.customer_id),
            customer_name=b.customer.full_name if b.customer else None,
            artisan_id=str(b.artisan_id),
            artisan_name=b.artisan.full_name if b.artisan else None,
            agreed_amount=b.agreed_amount,
            budget_min=b.budget_min,
            budget_max=b.budget_max,
            job_date=b.job_date,
            payment_status=b.payment.status.value if b.payment else None,
            completion_disputed_at=b.completion_disputed_at,
            completion_confirmed_by_client_at=b.completion_confirmed_by_client_at,
            created_at=b.created_at,
        )

    return _page(query, params, convert, [Booking.created_at.desc(), Booking.id.desc()])


# ------------------------------------------------------------- payments


@router.get("/payments", response_model=Page[AdminPaymentItem])
def list_payments(
    params: PageParams = Depends(),
    status: Optional[PaymentStatus] = None,
    q: Optional[str] = Query(
        None, min_length=1, max_length=100, description="payment reference / customer email"
    ),
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Payment).options(joinedload(Payment.booking))
    if status:
        query = query.filter(Payment.status == status)
    if q:
        like = _like(q)
        query = query.filter(
            or_(
                Payment.payment_reference.ilike(like, escape="\\"),
                Payment.customer_email.ilike(like, escape="\\"),
            )
        )
    if created_from:
        query = query.filter(Payment.created_at >= created_from)
    if created_to:
        query = query.filter(Payment.created_at <= created_to)

    def convert(p: Payment) -> AdminPaymentItem:
        return AdminPaymentItem(
            id=p.id,
            payment_reference=p.payment_reference,
            booking_id=p.booking_id,
            booking_reference=p.booking.booking_reference if p.booking else None,
            status=p.status.value,
            amount=p.amount,
            platform_fee=p.platform_fee,
            artisan_amount=p.artisan_amount,
            currency=p.currency,
            customer_email=p.customer_email,
            paid_at=p.paid_at,
            released_at=p.released_at,
            refunded_at=p.refunded_at,
            created_at=p.created_at,
        )

    return _page(query, params, convert, [Payment.created_at.desc(), Payment.id.desc()])


# ------------------------------------------------------------- disputes


@router.get("/disputes", response_model=Page[AdminDisputeItem])
def list_disputes(
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    """Unresolved disputes, oldest first (longest waiting at the top)."""
    query = (
        db.query(Booking)
        .options(
            joinedload(Booking.customer), joinedload(Booking.artisan), joinedload(Booking.payment)
        )
        .filter(
            Booking.completion_disputed_at.is_not(None), Booking.status == BookingStatus.DISPUTED
        )
    )

    def convert(b: Booking) -> AdminDisputeItem:
        return AdminDisputeItem(
            booking_id=b.id,
            booking_reference=b.booking_reference,
            customer_id=str(b.customer_id),
            customer_name=b.customer.full_name if b.customer else None,
            artisan_id=str(b.artisan_id),
            artisan_name=b.artisan.full_name if b.artisan else None,
            agreed_amount=b.agreed_amount,
            payment_status=b.payment.status.value if b.payment else None,
            disputed_at=b.completion_disputed_at,
            dispute_reason=b.completion_dispute_reason,
            completion_notes=b.completion_notes,
        )

    return _page(query, params, convert, [Booking.completion_disputed_at.asc(), Booking.id])


@router.post("/bookings/{booking_id}/resolve-dispute", response_model=ResolveDisputeResponse)
def resolve_dispute(
    booking_id: int,
    body: ResolveDisputeRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_service.resolve_dispute(db, admin, booking_id, body.resolution, body.note.strip())


# ------------------------------------------------------------ artisans


@router.post("/artisans/{user_id}/verify", response_model=AdminArtisanVerificationResponse)
def verify_artisan(
    user_id: UUID,
    body: ArtisanVerifyRequest = ArtisanVerifyRequest(),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_service.admin_verify_artisan(db, admin, user_id, body.note)


@router.post("/artisans/{user_id}/reject", response_model=AdminArtisanVerificationResponse)
def reject_artisan(
    user_id: UUID,
    body: ArtisanRejectRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_service.admin_reject_artisan(db, admin, user_id, body.note.strip())


# ------------------------------------------------------------- reviews


@router.get("/reviews", response_model=Page[AdminReviewItem])
def list_reviews(
    params: PageParams = Depends(),
    queue: str = Query(
        "needs_attention",
        pattern="^(needs_attention|flagged|reported)$",
        description="flagged = hidden, reported = open user reports, needs_attention = either",
    ),
    artisan_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    """Moderation queue: hidden (flagged) reviews and reviews with open user reports."""
    query = db.query(Review).options(joinedload(Review.customer), joinedload(Review.artisan))
    if queue == "flagged":
        query = query.filter(Review.is_flagged.is_(True))
    elif queue == "reported":
        query = query.filter(Review.open_report_count > 0)
    else:
        query = query.filter(or_(Review.is_flagged.is_(True), Review.open_report_count > 0))
    if artisan_id:
        query = query.filter(Review.artisan_id == artisan_id)
    return _page(
        query,
        params,
        admin_service.review_item,
        [Review.open_report_count.desc(), Review.created_at.desc(), Review.id.desc()],
    )


@router.get("/reviews/{review_id}", response_model=AdminReviewDetail)
def get_review(review_id: int, db: Session = Depends(get_db)):
    review = (
        db.query(Review)
        .options(joinedload(Review.customer), joinedload(Review.artisan))
        .filter(Review.id == review_id)
        .first()
    )
    if review is None:
        raise admin_service._err("review_not_found", "Review not found", 404)
    return admin_service.review_detail(db, review)


@router.post("/reviews/{review_id}/flag", response_model=AdminReviewItem)
def flag_review(
    review_id: int,
    body: ReviewModerationRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_service.admin_flag_review(db, admin, review_id, body.note.strip())


@router.post("/reviews/{review_id}/unflag", response_model=AdminReviewItem)
def unflag_review(
    review_id: int,
    body: ReviewModerationRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return admin_service.admin_unflag_review(db, admin, review_id, body.note.strip())
