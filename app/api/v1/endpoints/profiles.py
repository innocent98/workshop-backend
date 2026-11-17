"""
User Profile endpoints (Customer and Artisan).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.logger import logger
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.portfolio import Portfolio
from app.db.models.service import Service, UserService
from app.db.models.user import User, UserType
from app.db.session import get_db
from app.schemas.portfolio import PortfolioResponse, PortfolioUpdate
from app.schemas.profile import (
    ArtisanAvailabilityUpdate,
    ArtisanProfileResponse,
    ArtisanProfileUpdate,
    ArtisanPublicProfileResponse,
    ArtisanServiceSelectionResponse,
    ArtisanServiceSelectionUpdate,
    ArtisanStatsResponse,
    CustomerProfileResponse,
    CustomerProfileUpdate,
    ProfilePictureResponse,
)
from app.utils.file_upload import delete_image, save_portfolio_image, save_profile_picture
from app.utils.location import resolve_location_label

router = APIRouter()


def _format_coordinates_address(latitude: float, longitude: float) -> str:
    """Build a readable fallback address from coordinates."""
    return f"{latitude:.5f}, {longitude:.5f}"


def _resolve_address_or_fallback(latitude: float, longitude: float) -> str:
    """Resolve a human-readable area/state label; fallback to coordinates."""
    resolved = resolve_location_label(latitude, longitude)
    if resolved and resolved.strip():
        return resolved.strip()
    return _format_coordinates_address(latitude, longitude)


# ==================== Customer Profile Endpoints ====================


@router.get("/customers/me", response_model=CustomerProfileResponse)
def get_my_customer_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get current user's customer profile.
    Available to all users (customers and artisans).
    """
    # Manually build response to convert UUID to string
    return {
        "id": str(current_user.id),
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone_number": current_user.phone_number,
        "profile_picture_url": current_user.profile_picture_url,
        "bio": current_user.bio,
        "location_address": current_user.location_address,
        "location_latitude": current_user.location_latitude,
        "location_longitude": current_user.location_longitude,
        "is_email_verified": current_user.is_email_verified,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
    }


