from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    bookings,
    health,
    notifications,
    payments,
    profiles,
    reviews,
    search,
    services,
    wallet,
)

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(services.router, prefix="/services", tags=["services"])
api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(wallet.router, prefix="/wallet", tags=["wallet"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
