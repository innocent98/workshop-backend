from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
import time
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logger import log
from app.api.v1.api import api_router


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        log.info(
            f"{request.method} {request.url.path} "
            f"completed in {process_time:.4f}s with status {response.status_code}"
        )

        return response


def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom rate limit error handler with user-friendly messages.
    Provides clear information about the rate limit and when to retry.
    """
    # Parse the rate limit details
    limit_detail = exc.detail  # e.g., "5 per 15 minute"

    # Extract endpoint-specific context
    path = request.url.path
    endpoint_name = "this endpoint"
    retry_message = "Please try again later."

    # Customize messages based on endpoint
    if "/login" in path:
        endpoint_name = "login"
        retry_message = "Please wait a few minutes before attempting to log in again."
    elif "/register" in path or "/send-otp" in path or "/verify-otp" in path:
        endpoint_name = "registration"
        retry_message = "Please wait before requesting another verification code."
    elif "/forgot-password" in path:
        endpoint_name = "password reset"
        retry_message = "Please wait before requesting another password reset code."
    elif "/resend-otp" in path:
        endpoint_name = "OTP resend"
        retry_message = "Please wait before requesting to resend the OTP."

    # Log the rate limit violation
    client_ip = get_remote_address(request)
    log.warning(
        f"Rate limit exceeded for {endpoint_name} from IP {client_ip}: {limit_detail}"
    )

    # Build response with detailed information
    response = JSONResponse(
        content={
            "error": "Rate limit exceeded",
            "message": f"Too many {endpoint_name} attempts. {retry_message}",
            "details": {
                "limit": limit_detail,
                "endpoint": path,
            }
        },
        status_code=429
    )

    # Inject rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, etc.)
    if hasattr(request.state, "view_rate_limit"):
        response = request.app.state.limiter._inject_headers(
            response, request.state.view_rate_limit
        )

    return response


# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# Add rate limiter state and custom error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware
app.add_middleware(LoggingMiddleware)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME} API",
        "version": settings.VERSION,
        "docs": f"{settings.API_V1_STR}/docs"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=True if settings.ENVIRONMENT == "development" else False
    )
