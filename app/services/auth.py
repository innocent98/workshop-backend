"""
Authentication service layer.
Business logic for user registration, login, and password recovery.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, UploadFile

from app.db.models.user import User, UserType
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.otp import OTP, OTPType
from app.db.models.service import Service, UserService
from app.db.models.password_reset import PasswordResetToken
from app.core.security import get_password_hash, verify_password, create_access_token
from app.utils.otp import generate_otp, calculate_otp_expiry, is_otp_expired
from app.utils.email import send_otp_email, send_welcome_email
from app.utils.file_upload import save_profile_picture
from app.core.logger import log


def parse_uuid(user_id: str) -> UUID:
    """
    Safely parse a string to UUID.
    Raises HTTP 400 if invalid UUID format.
    """
    try:
        return UUID(user_id)
    except (ValueError, AttributeError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user ID format. Expected UUID, got: {user_id}"
        )


class AuthService:
    """Authentication service handling all auth operations"""

    @staticmethod
    def create_user_personal_info(
        db: Session,
        full_name: str,
        email: str,
        phone_number: str,
        user_type: str,
    ) -> User:
        """
        Step 1: Create user with personal information.
        Registration is not completed yet.
        """
        # Check if email already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        # Check if phone number already exists
        existing_phone = db.query(User).filter(User.phone_number == phone_number).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered"
            )

        # Create user (password not set yet, registration not completed)
        user = User(
            full_name=full_name,
            email=email.lower(),
            phone_number=phone_number,
            user_type=UserType(user_type),
            registration_completed=False,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        log.info(f"User created with personal info: {user.email} (ID: {user.id})")
        return user

    @staticmethod
    def set_user_password(
        db: Session,
        user_id: str,
        password: str,
    ) -> User:
        """
        Step 2: Set user password.
        """
        uuid_id = parse_uuid(user_id)
        user = db.query(User).filter(User.id == uuid_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Hash and store password
        user.hashed_password = get_password_hash(password)
        db.commit()
        db.refresh(user)

        log.info(f"Password set for user: {user.email}")
        return user

    @staticmethod
    async def send_verification_otp(
        db: Session,
        user_id: str,
        email: str,
    ) -> bool:
        """
        Step 3a: Send OTP for email verification.
        """
        uuid_id = parse_uuid(user_id)
        normalized_email = email.strip().lower()

        user = db.query(User).filter(User.id == uuid_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        if user.email.lower() != normalized_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match the registration record"
            )

        try:
            # Invalidate any existing unused OTPs for this user
            db.query(OTP).filter(
                OTP.user_id == uuid_id,
                OTP.otp_type == OTPType.PHONE_VERIFICATION,
                OTP.is_used.is_(False)
            ).update({"is_used": True})

            # Generate new OTP
            otp_code = generate_otp()
            expires_at = calculate_otp_expiry(minutes=10)

            otp = OTP(
                user_id=user.id,
                otp_code=otp_code,
                otp_type=OTPType.PHONE_VERIFICATION,
                expires_at=expires_at,
            )
            db.add(otp)
            db.flush()

            # Send OTP via email first; commit only if dispatch succeeds.
            success = await send_otp_email(user.email, otp_code, purpose="verification")
            if not success:
                db.rollback()
                log.error(f"Failed to send verification OTP email to {user.email}")
                return False

            db.commit()
            log.info(f"OTP sent to {user.email}: {otp_code}")
            return True
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            log.error(f"Unexpected error while sending verification OTP: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send verification OTP"
            )

    @staticmethod
    def verify_otp(
        db: Session,
        user_id: str,
        otp_code: str,
    ) -> User:
        """
        Step 3b: Verify OTP code.
        """
        uuid_id = parse_uuid(user_id)
        user = db.query(User).filter(User.id == uuid_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Find the OTP
        otp = db.query(OTP).filter(
            OTP.user_id == uuid_id,
            OTP.otp_code == otp_code,
            OTP.otp_type == OTPType.PHONE_VERIFICATION,
            OTP.is_used == False
        ).first()

        if not otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP code"
            )

        # Check if OTP is expired
        if is_otp_expired(otp.expires_at):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP has expired"
            )

        # Mark OTP as used
        otp.is_used = True

        # Mark email as verified
        user.is_email_verified = True

        # Temporary rule: once email is verified, auto-verify artisan profile.
        # This can be replaced later with stricter KYC/face-verification flow.
        if user.user_type == UserType.ARTISAN:
            artisan_profile = db.query(ArtisanProfile).filter(
                ArtisanProfile.user_id == user.id
            ).first()
            if not artisan_profile:
                artisan_profile = ArtisanProfile(user_id=user.id)
                db.add(artisan_profile)

            if not artisan_profile.is_verified:
                artisan_profile.is_verified = True
                artisan_profile.verified_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(user)

        log.info(f"OTP verified for user: {user.email}")
        return user

    @staticmethod
    def select_user_services(
        db: Session,
        user_id: str,
        user_type: str,
        service_ids: list[str],
    ) -> User:
        """
        Step 4: Select services.
        """
        uuid_id = parse_uuid(user_id)
        user = db.query(User).filter(User.id == uuid_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Verify user type matches
        if user.user_type.value != user_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User type mismatch"
            )

        # Delete existing user services
        db.query(UserService).filter(UserService.user_id == uuid_id).delete()

        # Add new services
        for service_name in service_ids:
            service = db.query(Service).filter(Service.name == service_name).first()
            if service:
                user_service = UserService(
                    user_id=user.id,
                    service_id=service.id
                )
                db.add(user_service)

        db.commit()
        db.refresh(user)

        log.info(f"Services selected for user {user.email}: {service_ids}")
        return user

    @staticmethod
    async def complete_user_profile(
        db: Session,
        user_id: str,
        bio: Optional[str],
        profile_picture: Optional[UploadFile],
    ) -> User:
        """
        Step 5: Complete profile with bio and picture.
        Marks registration as completed.
        """
        uuid_id = parse_uuid(user_id)
        user = db.query(User).filter(User.id == uuid_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Update bio if provided
        if bio:
            user.bio = bio

        # Upload profile picture if provided
        if profile_picture:
            image_url = await save_profile_picture(profile_picture, str(user.id))
            if image_url:
                user.profile_picture_url = image_url

        # Mark registration as completed
        user.registration_completed = True

        db.commit()
        db.refresh(user)

        # Send welcome email
        await send_welcome_email(user.email, user.full_name)

        log.info(f"Registration completed for user: {user.email}")
        return user

    @staticmethod
    def login_user(
        db: Session,
        email: str,
        password: str,
    ) -> Tuple[str, User]:
        """
        Standard login with email and password.
        Returns access token and user object.
        """
        user = db.query(User).filter(User.email == email.lower()).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Verify password
        if not user.hashed_password or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive"
            )

        # Check if email is verified
        if not user.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email address not verified. Please verify your email to continue."
            )

        # Check if registration is completed
        if not user.registration_completed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please complete your registration"
            )

        # Generate access token
        access_token = create_access_token(data={"sub": str(user.id)})

        log.info(f"User logged in: {user.email}")
        return access_token, user

    @staticmethod
    def google_sign_in(
        db: Session,
        google_id: str,
        email: str,
        full_name: str,
        user_type: str,
        profile_picture_url: Optional[str] = None,
    ) -> Tuple[str, User, bool]:
        """
        Google OAuth sign-in.
        Creates user if doesn't exist, otherwise logs in.
        Returns access token, user object, and is_new_user flag.
        """
        # Check if user exists with this Google ID
        user = db.query(User).filter(User.google_id == google_id).first()
        is_new_user = False

        if not user:
            # Check if email exists (user might have registered manually)
            user = db.query(User).filter(User.email == email.lower()).first()

            if user:
                # Link Google account to existing user
                user.google_id = google_id
                if profile_picture_url and not user.profile_picture_url:
                    user.profile_picture_url = profile_picture_url
            else:
                # Create new user via Google
                user = User(
                    full_name=full_name,
                    email=email.lower(),
                    phone_number="",  # Will be updated later if needed
                    user_type=UserType(user_type),
                    google_id=google_id,
                    profile_picture_url=profile_picture_url,
                    is_email_verified=True,  # Google verified
                    registration_completed=False,  # Still need to complete profile
                )
                db.add(user)
                is_new_user = True

            db.commit()
            db.refresh(user)

        # Generate access token
        access_token = create_access_token(data={"sub": str(user.id)})

        log.info(f"Google sign-in for user: {user.email} (new: {is_new_user})")
        return access_token, user, is_new_user

    @staticmethod
    async def send_password_reset_code(
        db: Session,
        email: str,
    ) -> bool:
        """
        Step 1 of password recovery: Send reset code.
        """
        user = db.query(User).filter(User.email == email.lower()).first()
        if not user:
            # Don't reveal if email exists or not (security best practice)
            log.warning(f"Password reset requested for non-existent email: {email}")
            return True

        # Invalidate any existing unused OTPs
        db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.otp_type == OTPType.PASSWORD_RESET,
            OTP.is_used == False
        ).update({"is_used": True})

        # Generate new OTP
        otp_code = generate_otp()
        expires_at = calculate_otp_expiry(minutes=10)

        otp = OTP(
            user_id=user.id,
            otp_code=otp_code,
            otp_type=OTPType.PASSWORD_RESET,
            expires_at=expires_at,
        )

        db.add(otp)
        db.commit()

        # Send OTP via email
        success = await send_otp_email(email, otp_code, purpose="password_reset")

        log.info(f"Password reset OTP sent to {email}")
        return success

    @staticmethod
    def verify_password_reset_code(
        db: Session,
        email: str,
        code: str,
    ) -> str:
        """
        Step 2 of password recovery: Verify reset code.
        Returns reset token if valid.
        """
        user = db.query(User).filter(User.email == email.lower()).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Find the OTP
        otp = db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.otp_code == code,
            OTP.otp_type == OTPType.PASSWORD_RESET,
            OTP.is_used == False
        ).first()

        if not otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset code"
            )

        # Check if OTP is expired
        if is_otp_expired(otp.expires_at):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset code has expired"
            )

        # Mark OTP as used
        otp.is_used = True

        # Generate reset token
        reset_token = PasswordResetToken.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        token_obj = PasswordResetToken(
            user_id=user.id,
            reset_token=reset_token,
            expires_at=expires_at,
        )

        db.add(token_obj)
        db.commit()

        log.info(f"Password reset code verified for user: {user.email}")
        return reset_token

    @staticmethod
    def reset_password(
        db: Session,
        email: str,
        reset_token: str,
        new_password: str,
    ) -> User:
        """
        Step 3 of password recovery: Reset password.
        """
        user = db.query(User).filter(User.email == email.lower()).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Find the reset token
        token_obj = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.reset_token == reset_token,
            PasswordResetToken.is_used == False
        ).first()

        if not token_obj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset token"
            )

        # Check if token is expired
        if datetime.now(timezone.utc) > token_obj.expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset token has expired"
            )

        # Mark token as used
        token_obj.is_used = True

        # Update password
        user.hashed_password = get_password_hash(new_password)

        db.commit()
        db.refresh(user)

        log.info(f"Password reset for user: {user.email}")
        return user

    @staticmethod
    def change_password(
        db: Session,
        user: User,
        current_password: str,
        new_password: str,
    ) -> User:
        """
        Change password for an authenticated user.
        """
        if not user.hashed_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password change is not available for this account"
            )

        if not verify_password(current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )

        if verify_password(new_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password"
            )

        user.hashed_password = get_password_hash(new_password)
        db.commit()
        db.refresh(user)

        log.info(f"Password changed for user: {user.email}")
        return user

    @staticmethod
    async def resend_otp(
        db: Session,
        email: str,
        otp_type: str,
    ) -> bool:
        """
        Resend OTP for verification or password reset.
        """
        user = db.query(User).filter(User.email == email.lower()).first()
        if not user:
            # Don't reveal if email exists or not
            log.warning(f"OTP resend requested for non-existent email: {email}")
            return True

        # Map string type to enum
        if otp_type == "phone_verification":
            otp_type_enum = OTPType.PHONE_VERIFICATION
            purpose = "verification"
        elif otp_type == "password_reset":
            otp_type_enum = OTPType.PASSWORD_RESET
            purpose = "password_reset"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP type"
            )

        # Invalidate any existing unused OTPs
        db.query(OTP).filter(
            OTP.user_id == user.id,
            OTP.otp_type == otp_type_enum,
            OTP.is_used == False
        ).update({"is_used": True})

        # Generate new OTP
        otp_code = generate_otp()
        expires_at = calculate_otp_expiry(minutes=10)

        otp = OTP(
            user_id=user.id,
            otp_code=otp_code,
            otp_type=otp_type_enum,
            expires_at=expires_at,
        )

        db.add(otp)
        db.commit()

        # Send OTP via email
        success = await send_otp_email(email, otp_code, purpose=purpose)

        log.info(f"OTP resent to {email} (type: {otp_type})")
        return success