@router.put("/customers/me", response_model=CustomerProfileResponse)
def update_my_customer_profile(
    profile_update: CustomerProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update current user's customer profile.
    """
    try:
        # Update fields
        if profile_update.full_name is not None:
            current_user.full_name = profile_update.full_name
        if profile_update.phone_number is not None:
            # Check if phone number is already taken by another user
            existing = (
                db.query(User)
                .filter(
                    User.phone_number == profile_update.phone_number, User.id != current_user.id
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number already registered",
                )
            current_user.phone_number = profile_update.phone_number
        if profile_update.bio is not None:
            current_user.bio = profile_update.bio
        if profile_update.location is not None:
            current_user.location_latitude = profile_update.location.latitude
            current_user.location_longitude = profile_update.location.longitude
            current_user.location_address = (
                profile_update.location.address
                or _resolve_address_or_fallback(
                    profile_update.location.latitude,
                    profile_update.location.longitude,
                )
            )
        if profile_update.location_address is not None:
            current_user.location_address = profile_update.location_address

        db.commit()
        db.refresh(current_user)

        logger.info(f"Customer profile updated for user {current_user.id}")

        # Manually build response to convert UUID to string
        return {
            "id": str(current_user.id),
            "full_name": current_user.full_name,
            "email": current_user.email,
            "phone_number": current_user.phone_number,
            "profile_picture_url": current_user.profile_picture_url,
            "bio": current_user.bio,
            "location_address": current_user.location_address,
            "location_latitude": current_user.location_latitude,
            "location_longitude": current_user.location_longitude,
            "is_email_verified": current_user.is_email_verified,
            "is_active": current_user.is_active,
            "created_at": current_user.created_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating customer profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update profile"
        )


# ==================== Artisan Profile Endpoints ====================


@router.get("/artisans/me", response_model=ArtisanProfileResponse)
def get_my_artisan_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get current user's artisan profile (private view).
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    # Get or create artisan profile
    artisan_profile = (
        db.query(ArtisanProfile).filter(ArtisanProfile.user_id == current_user.id).first()
    )

    if not artisan_profile:
        # Create default profile
        artisan_profile = ArtisanProfile(user_id=current_user.id)
        db.add(artisan_profile)
        db.commit()
        db.refresh(artisan_profile)
        logger.info(f"Created artisan profile for user {current_user.id}")

    # Combine user and artisan profile data
    response_data = {
        "id": str(current_user.id),
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone_number": current_user.phone_number,
        "profile_picture_url": current_user.profile_picture_url,
        "bio": current_user.bio,
        "user_type": current_user.user_type.value,
        "location_address": artisan_profile.location_address,
        "service_radius_km": artisan_profile.service_radius_km,
        "hourly_rate_min": artisan_profile.hourly_rate_min,
        "hourly_rate_max": artisan_profile.hourly_rate_max,
        "years_of_experience": artisan_profile.years_of_experience,
        "specialization": artisan_profile.specialization,
        "is_verified": artisan_profile.is_verified,
        "verified_at": artisan_profile.verified_at,
        "verification_status": artisan_profile.verification_status,
        "availability_status": artisan_profile.availability_status,
        "average_rating": artisan_profile.average_rating,
        "total_ratings": artisan_profile.total_ratings,
        "total_jobs_completed": artisan_profile.total_jobs_completed,
        "response_time_avg_minutes": artisan_profile.response_time_avg_minutes,
        "acceptance_rate": artisan_profile.acceptance_rate,
        "created_at": current_user.created_at,
    }

    return response_data


@router.put("/artisans/me", response_model=ArtisanProfileResponse)
def update_my_artisan_profile(
    profile_update: ArtisanProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update current user's artisan profile.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    try:
        if profile_update.full_name is not None:
            current_user.full_name = profile_update.full_name

        if profile_update.phone_number is not None:
            existing = (
                db.query(User)
                .filter(
                    User.phone_number == profile_update.phone_number, User.id != current_user.id
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number already registered",
                )
            current_user.phone_number = profile_update.phone_number

        if profile_update.bio is not None:
            current_user.bio = profile_update.bio

        # Get or create artisan profile
        artisan_profile = (
            db.query(ArtisanProfile).filter(ArtisanProfile.user_id == current_user.id).first()
        )

        if not artisan_profile:
            artisan_profile = ArtisanProfile(user_id=current_user.id)
            db.add(artisan_profile)

        # Update location
        if profile_update.location is not None:
            # Create PostGIS POINT
            point = func.ST_SetSRID(
                func.ST_MakePoint(
                    profile_update.location.longitude, profile_update.location.latitude
                ),
                4326,
            )
            artisan_profile.location = point

            if profile_update.location.address:
                artisan_profile.location_address = profile_update.location.address
            else:
                artisan_profile.location_address = _resolve_address_or_fallback(
                    profile_update.location.latitude,
                    profile_update.location.longitude,
                )

        # Update other fields
        if profile_update.location_address is not None:
            artisan_profile.location_address = profile_update.location_address
        if profile_update.service_radius_km is not None:
            artisan_profile.service_radius_km = profile_update.service_radius_km
        if profile_update.hourly_rate_min is not None:
            artisan_profile.hourly_rate_min = profile_update.hourly_rate_min
        if profile_update.hourly_rate_max is not None:
            artisan_profile.hourly_rate_max = profile_update.hourly_rate_max
        if profile_update.years_of_experience is not None:
            artisan_profile.years_of_experience = profile_update.years_of_experience
        if profile_update.specialization is not None:
            artisan_profile.specialization = profile_update.specialization

        db.commit()
        db.refresh(artisan_profile)

        logger.info(f"Artisan profile updated for user {current_user.id}")

        # Return combined data
        response_data = {
            "id": str(current_user.id),
            "full_name": current_user.full_name,
            "email": current_user.email,
            "phone_number": current_user.phone_number,
            "profile_picture_url": current_user.profile_picture_url,
            "bio": current_user.bio,
            "user_type": current_user.user_type.value,
            "location_address": artisan_profile.location_address,
            "service_radius_km": artisan_profile.service_radius_km,
            "hourly_rate_min": artisan_profile.hourly_rate_min,
            "hourly_rate_max": artisan_profile.hourly_rate_max,
            "years_of_experience": artisan_profile.years_of_experience,
            "specialization": artisan_profile.specialization,
            "is_verified": artisan_profile.is_verified,
            "verified_at": artisan_profile.verified_at,
            "verification_status": artisan_profile.verification_status,
            "availability_status": artisan_profile.availability_status,
            "average_rating": artisan_profile.average_rating,
            "total_ratings": artisan_profile.total_ratings,
            "total_jobs_completed": artisan_profile.total_jobs_completed,
            "response_time_avg_minutes": artisan_profile.response_time_avg_minutes,
            "acceptance_rate": artisan_profile.acceptance_rate,
            "created_at": current_user.created_at,
        }

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating artisan profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update artisan profile",
        )


@router.put("/me/profile-picture", response_model=ProfilePictureResponse)
async def update_profile_picture(
    profile_picture: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload or replace current user's profile picture.
    Available to all authenticated users.
    """
    try:
        previous_url = current_user.profile_picture_url
        image_url = await save_profile_picture(profile_picture, str(current_user.id))
        if not image_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload profile picture",
            )

        current_user.profile_picture_url = image_url
        db.commit()
        db.refresh(current_user)

        if previous_url and previous_url != image_url:
            await delete_image(previous_url)

        logger.info(f"Profile picture updated for user {current_user.id}")
        return {
            "message": "Profile picture updated successfully",
            "profile_picture_url": image_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating profile picture: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile picture",
        )


