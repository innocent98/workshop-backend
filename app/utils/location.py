"""
Location and geography utility functions using PostGIS.
"""
from typing import Tuple, List, Optional
import httpx
from geoalchemy2 import Geometry
from geoalchemy2.functions import ST_DWithin, ST_Distance, ST_MakePoint, ST_SetSRID
from sqlalchemy import cast, Float
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.logger import logger


def create_point(latitude: float, longitude: float) -> str:
    """
    Create a PostGIS POINT from latitude and longitude.

    Args:
        latitude: Latitude coordinate (-90 to 90)
        longitude: Longitude coordinate (-180 to 180)

    Returns:
        WKT (Well-Known Text) representation of the point

    Example:
        >>> create_point(6.5244, 3.3792)  # Lagos coordinates
        'POINT(3.3792 6.5244)'
    """
    # Note: PostGIS uses (longitude, latitude) order, not (lat, lng)
    return f"POINT({longitude} {latitude})"


def calculate_distance_km(
    point1_lat: float,
    point1_lng: float,
    point2_lat: float,
    point2_lng: float
) -> float:
    """
    Calculate distance between two points in kilometers using Haversine formula.
    This is a pure Python implementation for quick calculations without database queries.

    Args:
        point1_lat: First point latitude
        point1_lng: First point longitude
        point2_lat: Second point latitude
        point2_lng: Second point longitude

    Returns:
        Distance in kilometers
    """
    from math import radians, sin, cos, sqrt, atan2

    # Earth's radius in kilometers
    R = 6371.0

    lat1 = radians(point1_lat)
    lng1 = radians(point1_lng)
    lat2 = radians(point2_lat)
    lng2 = radians(point2_lng)

    dlat = lat2 - lat1
    dlng = lng2 - lng1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlng / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return distance


def distance_query(
    point_column,
    latitude: float,
    longitude: float,
    srid: int = 4326
):
    """
    Create a SQLAlchemy query expression for calculating distance to a point.
    Uses PostGIS ST_Distance function.

    Args:
        point_column: SQLAlchemy Geography column
        latitude: Target latitude
        longitude: Target longitude
        srid: Spatial Reference System Identifier (default: 4326 for WGS84)

    Returns:
        SQLAlchemy expression for distance in meters

    Example:
        >>> from app.db.models.artisan import ArtisanProfile
        >>> distance = distance_query(
        ...     ArtisanProfile.location,
        ...     6.5244,
        ...     3.3792
        ... )
        >>> query = db.query(ArtisanProfile, distance.label('distance'))
    """
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), srid)
    return func.ST_Distance(
        cast(point_column, Geometry),
        cast(point, Geometry),
        True  # Use spheroid for accurate distance
    )


def within_radius_filter(
    point_column,
    latitude: float,
    longitude: float,
    radius_km: float,
    srid: int = 4326
):
    """
    Create a SQLAlchemy filter for finding points within a radius.
    Uses PostGIS ST_DWithin function for efficient spatial indexing.

    Args:
        point_column: SQLAlchemy Geography column
        latitude: Center point latitude
        longitude: Center point longitude
        radius_km: Radius in kilometers
        srid: Spatial Reference System Identifier (default: 4326 for WGS84)

    Returns:
        SQLAlchemy filter expression

    Example:
        >>> from app.db.models.artisan import ArtisanProfile
        >>> nearby = within_radius_filter(
        ...     ArtisanProfile.location,
        ...     6.5244,
        ...     3.3792,
        ...     10.0  # 10km radius
        ... )
        >>> artisans = db.query(ArtisanProfile).filter(nearby).all()
    """
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), srid)
    radius_meters = radius_km * 1000  # Convert km to meters

    return func.ST_DWithin(
        cast(point_column, Geometry),
        cast(point, Geometry),
        radius_meters,
        True  # Use spheroid
    )


