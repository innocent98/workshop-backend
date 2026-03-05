"""
Authentication endpoints.
Implements all 13 authentication endpoints from API documentation.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

from app.db.session import get_db
from app.services.auth import AuthService
from app.schemas.auth import (
    PersonalInfoRequest,
    PersonalInfoResponse,
    SetPasswordRequest,
    SetPasswordResponse,
    SendOTPRequest,
    SendOTPResponse,
    VerifyOTPRequest,
    VerifyOTPResponse,
    SelectServicesRequest,
    SelectServicesResponse,
    CompleteProfileResponse,
    UserResponse,
    LoginRequest,
    LoginResponse,
    GoogleSignInRequest,
    GoogleSignInResponse,
    ForgotPasswordSendCodeRequest,
    ForgotPasswordSendCodeResponse,
    ForgotPasswordVerifyCodeRequest,
    ForgotPasswordVerifyCodeResponse,
    ForgotPasswordResetRequest,
    ForgotPasswordResetResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ResendOTPRequest,
    ResendOTPResponse,
    LogoutResponse,
)
from app.core.logger import log
from app.api.deps import get_current_user
from app.core.token_blacklist import blacklist_token
from app.db.models.user import User
from app.core.config import settings


router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# REGISTRATION ENDPOINTS
# ============================================================================

@router.post(
    "/register/personal-info",
    response_model=PersonalInfoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Step 1: Submit Personal Information",
)
def register_personal_info(
    request: PersonalInfoRequest,
    db: Session = Depends(get_db),
):
    """
    Create user with personal information.
    This is the first step of the registration process.
    """
    user = AuthService.create_user_personal_info(
        db=db,
        full_name=request.full_name,
        email=request.email,
        phone_number=request.phone_number,
        user_type=request.user_type,
    )

    return PersonalInfoResponse(
        message="Personal information submitted successfully",
        user_id=str(user.id),
    )


@router.post(
    "/register/password",
    response_model=SetPasswordResponse,
    summary="Step 2: Set Password",
)
def register_set_password(
    request: SetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Set password for the user.
    This is the second step of the registration process.
    """
    AuthService.set_user_password(
        db=db,
        user_id=request.user_id,
        password=request.password,
    )

    return SetPasswordResponse(
        message="Password set successfully",
    )


