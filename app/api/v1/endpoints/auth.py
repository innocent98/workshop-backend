"""
Authentication endpoints.
Implements all 13 authentication endpoints from API documentation.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

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
    ResendOTPRequest,
    ResendOTPResponse,
)
from app.core.logger import log


router = APIRouter()


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
async def register_send_otp(
    request: SendOTPRequest,
    db: Session = Depends(get_db),
):
    """
    Send OTP code to user's email for verification.
    This is the third step of the registration process.
    """
    success = await AuthService.send_verification_otp(
        db=db,
        user_id=request.user_id,
        email=request.email,
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
def register_verify_otp(
    request: VerifyOTPRequest,
    db: Session = Depends(get_db),
):
    """
    Verify the OTP code sent to user's email.
    This is the third step of the registration process.
    """
    AuthService.verify_otp(
        db=db,
        user_id=request.user_id,
        otp_code=request.otp_code,
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
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Login with email and password.
    Returns access token and user information.
    """
    access_token, user = AuthService.login_user(
        db=db,
        email=request.email,
        password=request.password,
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
    # TODO: Verify Google token and extract user info
    # For now, this is a placeholder. In production:
    # 1. Verify google_token with Google API
    # 2. Extract user info (google_id, email, name, picture)
    # 3. Call AuthService.google_sign_in with extracted info

    # Placeholder implementation
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google Sign-In will be implemented with Google OAuth integration"
    )


# ============================================================================
# PASSWORD RECOVERY ENDPOINTS
# ============================================================================

@router.post(
    "/forgot-password/send-code",
    response_model=ForgotPasswordSendCodeResponse,
    summary="Step 1: Request Password Reset Code",
)
async def forgot_password_send_code(
    request: ForgotPasswordSendCodeRequest,
    db: Session = Depends(get_db),
):
    """
    Send password reset code to user's email.
    This is the first step of password recovery.
    """
    await AuthService.send_password_reset_code(
        db=db,
        email=request.email,
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


# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.post(
    "/resend-otp",
    response_model=ResendOTPResponse,
    summary="Resend OTP",
)
async def resend_otp(
    request: ResendOTPRequest,
    db: Session = Depends(get_db),
):
    """
    Resend OTP for email verification or password reset.
    """
    await AuthService.resend_otp(
        db=db,
        email=request.email,
        otp_type=request.type,
    )

    return ResendOTPResponse(
        message="OTP sent successfully",
        retry_after=60,
    )
