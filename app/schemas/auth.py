"""
Authentication schemas for request and response validation.
Based on authentication API documentation.
"""
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime


# ============================================================================
# REGISTRATION SCHEMAS
# ============================================================================

class PersonalInfoRequest(BaseModel):
    """Step 1: Submit Personal Information"""
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone_number: str = Field(..., min_length=10, max_length=20)
    user_type: str = Field(..., pattern="^(artisan|client)$")

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if '@' not in v:
            raise ValueError('Email must contain @')
        return v.lower()


class PersonalInfoResponse(BaseModel):
    success: bool = True
    message: str
    user_id: str


class SetPasswordRequest(BaseModel):
    """Step 2: Set Password"""
    user_id: str
    password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Passwords must match')
        return v


class SetPasswordResponse(BaseModel):
    success: bool = True
    message: str


class SendOTPRequest(BaseModel):
    """Step 3: Send OTP for Email Verification"""
    user_id: str
    email: EmailStr


class SendOTPResponse(BaseModel):
    success: bool = True
    message: str


class VerifyOTPRequest(BaseModel):
    """Step 3: Verify OTP"""
    user_id: str
    otp_code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


class VerifyOTPResponse(BaseModel):
    success: bool = True
    message: str


class SelectServicesRequest(BaseModel):
    """Step 4: Select Services"""
    user_id: str
    user_type: str = Field(..., pattern="^(artisan|client)$")
    services: List[str] = Field(..., min_length=1)

    @field_validator('services')
    @classmethod
    def validate_services(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError('At least one service must be selected')
        return v


class SelectServicesResponse(BaseModel):
    success: bool = True
    message: str


class CompleteProfileRequest(BaseModel):
    """Step 5: Upload Profile Picture & Bio (multipart/form-data)"""
    user_id: str
    bio: Optional[str] = None


class UserResponse(BaseModel):
    """User data response"""
    id: str
    full_name: str
    email: str
    phone_number: str
    user_type: str
    profile_picture_url: Optional[str] = None
    bio: Optional[str] = None

    @field_validator('id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string if needed"""
        if hasattr(v, 'hex'):  # Check if it's a UUID object
            return str(v)
        return v

    class Config:
        from_attributes = True


class CompleteProfileResponse(BaseModel):
    success: bool = True
    message: str
    user: UserResponse


# ============================================================================
# LOGIN SCHEMAS
# ============================================================================

class LoginRequest(BaseModel):
    """Standard Login"""
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    success: bool = True
    message: str
    token: str
    user: UserResponse


class GoogleSignInRequest(BaseModel):
    """Google Sign-In"""
    google_token: str
    user_type: Optional[str] = Field(None, pattern="^(artisan|client)$")


class GoogleSignInResponse(BaseModel):
    success: bool = True
    message: str
    token: str
    is_new_user: bool
    user: UserResponse


# ============================================================================
# PASSWORD RECOVERY SCHEMAS
# ============================================================================

class ForgotPasswordSendCodeRequest(BaseModel):
    """Step 1: Request Reset Code"""
    email: EmailStr


class ForgotPasswordSendCodeResponse(BaseModel):
    success: bool = True
    message: str


class ForgotPasswordVerifyCodeRequest(BaseModel):
    """Step 2: Verify Reset Code"""
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


class ForgotPasswordVerifyCodeResponse(BaseModel):
    success: bool = True
    message: str
    reset_token: str


class ForgotPasswordResetRequest(BaseModel):
    """Step 3: Reset Password"""
    email: EmailStr
    reset_token: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Passwords must match')
        return v


class ForgotPasswordResetResponse(BaseModel):
    success: bool = True
    message: str


# ============================================================================
# AUTHENTICATED PASSWORD CHANGE SCHEMAS
# ============================================================================

class ChangePasswordRequest(BaseModel):
    """Change password for authenticated user"""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Passwords must match')
        return v


class ChangePasswordResponse(BaseModel):
    success: bool = True
    message: str


# ============================================================================
# RESEND OTP SCHEMA
# ============================================================================

class ResendOTPRequest(BaseModel):
    """Resend OTP"""
    email: EmailStr
    type: str = Field(..., pattern="^(phone_verification|password_reset)$")


class ResendOTPResponse(BaseModel):
    success: bool = True
    message: str
    retry_after: int = 60


# ============================================================================
# LOGOUT SCHEMA
# ============================================================================

class LogoutResponse(BaseModel):
    """Logout response"""
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Logged out successfully"
            }
        }


# ============================================================================
# ERROR RESPONSE SCHEMA
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    message: str
    detail: Optional[str] = None


class UpdateMyServicesRequest(BaseModel):
    """Update current authenticated user's selected services."""
    services: List[str] = Field(..., min_length=1)

    @field_validator('services')
    @classmethod
    def validate_services(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError('At least one service must be selected')
        return v


class MyServicesResponse(BaseModel):
    """Current authenticated user's selected services."""
    services: List[str]