@router.post(
    "/register/send-otp",
    response_model=SendOTPResponse,
    summary="Step 3a: Send OTP for Email Verification",
)
@limiter.limit("3/10minutes")
async def register_send_otp(
    body: SendOTPRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Send OTP code to user's email for verification.
    This is the third step of the registration process.
    """
    success = await AuthService.send_verification_otp(
        db=db,
        user_id=body.user_id,
        email=body.email,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP email"
        )

    return SendOTPResponse(
        message="OTP sent successfully to your email",
    )


@router.post(
    "/register/verify-otp",
    response_model=VerifyOTPResponse,
    summary="Step 3b: Verify OTP",
)
@limiter.limit("5/10minutes")
def register_verify_otp(
    body: VerifyOTPRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Verify the OTP code sent to user's email.
    This is the third step of the registration process.
    """
    AuthService.verify_otp(
        db=db,
        user_id=body.user_id,
        otp_code=body.otp_code,
    )

    return VerifyOTPResponse(
        message="Email verified successfully",
    )


@router.post(
    "/register/services",
    response_model=SelectServicesResponse,
    summary="Step 4: Select Services",
)
def register_select_services(
    request: SelectServicesRequest,
    db: Session = Depends(get_db),
):
    """
    Select services (artisan provides / client needs).
    This is the fourth step of the registration process.
    """
    AuthService.select_user_services(
        db=db,
        user_id=request.user_id,
        user_type=request.user_type,
        service_ids=request.services,
    )

    return SelectServicesResponse(
        message="Services selected successfully",
    )


@router.post(
    "/register/profile",
    response_model=CompleteProfileResponse,
    summary="Step 5: Upload Profile Picture & Bio",
)
async def register_complete_profile(
    user_id: str = Form(...),
    bio: Optional[str] = Form(None),
    profile_picture: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """
    Complete profile with optional bio and profile picture.
    This is the final step of the registration process.
    Marks registration as completed.
    """
    user = await AuthService.complete_user_profile(
        db=db,
        user_id=user_id,
        bio=bio,
        profile_picture=profile_picture,
    )

    return CompleteProfileResponse(
        message="Registration completed successfully",
        user=UserResponse.model_validate(user),
    )


# ============================================================================
# LOGIN ENDPOINTS
# ============================================================================

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Standard Login",
)
@limiter.limit("5/15minutes")
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Login with email and password.
    Returns access token and user information.
    """
    access_token, user = AuthService.login_user(
        db=db,
        email=body.email,
        password=body.password,
    )

    return LoginResponse(
        message="Login successful",
        token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/google",
    response_model=GoogleSignInResponse,
    summary="Google Sign-In",
)
def google_sign_in(
    request: GoogleSignInRequest,
    db: Session = Depends(get_db),
):
    """
    Sign in with Google OAuth.
    Creates new user if doesn't exist, otherwise logs in.
    """
    if not settings.FCM_SERVICE_ACCOUNT_FILE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase service account is not configured",
        )

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FCM_SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)

        claims = firebase_auth.verify_id_token(request.google_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token",
        )

    google_id = claims.get("uid")
    email = claims.get("email")
    full_name = claims.get("name") or (email.split("@")[0] if email else "Google User")
    picture = claims.get("picture")

    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google token is missing required user identity fields",
        )

    access_token, user, is_new_user = AuthService.google_sign_in(
        db=db,
        google_id=google_id,
        email=email,
        full_name=full_name,
        user_type=request.user_type,
        profile_picture_url=picture,
    )

    return GoogleSignInResponse(
        message="Google sign-in successful",
        token=access_token,
        is_new_user=is_new_user,
        user=UserResponse.model_validate(user),
    )


# ============================================================================
# PASSWORD RECOVERY ENDPOINTS
# ============================================================================

@router.post(
    "/forgot-password/send-code",
    response_model=ForgotPasswordSendCodeResponse,
    summary="Step 1: Request Password Reset Code",
)
@limiter.limit("3/10minutes")
async def forgot_password_send_code(
    body: ForgotPasswordSendCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Send password reset code to user's email.
    This is the first step of password recovery.
    """
    await AuthService.send_password_reset_code(
        db=db,
        email=body.email,
    )

    return ForgotPasswordSendCodeResponse(
        message="Password reset code sent to your email",
    )


@router.post(
    "/forgot-password/verify-code",
    response_model=ForgotPasswordVerifyCodeResponse,
    summary="Step 2: Verify Password Reset Code",
)
def forgot_password_verify_code(
    request: ForgotPasswordVerifyCodeRequest,
    db: Session = Depends(get_db),
):
    """
    Verify password reset code.
    Returns a reset token if code is valid.
    This is the second step of password recovery.
    """
    reset_token = AuthService.verify_password_reset_code(
        db=db,
        email=request.email,
        code=request.code,
    )

    return ForgotPasswordVerifyCodeResponse(
        message="Code verified successfully",
        reset_token=reset_token,
    )


@router.post(
    "/forgot-password/reset",
    response_model=ForgotPasswordResetResponse,
    summary="Step 3: Reset Password",
)
def forgot_password_reset(
    request: ForgotPasswordResetRequest,
    db: Session = Depends(get_db),
):
    """
    Reset password using the reset token.
    This is the final step of password recovery.
    """
    AuthService.reset_password(
        db=db,
        email=request.email,
        reset_token=request.reset_token,
        new_password=request.new_password,
    )

    return ForgotPasswordResetResponse(
        message="Password reset successfully",
    )


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="Change Password",
)
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change password for authenticated user.
    """
    AuthService.change_password(
        db=db,
        user=current_user,
        current_password=body.current_password,
        new_password=body.new_password,
    )

    return ChangePasswordResponse(
        message="Password changed successfully",
    )


# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.post(
    "/resend-otp",
    response_model=ResendOTPResponse,
    summary="Resend OTP",
)
@limiter.limit("3/10minutes")
async def resend_otp(
    body: ResendOTPRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Resend OTP for email verification or password reset.
    """
    await AuthService.resend_otp(
        db=db,
        email=body.email,
        otp_type=body.type,
    )

    return ResendOTPResponse(
        message="OTP sent successfully",
        retry_after=60,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
)
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Logout user by blacklisting their current token.
    The token will be invalid until it naturally expires.
    """
    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

        # Blacklist the token
        blacklist_token(token)

        log.info(f"User logged out: {current_user.email}")

    return LogoutResponse(message="Logged out successfully")
