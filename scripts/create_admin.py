#!/usr/bin/env python
"""
Create the first admin from FIRST_SUPERUSER_EMAIL / FIRST_SUPERUSER_PASSWORD.

Idempotent and safe to run on every deploy:
  * no user with that email -> creates an admin (user_type=client, is_admin, email-verified)
  * user exists and is already an admin -> re-activates it if needed; the password is set ONLY if
    the account has none (never overwrites a rotated password; --reset-password overwrites)
  * user exists but is NOT an admin -> REFUSES (exit code 2). A pre-registered account with that
    email
    must not silently inherit admin rights. After checking the account really is yours, re-run with
    --promote-existing (this also sets the password from the env and marks the email verified).
The password is never printed or logged.

Run (inside the api container, or anywhere with the app env loaded):
    python scripts/create_admin.py
    python scripts/create_admin.py --reset-password
    python scripts/create_admin.py --promote-existing
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.base import import_models  # noqa: E402
from app.db.models.user import User, UserType  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

ADMIN_PHONE = "+2340000000000"


def ensure_admin(
    db,
    email: str,
    password: str,
    reset_password: bool = False,
    promote_existing: bool = False,
) -> str:
    """Returns 'created' | 'updated' | 'refused'."""
    email = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        user = User(
            full_name="Workchop Admin",
            email=email,
            phone_number=ADMIN_PHONE,
            user_type=UserType.CLIENT,
            hashed_password=get_password_hash(password),
            is_admin=True,
            is_active=True,
            is_email_verified=True,
            registration_completed=True,
        )
        db.add(user)
        db.commit()
        return "created"

    if not user.is_admin:
        if not promote_existing:
            return "refused"
        # Promoting a pre-existing account: take it over fully so a previous owner of the
        # email/password cannot keep access.
        user.is_admin = True
        user.is_email_verified = True
        user.hashed_password = get_password_hash(password)
    user.is_active = True
    if reset_password or not user.hashed_password:
        user.hashed_password = get_password_hash(password)
    db.commit()
    return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument("--promote-existing", action="store_true")
    args = parser.parse_args()

    import_models()
    db = SessionLocal()
    try:
        result = ensure_admin(
            db,
            str(settings.FIRST_SUPERUSER_EMAIL),
            settings.FIRST_SUPERUSER_PASSWORD,
            args.reset_password,
            args.promote_existing,
        )
    finally:
        db.close()
    if result == "refused":
        print(
            f"REFUSED: {settings.FIRST_SUPERUSER_EMAIL} already exists and is not an admin. "
            "Verify the account is yours, then re-run with --promote-existing.",
            file=sys.stderr,
        )
        return 2
    print(f"admin {result}: {settings.FIRST_SUPERUSER_EMAIL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