@router.patch("/artisans/me/availability", response_model=ArtisanProfileResponse)
def update_artisan_availability(
    availability_update: ArtisanAvailabilityUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Toggle artisan availability status.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    try:
        artisan_profile = (
            db.query(ArtisanProfile).filter(ArtisanProfile.user_id == current_user.id).first()
        )

        if not artisan_profile:
            artisan_profile = ArtisanProfile(user_id=current_user.id)
            db.add(artisan_profile)

        artisan_profile.availability_status = availability_update.availability_status

        db.commit()
        db.refresh(artisan_profile)

        logger.info(
            f"Artisan availability updated to {availability_update.availability_status} for user {current_user.id}"  # noqa: E501
        )

        # Return combined data
        response_data = {
            "id": str(current_user.id),
            "full_name": current_user.full_name,
            "email": current_user.email,
            "phone_number": current_user.phone_number,
            "profile_picture_url": current_user.profile_picture_url,
            "bio": current_user.bio,
            "user_type": current_user.user_type.value,
            "location_address": artisan_profile.location_address,
            "service_radius_km": artisan_profile.service_radius_km,
            "hourly_rate_min": artisan_profile.hourly_rate_min,
            "hourly_rate_max": artisan_profile.hourly_rate_max,
            "years_of_experience": artisan_profile.years_of_experience,
            "specialization": artisan_profile.specialization,
            "is_verified": artisan_profile.is_verified,
            "verified_at": artisan_profile.verified_at,
            "verification_status": artisan_profile.verification_status,
            "availability_status": artisan_profile.availability_status,
            "average_rating": artisan_profile.average_rating,
            "total_ratings": artisan_profile.total_ratings,
            "total_jobs_completed": artisan_profile.total_jobs_completed,
            "response_time_avg_minutes": artisan_profile.response_time_avg_minutes,
            "acceptance_rate": artisan_profile.acceptance_rate,
            "created_at": current_user.created_at,
        }

        return response_data

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating availability: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update availability",
        )


@router.get("/artisans/me/stats", response_model=ArtisanStatsResponse)
def get_my_artisan_stats(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get artisan statistics (ratings, jobs completed, etc.).
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    artisan_profile = (
        db.query(ArtisanProfile).filter(ArtisanProfile.user_id == current_user.id).first()
    )

    if not artisan_profile:
        # Return default stats
        return ArtisanStatsResponse(
            average_rating=0.0,
            total_ratings=0,
            total_jobs_completed=0,
            response_time_avg_minutes=None,
            acceptance_rate=0.0,
        )

    return artisan_profile


@router.get(
    "/artisans/me/services",
    response_model=List[ArtisanServiceSelectionResponse],
)
def get_my_artisan_services(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get selected services for current artisan.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can access this endpoint",
        )

    services = (
        db.query(Service)
        .join(UserService, UserService.service_id == Service.id)
        .filter(UserService.user_id == current_user.id)
        .order_by(Service.name)
        .all()
    )
    return services


@router.put(
    "/artisans/me/services",
    response_model=List[ArtisanServiceSelectionResponse],
)
def update_my_artisan_services(
    payload: ArtisanServiceSelectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Replace selected services for current artisan.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can access this endpoint",
        )

    try:
        requested_ids = list(dict.fromkeys(payload.service_ids))

        services = db.query(Service).filter(Service.id.in_(requested_ids)).all()
        found_ids = {service.id for service in services}
        missing_ids = [sid for sid in requested_ids if sid not in found_ids]
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid service IDs: {missing_ids}",
            )

        db.query(UserService).filter(UserService.user_id == current_user.id).delete()

        for service_id in requested_ids:
            db.add(UserService(user_id=current_user.id, service_id=service_id))

        db.commit()

        updated_services = (
            db.query(Service)
            .join(UserService, UserService.service_id == Service.id)
            .filter(UserService.user_id == current_user.id)
            .order_by(Service.name)
            .all()
        )

        logger.info(f"Updated artisan services for user {current_user.id}: {requested_ids}")
        return updated_services
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating artisan services: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update artisan services",
        )


