"""
Fixtures for admin / verification tests. They need a real Postgres+PostGIS database
(the models use Geography columns), taken from DATABASE_URL. Tables are truncated
between tests, so the database name must contain "test" as a safety guard.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import admin as admin_endpoints  # noqa: F401
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.base import Base, import_models
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import Service
from app.db.models.user import User, UserType
from app.db.session import get_db
from app.main import app
from app.services import admin as admin_service

_counter = itertools.count(1)


@pytest.fixture(scope="session")
def pg_engine():
    url = settings.DATABASE_URL
    db_name = url.rsplit("/", 1)[-1].split("?")[0]
    if "test" not in db_name:
        pytest.fail(f"Refusing to run destructive admin tests on database '{db_name}'")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    import_models()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(pg_engine):
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    session = sessionmaker(bind=pg_engine, autoflush=False)()
    yield session
    session.close()


@pytest.fixture()
def notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(
        admin_service,
        "notify_user",
        lambda user_id, title, body, data=None: sent.append((str(user_id), title, data)),
    )
    return sent


@pytest.fixture()
def client(db, notifications):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, user_type=UserType.CLIENT, is_admin=False, **kw):
    n = next(_counter)
    user = User(
        full_name=kw.pop("full_name", f"Test User {n}"),
        email=kw.pop("email", f"user{n}@example.test"),
        phone_number=kw.pop("phone_number", f"+23480000{n:05d}"),
        user_type=user_type,
        hashed_password=get_password_hash("placeholder-pw"),
        is_admin=is_admin,
        is_active=True,
        is_email_verified=kw.pop("is_email_verified", True),
        registration_completed=True,
        **kw,
    )
    db.add(user)
    db.commit()
    if user_type == UserType.ARTISAN:
        db.add(ArtisanProfile(user_id=user.id))
        db.commit()
    return user


def auth(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


@pytest.fixture()
def admin(db):
    return make_user(db, is_admin=True, full_name="Admin One")


@pytest.fixture()
def admin_h(admin):
    return auth(admin)


@pytest.fixture()
def service(db):
    s = Service(name=f"Plumbing {uuid.uuid4().hex[:6]}")
    db.add(s)
    db.commit()
    return s


def make_booking(
    db,
    service,
    customer,
    artisan,
    status=BookingStatus.DISPUTED,
    payment_status=PaymentStatus.SUCCESS,
    disputed=True,
):
    n = next(_counter)
    now = datetime.now(timezone.utc)
    booking = Booking(
        booking_reference=f"BKG-T{n:05d}",
        customer_id=customer.id,
        artisan_id=artisan.id,
        service_id=service.id,
        job_description="Fix the sink",
        job_date=now + timedelta(days=1),
        job_location=WKTElement("POINT(3.3792 6.5244)", srid=4326),
        job_address="1 Test Street, Lagos",
        budget_min=Decimal("5000"),
        budget_max=Decimal("10000"),
        agreed_amount=Decimal("8000"),
        status=status,
        completion_disputed_at=now - timedelta(hours=2) if disputed else None,
        completion_dispute_reason="Work not done" if disputed else None,
    )
    db.add(booking)
    db.flush()
    if payment_status is not None:
        db.add(
            Payment(
                payment_reference=f"PAY-T{n:05d}",
                paystack_reference=f"ps_ref_{n}",
                booking_id=booking.id,
                amount=Decimal("8000"),
                platform_fee=Decimal("800"),
                artisan_amount=Decimal("7200"),
                status=payment_status,
                customer_email=customer.email,
                customer_name=customer.full_name,
            )
        )
    db.commit()
    return booking


__all__ = ["make_user", "make_booking", "auth"]