def parse_coordinates(location_string: str) -> Optional[Tuple[float, float]]:
    """
    Parse latitude and longitude from a coordinate string.

    Args:
        location_string: String in format "lat,lng" or "lat, lng"

    Returns:
        Tuple of (latitude, longitude) or None if parsing fails

    Example:
        >>> parse_coordinates("6.5244, 3.3792")
        (6.5244, 3.3792)
    """
    try:
        parts = location_string.replace(" ", "").split(",")
        if len(parts) != 2:
            return None

        lat = float(parts[0])
        lng = float(parts[1])

        # Validate ranges
        if not (-90 <= lat <= 90):
            return None
        if not (-180 <= lng <= 180):
            return None

        return (lat, lng)
    except (ValueError, AttributeError):
        return None


def validate_coordinates(latitude: float, longitude: float) -> bool:
    """
    Validate latitude and longitude values.

    Args:
        latitude: Latitude value
        longitude: Longitude value

    Returns:
        True if valid, False otherwise
    """
    try:
        lat = float(latitude)
        lng = float(longitude)
        return (-90 <= lat <= 90) and (-180 <= lng <= 180)
    except (ValueError, TypeError):
        return False


# Nigerian major cities coordinates (for reference)
NIGERIAN_CITIES = {
    "lagos": {"lat": 6.5244, "lng": 3.3792, "name": "Lagos"},
    "abuja": {"lat": 9.0765, "lng": 7.3986, "name": "Abuja"},
    "kano": {"lat": 12.0022, "lng": 8.5920, "name": "Kano"},
    "ibadan": {"lat": 7.3775, "lng": 3.9470, "name": "Ibadan"},
    "port_harcourt": {"lat": 4.8156, "lng": 7.0498, "name": "Port Harcourt"},
    "benin_city": {"lat": 6.3350, "lng": 5.6037, "name": "Benin City"},
    "kaduna": {"lat": 10.5105, "lng": 7.4165, "name": "Kaduna"},
    "jos": {"lat": 9.9285, "lng": 8.8921, "name": "Jos"},
    "ilorin": {"lat": 8.4966, "lng": 4.5426, "name": "Ilorin"},
    "enugu": {"lat": 6.4403, "lng": 7.4970, "name": "Enugu"},
}


def get_city_coordinates(city_name: str) -> Optional[Tuple[float, float]]:
    """
    Get coordinates for a Nigerian city.

    Args:
        city_name: City name (case-insensitive)

    Returns:
        Tuple of (latitude, longitude) or None if city not found

    Example:
        >>> get_city_coordinates("lagos")
        (6.5244, 3.3792)
    """
    city = NIGERIAN_CITIES.get(city_name.lower().replace(" ", "_"))
    if city:
        return (city["lat"], city["lng"])
    return None


def resolve_location_label(latitude: float, longitude: float) -> Optional[str]:
    """
    Best-effort reverse geocoding for area/state-style labels.

    Returns a compact human-friendly label such as:
    - "Ikeja, Lagos"
    - "Lagos, Lagos State"
    - "Lagos State, Nigeria"
    """
    if not settings.REVERSE_GEOCODE_ENABLED:
        return None

    url = f"{settings.NOMINATIM_BASE_URL.rstrip('/')}/reverse"
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "jsonv2",
        "addressdetails": 1,
        "zoom": 10,  # Prefer city/LGA/state level, not street-level detail
    }
    headers = {
        "User-Agent": settings.NOMINATIM_USER_AGENT,
        "Accept": "application/json",
    }

    try:
        with httpx.Client(timeout=4.0, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        address = payload.get("address") or {}
        area = (
            address.get("suburb")
            or address.get("city_district")
            or address.get("town")
            or address.get("city")
            or address.get("county")
        )
        state = address.get("state")
        country = address.get("country")

        if area and state:
            return f"{area}, {state}"
        if area:
            return area
        if state and country:
            return f"{state}, {country}"
        if state:
            return state
        if country:
            return country

        display_name = payload.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            # Keep only broader area by trimming after first two comma-separated parts.
            parts = [p.strip() for p in display_name.split(",") if p.strip()]
            return ", ".join(parts[:2]) if parts else None
    except Exception as exc:
        logger.warning(f"Reverse geocoding failed for {latitude},{longitude}: {exc}")

    return None
