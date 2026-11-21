"""
Search endpoints for artisan and service discovery
"""

import math
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from geoalchemy2.elements import WKTElement
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.artisan_profile import ArtisanProfile, AvailabilityStatus
from app.db.models.portfolio import Portfolio
from app.db.models.service import Service, UserService
from app.db.models.service_category import ServiceCategory
from app.db.models.user import User
from app.schemas.search import (
    ArtisanSearchResponse,
    ArtisanSearchResult,
    NearbyArtisanSummary,
    ServiceAvailability,
)
from app.utils.location import create_point

router = APIRouter()


@router.get("/artisans", response_model=ArtisanSearchResponse)
def search_artisans(
    latitude: float = Query(..., ge=-90, le=90, description="Search latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Search longitude"),
    radius_km: float = Query(10.0, ge=0.1, le=100, description="Search radius in kilometers"),
    category_id: Optional[int] = Query(None, description="Filter by service category"),
    service_ids: Optional[str] = Query(None, description="Comma-separated service IDs"),
    min_hourly_rate: Optional[Decimal] = Query(None, ge=0, description="Minimum hourly rate"),
    max_hourly_rate: Optional[Decimal] = Query(None, ge=0, description="Maximum hourly rate"),
    min_rating: Optional[float] = Query(None, ge=0, le=5, description="Minimum average rating"),
    verified_only: bool = Query(False, description="Show only verified artisans"),
    availability_status: Optional[str] = Query(None, description="Filter by availability status"),
    min_years_experience: Optional[int] = Query(
        None, ge=0, description="Minimum years of experience"
    ),
    sort_by: str = Query(
        "distance",
        description="Sort by: distance, rating, price, experience, jobs_completed, response_time",
    ),
    sort_order: str = Query("asc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    Search for artisans based on location and various filters.

    Uses PostGIS for efficient proximity searches and returns results
    with calculated distances from the search location.
    """
    # Create search point
    search_point = create_point(latitude, longitude)
    search_point_geog = WKTElement(search_point, srid=4326)

    # Convert radius from km to meters for PostGIS
    radius_meters = radius_km * 1000

    # Base query with location filter
    query = (
        db.query(
            ArtisanProfile,
            User,
            # Calculate distance in meters and convert to km
            (func.ST_Distance(ArtisanProfile.location, search_point_geog) / 1000).label(
                "distance_km"
            ),
        )
        .join(User, ArtisanProfile.user_id == User.id)
        .filter(
            User.is_active == True,
            ArtisanProfile.location.isnot(None),
            # Use ST_DWithin for efficient spatial filtering
            func.ST_DWithin(ArtisanProfile.location, search_point_geog, radius_meters),
        )
    )

    # Apply filters
    filters_applied = {"radius_km": radius_km, "verified_only": verified_only}

    if category_id:
        # Filter by category through UserService join
        query = (
            query.join(UserService, UserService.user_id == User.id)
            .join(Service, UserService.service_id == Service.id)
            .filter(Service.category_id == category_id)
        )
        filters_applied["category_id"] = category_id

    if service_ids:
        # Parse comma-separated service IDs
        service_id_list = [int(sid.strip()) for sid in service_ids.split(",")]
        query = (
            query.join(UserService, UserService.user_id == User.id)
            .join(Service, UserService.service_id == Service.id)
            .filter(Service.id.in_(service_id_list))
        )
        filters_applied["service_ids"] = service_id_list

    if min_hourly_rate is not None:
        query = query.filter(
            or_(
                ArtisanProfile.hourly_rate_min >= min_hourly_rate,
                ArtisanProfile.hourly_rate_max >= min_hourly_rate,
            )
        )
        filters_applied["min_hourly_rate"] = float(min_hourly_rate)

    if max_hourly_rate is not None:
        query = query.filter(
            or_(
                ArtisanProfile.hourly_rate_min <= max_hourly_rate,
                ArtisanProfile.hourly_rate_max <= max_hourly_rate,
            )
        )
        filters_applied["max_hourly_rate"] = float(max_hourly_rate)

    if min_rating is not None:
        query = query.filter(ArtisanProfile.average_rating >= min_rating)
        filters_applied["min_rating"] = min_rating

    if verified_only:
        query = query.filter(ArtisanProfile.is_verified == True)

    if availability_status:
        query = query.filter(ArtisanProfile.availability_status == availability_status)
        filters_applied["availability_status"] = availability_status

    if min_years_experience is not None:
        query = query.filter(ArtisanProfile.years_of_experience >= min_years_experience)
        filters_applied["min_years_experience"] = min_years_experience

    # Remove duplicates if we joined with services
    # We need to do this before ordering to avoid DISTINCT ON conflicts
    if category_id or service_ids:
        # If we filtered by services, we need to deduplicate
        # Use a subquery approach to maintain proper ordering
        from sqlalchemy import select

        # Get unique artisan profile IDs that match filters
        subq = query.with_entities(ArtisanProfile.id).distinct().subquery()

        # Re-query with full data for those IDs
        query = (
            db.query(
                ArtisanProfile,
                User,
                (func.ST_Distance(ArtisanProfile.location, search_point_geog) / 1000).label(
                    "distance_km"
                ),
            )
            .join(User, ArtisanProfile.user_id == User.id)
            .filter(ArtisanProfile.id.in_(select(subq.c.id)))
        )

    # Apply sorting
    sort_column = None
    if sort_by == "distance":
        sort_column = "distance_km"
    elif sort_by == "rating":
        sort_column = ArtisanProfile.average_rating
    elif sort_by == "price":
        # Sort by minimum hourly rate
        sort_column = ArtisanProfile.hourly_rate_min
    elif sort_by == "experience":
        sort_column = ArtisanProfile.years_of_experience
    elif sort_by == "jobs_completed":
        sort_column = ArtisanProfile.total_jobs_completed
    elif sort_by == "response_time":
        sort_column = ArtisanProfile.response_time_avg_minutes
    else:
        sort_column = "distance_km"

    if sort_column == "distance_km":
        if sort_order == "desc":
            query = query.order_by(
                func.ST_Distance(ArtisanProfile.location, search_point_geog).desc()
            )
        else:
            query = query.order_by(func.ST_Distance(ArtisanProfile.location, search_point_geog))
    else:
        ordering = sort_column.desc() if sort_order == "desc" else sort_column
        if sort_by == "response_time":
            # Artisans with no accepted booking yet have no figure: never rank them above real ones.
            ordering = ordering.nulls_last()
        query = query.order_by(ordering)

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    # Build response
    artisan_results = []
    for artisan_profile, user, distance_km in results:
        # Get services offered by this artisan
        services = (
            db.query(Service.name)
            .join(UserService, UserService.service_id == Service.id)
            .filter(UserService.user_id == user.id)
            .all()
        )
        service_names = [s.name for s in services]

        categories = (
            db.query(ServiceCategory.name)
            .join(Service, Service.category_id == ServiceCategory.id)
            .join(UserService, UserService.service_id == Service.id)
            .filter(UserService.user_id == user.id)
            .order_by(ServiceCategory.display_order, ServiceCategory.name)
            .all()
        )
        category_name = categories[0].name if categories else None

        # Get a portfolio sample
        portfolio_sample = (
            db.query(Portfolio.image_url)
            .filter(Portfolio.artisan_id == user.id)
            .order_by(Portfolio.display_order)
            .first()
        )

        artisan_results.append(
            ArtisanSearchResult(
                id=str(user.id),
                full_name=user.full_name,
                profile_picture=user.profile_picture_url,
                location_address=artisan_profile.location_address,
                service_radius_km=artisan_profile.service_radius_km,
                hourly_rate_min=artisan_profile.hourly_rate_min,
                hourly_rate_max=artisan_profile.hourly_rate_max,
                years_of_experience=artisan_profile.years_of_experience,
                specialization=artisan_profile.specialization,
                is_verified=artisan_profile.is_verified,
                availability_status=artisan_profile.availability_status.value,
                average_rating=artisan_profile.average_rating,
                total_ratings=artisan_profile.total_ratings,
                total_jobs_completed=artisan_profile.total_jobs_completed,
                response_time_avg_minutes=artisan_profile.response_time_avg_minutes,
                acceptance_rate=artisan_profile.acceptance_rate,
                distance_km=round(distance_km, 2),
                services=service_names,
                category_name=category_name,
                portfolio_sample=portfolio_sample.image_url if portfolio_sample else None,
            )
        )

    total_pages = math.ceil(total / page_size)

    return ArtisanSearchResponse(
        results=artisan_results,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        search_location={"latitude": latitude, "longitude": longitude},
        filters_applied=filters_applied,
    )


@router.get("/services/availability", response_model=List[ServiceAvailability])
def get_service_availability(
    latitude: float = Query(..., ge=-90, le=90, description="Search latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Search longitude"),
    radius_km: float = Query(10.0, ge=0.1, le=100, description="Search radius in kilometers"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
):
    """
    Get service availability in a specific location.

    Returns aggregated statistics about available services and artisans
    in the specified area.
    """
    # Create search point
    search_point = create_point(latitude, longitude)
    search_point_geog = WKTElement(search_point, srid=4326)
    radius_meters = radius_km * 1000

    # Query for service availability
    query = (
        db.query(
            Service.id.label("service_id"),
            Service.name.label("service_name"),
            ServiceCategory.id.label("category_id"),
            ServiceCategory.name.label("category_name"),
            func.count(func.distinct(ArtisanProfile.id)).label("artisans_available"),
            func.avg(ArtisanProfile.hourly_rate_min).label("average_hourly_rate"),
            func.avg(ArtisanProfile.average_rating).label("average_rating"),
            func.min(func.ST_Distance(ArtisanProfile.location, search_point_geog) / 1000).label(
                "closest_distance_km"
            ),
        )
        .join(UserService, UserService.service_id == Service.id)
        .join(User, UserService.user_id == User.id)
        .join(ArtisanProfile, ArtisanProfile.user_id == User.id)
        .join(ServiceCategory, Service.category_id == ServiceCategory.id)
        .filter(
            User.is_active == True,
            ArtisanProfile.location.isnot(None),
            ArtisanProfile.availability_status == AvailabilityStatus.AVAILABLE,
            func.ST_DWithin(ArtisanProfile.location, search_point_geog, radius_meters),
        )
    )

    if category_id:
        query = query.filter(ServiceCategory.id == category_id)

    query = query.group_by(
        Service.id, Service.name, ServiceCategory.id, ServiceCategory.name
    ).order_by(ServiceCategory.name, Service.name)

    results = query.all()

    availability_list = []
    for result in results:
        availability_list.append(
            ServiceAvailability(
                service_id=result.service_id,
                service_name=result.service_name,
                category_id=result.category_id,
                category_name=result.category_name,
                artisans_available=result.artisans_available,
                average_hourly_rate=(
                    round(result.average_hourly_rate, 2) if result.average_hourly_rate else None
                ),
                average_rating=round(result.average_rating, 1) if result.average_rating else None,
                closest_artisan_distance_km=(
                    round(result.closest_distance_km, 2) if result.closest_distance_km else None
                ),
            )
        )

    return availability_list


@router.get("/artisans/nearby/summary", response_model=NearbyArtisanSummary)
def get_nearby_artisans_summary(
    latitude: float = Query(..., ge=-90, le=90, description="Search latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Search longitude"),
    radius_km: float = Query(10.0, ge=0.1, le=100, description="Search radius in kilometers"),
    db: Session = Depends(get_db),
):
    """
    Get summary statistics of nearby artisans.

    Provides an overview of artisans available in the specified area.
    """
    # Create search point
    search_point = create_point(latitude, longitude)
    search_point_geog = WKTElement(search_point, srid=4326)
    radius_meters = radius_km * 1000

    # Get summary statistics
    summary = (
        db.query(
            func.count(func.distinct(ArtisanProfile.id)).label("total_artisans"),
            func.count(
                func.distinct(case((ArtisanProfile.is_verified == True, ArtisanProfile.id)))
            ).label("total_verified"),
            func.count(
                func.distinct(
                    case(
                        (
                            ArtisanProfile.availability_status == AvailabilityStatus.AVAILABLE,
                            ArtisanProfile.id,
                        )
                    )
                )
            ).label("total_available"),
            func.avg(ArtisanProfile.average_rating).label("average_rating"),
            func.min(func.ST_Distance(ArtisanProfile.location, search_point_geog) / 1000).label(
                "min_distance"
            ),
            func.max(func.ST_Distance(ArtisanProfile.location, search_point_geog) / 1000).label(
                "max_distance"
            ),
        )
        .join(User, ArtisanProfile.user_id == User.id)
        .filter(
            User.is_active == True,
            ArtisanProfile.location.isnot(None),
            func.ST_DWithin(ArtisanProfile.location, search_point_geog, radius_meters),
        )
        .first()
    )

    # Get count of unique services offered
    services_count = (
        db.query(func.count(func.distinct(Service.id)))
        .join(UserService, UserService.service_id == Service.id)
        .join(User, UserService.user_id == User.id)
        .join(ArtisanProfile, ArtisanProfile.user_id == User.id)
        .filter(
            User.is_active == True,
            ArtisanProfile.location.isnot(None),
            func.ST_DWithin(ArtisanProfile.location, search_point_geog, radius_meters),
        )
        .scalar()
    )

    return NearbyArtisanSummary(
        total_artisans=summary.total_artisans or 0,
        total_verified=summary.total_verified or 0,
        total_available=summary.total_available or 0,
        services_offered=services_count or 0,
        average_rating=round(summary.average_rating, 1) if summary.average_rating else 0.0,
        distance_range_km={
            "min": round(summary.min_distance, 2) if summary.min_distance else 0.0,
            "max": round(summary.max_distance, 2) if summary.max_distance else 0.0,
        },
    )
