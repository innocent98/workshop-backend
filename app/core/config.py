from typing import List, Optional, Any, Dict
from pydantic import AnyHttpUrl, field_validator, EmailStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Project Info
    PROJECT_NAME: str = "workchop-api"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str

    # Server
    SERVER_HOST: str
    SERVER_PORT: int = 8000

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "https://0b7fd6f1a85b.ngrok-free.app"
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Database
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str

    # Email (optional)
    SMTP_TLS: bool = True
    SMTP_PORT: int = 587
    SMTP_HOST: Optional[str] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: Optional[EmailStr] = None
    EMAILS_FROM_NAME: Optional[str] = None

    # Cloudinary (for file uploads)
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    CLOUDINARY_FOLDER: str = "workchop"  # Default folder in Cloudinary

    # File Upload Settings
    MAX_UPLOAD_SIZE_MB: int = 5
    ALLOWED_IMAGE_EXTENSIONS: List[str] = ["jpg", "jpeg", "png", "gif", "webp"]
    USE_CLOUDINARY: bool = True  # Toggle between local and cloud storage

    # Paystack Payment Gateway
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None
    PAYSTACK_WEBHOOK_SECRET: Optional[str] = None
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"

    # Reverse Geocoding
    REVERSE_GEOCODE_ENABLED: bool = True
    NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org"
    NOMINATIM_USER_AGENT: str = "workchop-api/1.0"

    # Booking completion confirmation / payout hold window
    COMPLETION_DISPUTE_WINDOW_HOURS: int = 24

    # Push notifications (Firebase Cloud Messaging)
    FCM_ENABLED: bool = True
    FCM_SERVICE_ACCOUNT_FILE: Optional[str] = "/app/app/service_account/workchop-b3069-firebase-adminsdk-fbsvc-75e0bff73a.json"

    # Admin
    FIRST_SUPERUSER_EMAIL: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings()
