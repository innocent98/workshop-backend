from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import all models so they are registered with Base.metadata
# This is required for Alembic autogenerate to work
# Import at the end to avoid circular import
def import_models():
    from app.db.models import (  # noqa: F401
        User,
        OTP,
        Service,
        UserService,
        PasswordResetToken,
    )
