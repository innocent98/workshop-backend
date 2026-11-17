"""
Test fixtures.

Tests run against a real PostgreSQL + PostGIS database (the models use PostGIS
``Geography`` columns and the money paths rely on ``SELECT ... FOR UPDATE``), so SQLite
cannot be used. Point ``DATABASE_URL`` at a database whose name contains ``test``;
CI provides a ``postgis/postgis`` service, locally use a scratch container.
"""

import os

# Settings are required at import time of ``app``; give CI/local runs sane defaults.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SERVER_HOST", "http://localhost")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test_user:test_password@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("FIRST_SUPERUSER_EMAIL", "admin@test.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "testpassword")
os.environ.setdefault("FCM_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import Base, import_models  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

import_models()

_db_name = make_url(settings.DATABASE_URL).database or ""
if "test" not in _db_name:
    # Tests TRUNCATE every table: never run them against a real database.
    pytest.exit(f"Refusing to run tests against database '{_db_name}' (name must contain 'test')")

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean_tables(_schema):
    yield
    names = ", ".join(
        f'"{t.name}"' for t in Base.metadata.sorted_tables if t.name != "spatial_ref_sys"
    )
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """Capture push notifications instead of talking to Celery/Redis."""
    sent = []

    def fake_delay(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.services.notify.send_push_notification.delay", fake_delay)
    return sent


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


from app.services.paystack import PaystackError  # noqa: E402


class FakePaystack:
    """Stand-in for the Paystack transfer API (set ``transfer_error`` / ``transfer_status``)."""

    def __init__(self):
        self.verify_calls = []
        self.recipient_calls = []
        self.transfer_calls = []
        self.verify_error = None
        self.recipient_error = None
        self.transfer_error = None
        self.transfer_status = "pending"
        self.transfer_verify = {}  # reference -> verify payload (or an Exception to raise)
        self.transfer_verify_calls = []

    def verify_account_number(self, account_number, bank_code):
        self.verify_calls.append((account_number, bank_code))
        if self.verify_error:
            raise self.verify_error
        return {"account_name": "JANE ARTISAN", "account_number": account_number}

    def create_transfer_recipient(self, name, account_number, bank_code):
        self.recipient_calls.append((name, account_number, bank_code))
        if self.recipient_error:
            raise self.recipient_error
        return {"recipient_code": "RCP_test123"}

    def verify_transfer(self, reference):
        self.transfer_verify_calls.append(reference)
        result = self.transfer_verify.get(reference, PaystackError("Transfer not found", 404))
        if isinstance(result, Exception):
            raise result
        return {"reference": reference, "currency": "NGN", **result}

    def initiate_transfer(self, recipient_code, amount, reason, reference):
        self.transfer_calls.append(
            {"recipient_code": recipient_code, "amount": amount, "reference": reference}
        )
        if self.transfer_error:
            raise self.transfer_error
        return {
            "transfer_code": f"TRF_{len(self.transfer_calls)}",
            "reference": reference,
            "status": self.transfer_status,
            "amount": int(amount * 100),
        }


@pytest.fixture
def paystack(monkeypatch):
    from app.services.paystack import PaystackService

    fake = FakePaystack()
    monkeypatch.setattr(
        PaystackService, "verify_account_number", staticmethod(fake.verify_account_number)
    )
    monkeypatch.setattr(
        PaystackService, "create_transfer_recipient", staticmethod(fake.create_transfer_recipient)
    )
    monkeypatch.setattr(PaystackService, "initiate_transfer", staticmethod(fake.initiate_transfer))
    monkeypatch.setattr(PaystackService, "verify_transfer", staticmethod(fake.verify_transfer))
    return fake
