"""Booking endpoints vs account deletion / deactivation.

A booking action read the row without a lock and wrote the status back, so an accept that ran
after the deletion committed could resurrect a CANCELLED booking. State-changing booking endpoints
now load the row FOR UPDATE and re-check, and refuse to act on a booking whose other party is
inactive.
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from geoalchemy2 import WKTElement

from app.api.v1.endpoints import bookings as bookings_endpoints
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import UserService
from app.db.models.user import User, UserType
from app.db.session import get_db
from app.main import app
from tests.admin.conftest import auth, make_booking, make_user
from tests.conftest import TestingSessionLocal
from tests.factories import make_service as fx_service

BASE = "/api/v1/bookings"


@pytest.fixture()
def service(db):
    s = fx_service(db)
    db.commit()
    return s


@pytest.fixture(autouse=True)
def silence_push(monkeypatch):
    monkeypatch.setattr(bookings_endpoints, "_notify_user", lambda *a, **k: None)


def pending_booking(db, service, **kw):
    customer = make_user(db, user_type=UserType.CLIENT)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    b = make_booking(
        db,
        service,
        customer,
        artisan,
        status=kw.pop("status", BookingStatus.PENDING),
        payment_status=kw.pop("payment_status", None),
        disputed=False,
    )
    return customer, artisan, b


# ----------------------------------------------------------------- the lock itself

ACTIONS = {
    # name: (acting party, method, path suffix, json body)
    "accept": ("artisan", "patch", "/accept", {"agreed_amount": 8000}),
    "reject": ("artisan", "patch", "/reject", {"rejection_reason": "busy that day"}),
    "negotiate": (
        "artisan",
        "patch",
        "/negotiate",
        {"negotiated_amount": 7000, "negotiation_condition": "after hours"},
    ),
    "cancel": ("client", "patch", "/cancel", {"cancellation_reason": "changed my mind"}),
}


@pytest.mark.parametrize("action", list(ACTIONS))
def test_booking_action_waits_for_a_concurrent_close_and_then_refuses(db, service, action):
    """Hold the booking row lock like an in-flight account deletion; the action must block on it
    instead of reading stale state, and after the close commits it must see the booking closed."""
    customer, artisan, b = pending_booking(db, service)
    actor_kind, method, suffix, payload = ACTIONS[action]
    actor = artisan if actor_kind == "artisan" else customer
    booking_id = b.id

    holder = TestingSessionLocal()  # the "deletion" transaction
    holder.query(Booking).filter(Booking.id == booking_id).with_for_update().one()

    def thread_session():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = thread_session
    from fastapi.testclient import TestClient

    result = {}

    def call():
        with TestClient(app) as c:
            result["resp"] = c.request(
                method.upper(), f"{BASE}/{booking_id}{suffix}", headers=auth(actor), json=payload
            )

    t = threading.Thread(target=call)
    t.start()
    try:
        time.sleep(1.0)
        assert t.is_alive(), "the action did not wait for the booking row lock"
        row = holder.query(Booking).filter(Booking.id == booking_id).one()
        row.status = BookingStatus.CANCELLED  # the deletion closes the pending booking
        row.cancellation_reason = "The customer deleted their account"
        holder.commit()
        t.join(timeout=15)
    finally:
        holder.close()
        app.dependency_overrides.pop(get_db, None)
    assert not t.is_alive()
    assert result["resp"].status_code == 400, result["resp"].text
    db.expire_all()
    assert db.get(Booking, booking_id).status == BookingStatus.CANCELLED  # not resurrected


def test_create_booking_waits_for_a_deleting_artisan_then_404s(db, service):
    customer = make_user(db, user_type=UserType.CLIENT)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    db.add(UserService(user_id=artisan.id, service_id=service.id))
    db.commit()
    artisan_id = artisan.id

    holder = TestingSessionLocal()
    holder.query(User).filter(User.id == artisan_id).with_for_update().one()  # deletion in flight

    def thread_session():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = thread_session
    from fastapi.testclient import TestClient

    body = {
        "artisan_id": str(artisan_id),
        "service_id": service.id,
        "job_description": "Fix sink",
        "job_date": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "job_latitude": 6.5,
        "job_longitude": 3.3,
        "job_address": "12 Example Street",
        "budget_min": 5000,
        "budget_max": 10000,
    }
    result = {}

    def call():
        with TestClient(app) as c:
            result["resp"] = c.post(BASE, headers=auth(customer), json=body)

    t = threading.Thread(target=call)
    t.start()
    try:
        time.sleep(1.0)
        assert t.is_alive(), "booking creation did not wait for the artisan row lock"
        u = holder.query(User).filter(User.id == artisan_id).one()
        u.is_active = False
        holder.commit()
        t.join(timeout=15)
    finally:
        holder.close()
        app.dependency_overrides.pop(get_db, None)
    assert result["resp"].status_code == 404, result["resp"].text
    db.expire_all()
    assert db.query(Booking).count() == 0


def _booking_body(artisan_id, service_id):
    return {
        "artisan_id": str(artisan_id),
        "service_id": service_id,
        "job_description": "Fix sink",
        "job_date": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "job_latitude": 6.5,
        "job_longitude": 3.3,
        "job_address": "12 Example Street",
        "budget_min": 5000,
        "budget_max": 10000,
    }


def test_create_booking_waits_for_a_deleting_customer_then_409s(db, service):
    """A customer mid-deletion holds their own user row; the booking must not be inserted after the
    account was anonymised (the deletion would never see it)."""
    customer = make_user(db, user_type=UserType.CLIENT)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    db.add(UserService(user_id=artisan.id, service_id=service.id))
    db.commit()
    customer_id, body = customer.id, _booking_body(artisan.id, service.id)

    holder = TestingSessionLocal()
    holder.query(User).filter(User.id == customer_id).with_for_update().one()  # deletion in flight

    def thread_session():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = thread_session
    from fastapi.testclient import TestClient

    result = {}

    def call():
        with TestClient(app) as c:
            result["resp"] = c.post(BASE, headers=auth(customer), json=body)

    t = threading.Thread(target=call)
    t.start()
    try:
        time.sleep(1.0)
        assert t.is_alive(), "booking creation did not wait for the customer row lock"
        u = holder.query(User).filter(User.id == customer_id).one()
        u.is_active = False  # the deletion commits
        holder.commit()
        t.join(timeout=15)
    finally:
        holder.close()
        app.dependency_overrides.pop(get_db, None)
    assert not t.is_alive()
    assert result["resp"].status_code == 409, result["resp"].text
    assert result["resp"].json()["detail"]["code"] == "account_unavailable"
    db.expire_all()
    assert db.query(Booking).count() == 0


def test_an_active_customer_can_still_create_a_booking(client, db, service):
    customer = make_user(db, user_type=UserType.CLIENT)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    db.add(UserService(user_id=artisan.id, service_id=service.id))
    db.commit()
    headers = auth(customer)
    ok = client.post(BASE, headers=headers, json=_booking_body(artisan.id, service.id))
    assert ok.status_code == 201, ok.text
    assert db.query(Booking).count() == 1


# ----------------------------------------------------- inactive / deleted counterparty


def deactivate(db, user):
    user.is_active = False
    db.commit()


@pytest.mark.parametrize(
    "who,path,method,payload,status_",
    [
        ("artisan", "/accept", "patch", {"agreed_amount": 8000}, BookingStatus.PENDING),
        (
            "artisan",
            "/negotiate",
            "patch",
            {"negotiated_amount": 7000, "negotiation_condition": "after hours"},
            BookingStatus.PENDING,
        ),
        ("artisan", "/start", "patch", {}, BookingStatus.PAID),
        ("artisan", "/complete", "patch", {"completion_notes": "done"}, BookingStatus.IN_PROGRESS),
    ],
)
def test_artisan_cannot_act_when_the_customer_is_inactive(
    client, db, service, who, path, method, payload, status_
):
    customer, artisan, b = pending_booking(db, service, status=status_)
    deactivate(db, customer)
    r = client.request(method.upper(), f"{BASE}/{b.id}{path}", headers=auth(artisan), json=payload)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "account_unavailable"
    db.expire_all()
    assert db.get(Booking, b.id).status == status_


def test_customer_cannot_respond_or_confirm_when_the_artisan_is_inactive(client, db, service):
    customer, artisan, b = pending_booking(db, service)
    b.negotiation_status = "pending_client"
    b.negotiated_amount = Decimal("7000")
    b.negotiation_last_offer_by = "artisan"
    db.commit()
    deactivate(db, artisan)
    r = client.patch(
        f"{BASE}/{b.id}/negotiate/respond", headers=auth(customer), json={"action": "agree"}
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "account_unavailable"

    customer2, artisan2, done = pending_booking(db, service, status=BookingStatus.COMPLETED)
    deactivate(db, artisan2)
    r = client.patch(f"{BASE}/{done.id}/confirm-completion", headers=auth(customer2))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "account_unavailable"


def test_exit_paths_still_work_with_an_inactive_counterparty(client, db, service):
    """cancel / reject must stay available so nobody is trapped behind a deleted party."""
    customer, artisan, b = pending_booking(db, service)
    deactivate(db, artisan)
    r = client.patch(
        f"{BASE}/{b.id}/cancel",
        headers=auth(customer),
        json={"cancellation_reason": "artisan is gone"},
    )
    assert r.status_code == 200, r.text


def test_customer_cannot_pay_a_deleted_artisan(client, db, service):
    customer, artisan, b = pending_booking(db, service, status=BookingStatus.ACCEPTED)
    deactivate(db, artisan)
    r = client.post(
        "/api/v1/payments/initialize", headers=auth(customer), json={"booking_id": b.id}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "account_unavailable"
    assert db.query(Payment).count() == 0


def test_active_parties_are_unaffected(client, db, service):
    customer, artisan, b = pending_booking(db, service)
    r = client.patch(f"{BASE}/{b.id}/accept", headers=auth(artisan), json={"agreed_amount": 8000})
    assert r.status_code == 200, r.text
    assert PaymentStatus  # keep import used
    assert WKTElement  # keep import used