@router.get("/artisans/{artisan_id}", response_model=ArtisanPublicProfileResponse)
def get_artisan_public_profile(artisan_id: str, db: Session = Depends(get_db)):
    """
    Get artisan public profile (what customers see).
    Available to all users.
    """
    try:
        # Get user
        user = db.query(User).filter(User.id == artisan_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artisan not found")

        if user.user_type != UserType.ARTISAN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User is not an artisan"
            )

        # Get artisan profile
        artisan_profile = db.query(ArtisanProfile).filter(ArtisanProfile.user_id == user.id).first()

        if not artisan_profile:
            # Create default if doesn't exist
            artisan_profile = ArtisanProfile(user_id=user.id)

        # Return public data only
        response_data = {
            "id": str(user.id),
            "full_name": user.full_name,
            "profile_picture_url": user.profile_picture_url,
            "bio": user.bio,
            "location_address": artisan_profile.location_address,
            "service_radius_km": artisan_profile.service_radius_km,
            "hourly_rate_min": artisan_profile.hourly_rate_min,
            "hourly_rate_max": artisan_profile.hourly_rate_max,
            "years_of_experience": artisan_profile.years_of_experience,
            "specialization": artisan_profile.specialization,
            "is_verified": artisan_profile.is_verified,
            "availability_status": artisan_profile.availability_status,
            "average_rating": artisan_profile.average_rating,
            "total_ratings": artisan_profile.total_ratings,
            "total_jobs_completed": artisan_profile.total_jobs_completed,
            "response_time_avg_minutes": artisan_profile.response_time_avg_minutes,
        }

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching artisan profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch artisan profile",
        )


# ==================== Portfolio Endpoints ====================


@router.get("/artisans/me/portfolio", response_model=List[PortfolioResponse])
def get_my_portfolio(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get current artisan's portfolio items.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    portfolio_items = (
        db.query(Portfolio)
        .filter(Portfolio.artisan_id == current_user.id)
        .order_by(Portfolio.display_order, Portfolio.created_at.desc())
        .all()
    )

    return portfolio_items


@router.post(
    "/artisans/me/portfolio", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED
)
async def add_portfolio_item(
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    display_order: int = Form(0),
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Add new portfolio item with image upload.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    try:
        # Upload image
        image_url = await save_portfolio_image(image, str(current_user.id))
        if not image_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload portfolio image",
            )

        # Create portfolio item
        portfolio_item = Portfolio(
            artisan_id=current_user.id,
            image_url=image_url,
            title=title,
            description=description,
            display_order=display_order,
        )

        db.add(portfolio_item)
        db.commit()
        db.refresh(portfolio_item)

        logger.info(f"Portfolio item added for artisan {current_user.id}")
        return portfolio_item

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding portfolio item: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add portfolio item"
        )


@router.put("/artisans/me/portfolio/{item_id}", response_model=PortfolioResponse)
def update_portfolio_item(
    item_id: int,
    portfolio_update: PortfolioUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update portfolio item (metadata only, not image).
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    try:
        portfolio_item = (
            db.query(Portfolio)
            .filter(Portfolio.id == item_id, Portfolio.artisan_id == current_user.id)
            .first()
        )

        if not portfolio_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio item not found"
            )

        # Update fields
        if portfolio_update.title is not None:
            portfolio_item.title = portfolio_update.title
        if portfolio_update.description is not None:
            portfolio_item.description = portfolio_update.description
        if portfolio_update.project_date is not None:
            portfolio_item.project_date = portfolio_update.project_date
        if portfolio_update.display_order is not None:
            portfolio_item.display_order = portfolio_update.display_order

        db.commit()
        db.refresh(portfolio_item)

        logger.info(f"Portfolio item {item_id} updated")
        return portfolio_item

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating portfolio item: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update portfolio item",
        )


@router.delete("/artisans/me/portfolio/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio_item(
    item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Delete portfolio item.
    Only available to artisans.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only artisans can access this endpoint"
        )

    try:
        portfolio_item = (
            db.query(Portfolio)
            .filter(Portfolio.id == item_id, Portfolio.artisan_id == current_user.id)
            .first()
        )

        if not portfolio_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio item not found"
            )

        # Delete image from storage
        await delete_image(portfolio_item.image_url)

        # Delete from database
        db.delete(portfolio_item)
        db.commit()

        logger.info(f"Portfolio item {item_id} deleted")
        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting portfolio item: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete portfolio item",
        )


@router.get("/artisans/{artisan_id}/portfolio", response_model=List[PortfolioResponse])
def get_artisan_portfolio(artisan_id: str, db: Session = Depends(get_db)):
    """
    Get artisan's portfolio (public view).
    Available to all users.
    """
    try:
        # Verify artisan exists
        user = db.query(User).filter(User.id == artisan_id).first()
        if not user or user.user_type != UserType.ARTISAN:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artisan not found")

        portfolio_items = (
            db.query(Portfolio)
            .filter(Portfolio.artisan_id == artisan_id)
            .order_by(Portfolio.display_order, Portfolio.created_at.desc())
            .all()
        )

        return portfolio_items

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching portfolio: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch portfolio"
        )
