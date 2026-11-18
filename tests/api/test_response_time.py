"""Artisan response-time stat: the calculation (last-N window, rejections not counted) and the
accept-endpoint hook that keeps ``artisan_profiles.response_time_avg_minutes`` current."""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints import bookings as bookings_endpoints
from app.core.config import settings
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.user import UserType
from app.services.response_time import compute_response_time_avg_minutes
from tests.admin.conftest import auth, make_booking, make_user
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


def _booking(db, service, customer, artisan, *, status, requested_minutes_ago, accepted_after=None):
    """A booking requested ``requested_minutes_ago`` minutes ago; if ``accepted_after`` is given it
    was accepted that many minutes after the request."""
    b = make_booking(
        db, service, customer, artisan, status=status, payment_status=None, disputed=False
    )
    created = datetime.now(timezone.utc) - timedelta(minutes=requested_minutes_ago)
    b.created_at = created
    b.accepted_at = (
        created + timedelta(minutes=accepted_after) if accepted_after is not None else None
    )
    db.commit()
    return b


def _profile(db, artisan):
    db.expire_all()
    return db.query(ArtisanProfile).filter(ArtisanProfile.user_id == artisan.id).one()


def accept(client, artisan, booking):
    return client.patch(
        f"{BASE}/{booking.id}/accept", json={"agreed_amount": 8000}, headers=auth(artisan)
    )


def _people(db):
    return make_user(db, user_type=UserType.CLIENT), make_user(db, user_type=UserType.ARTISAN)


# ------------------------------------------------------------------ the calculation


def test_none_until_the_artisan_has_an_accepted_booking(db, service):
    customer, artisan = _people(db)
    assert compute_response_time_avg_minutes(db, artisan.id) is None
    _booking(db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=50)
    assert compute_response_time_avg_minutes(db, artisan.id) is None


def test_average_of_accepted_bookings(db, service):
    customer, artisan = _people(db)
    for gap in (10, 20, 30):
        _booking(
            db,
            service,
            customer,
            artisan,
            status=BookingStatus.COMPLETED,
            requested_minutes_ago=5000,
            accepted_after=gap,
        )
    assert compute_response_time_avg_minutes(db, artisan.id) == 20


def test_rejected_and_pending_requests_are_not_counted(db, service):
    customer, artisan = _people(db)
    _booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.ACCEPTED,
        requested_minutes_ago=500,
        accepted_after=12,
    )
    _booking(
        db, service, customer, artisan, status=BookingStatus.REJECTED, requested_minutes_ago=900
    )
    _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=2000
    )
    _booking(
        db, service, customer, artisan, status=BookingStatus.CANCELLED, requested_minutes_ago=3000
    )
    assert compute_response_time_avg_minutes(db, artisan.id) == 12


def test_only_the_last_n_accepted_bookings_count(db, service, monkeypatch):
    monkeypatch.setattr(settings, "RESPONSE_TIME_WINDOW", 3)
    customer, artisan = _people(db)
    # oldest first: two slow acceptances, then three fast ones
    for i, gap in enumerate((600, 600, 4, 6, 8)):
        _booking(
            db,
            service,
            customer,
            artisan,
            status=BookingStatus.COMPLETED,
            requested_minutes_ago=10000 - i * 1000,
            accepted_after=gap,
        )
    assert compute_response_time_avg_minutes(db, artisan.id) == 6


def test_other_artisans_do_not_leak_in(db, service):
    customer, artisan = _people(db)
    other = make_user(db, user_type=UserType.ARTISAN)
    _booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.ACCEPTED,
        requested_minutes_ago=300,
        accepted_after=10,
    )
    _booking(
        db,
        service,
        customer,
        other,
        status=BookingStatus.ACCEPTED,
        requested_minutes_ago=300,
        accepted_after=90,
    )
    assert compute_response_time_avg_minutes(db, artisan.id) == 10
    assert compute_response_time_avg_minutes(db, other.id) == 90


def test_instant_acceptance_never_reads_as_zero(db, service):
    customer, artisan = _people(db)
    _booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.ACCEPTED,
        requested_minutes_ago=5,
        accepted_after=0.1,
    )
    assert compute_response_time_avg_minutes(db, artisan.id) == 1


def test_accepted_before_created_counts_as_zero_gap_not_negative(db, service):
    customer, artisan = _people(db)
    _booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.ACCEPTED,
        requested_minutes_ago=5,
        accepted_after=-30,
    )
    assert compute_response_time_avg_minutes(db, artisan.id) == 1


# ------------------------------------------------------------------ the accept hook


def test_accept_records_the_stat(db, service, client):
    customer, artisan = _people(db)
    b = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=30
    )
    assert _profile(db, artisan).response_time_avg_minutes is None

    r = accept(client, artisan, b)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert 29 <= _profile(db, artisan).response_time_avg_minutes <= 31


def test_second_accept_updates_the_running_average(db, service, client):
    customer, artisan = _people(db)
    first = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=10
    )
    second = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=50
    )
    accept(client, artisan, first)
    accept(client, artisan, second)
    # (10 + 50) / 2 = 30
    assert 29 <= _profile(db, artisan).response_time_avg_minutes <= 31


def test_reject_does_not_touch_the_stat(db, service, client):
    customer, artisan = _people(db)
    b = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=45
    )
    r = client.patch(
        f"{BASE}/{b.id}/reject", json={"rejection_reason": "fully booked"}, headers=auth(artisan)
    )
    assert r.status_code == 200
    assert _profile(db, artisan).response_time_avg_minutes is None


def test_failed_accept_leaves_the_stat_alone(db, service, client):
    customer, artisan = _people(db)
    b = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=45
    )
    # amount outside the customer's budget range: 400, nothing recorded
    r = client.patch(f"{BASE}/{b.id}/accept", json={"agreed_amount": 999999}, headers=auth(artisan))
    assert r.status_code == 400
    assert _profile(db, artisan).response_time_avg_minutes is None
    assert db.get(Booking, b.id).accepted_at is None


def test_accept_without_a_profile_row_still_succeeds(db, service, client):
    customer, artisan = _people(db)
    db.query(ArtisanProfile).filter(ArtisanProfile.user_id == artisan.id).delete()
    db.commit()
    b = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=5
    )
    r = client.patch(f"{BASE}/{b.id}/accept", json={"agreed_amount": 8000}, headers=auth(artisan))
    assert r.status_code == 200


def test_value_is_exposed_unchanged_on_the_artisan_stats_endpoint(db, service, client):
    customer, artisan = _people(db)
    me = client.get("/api/v1/profiles/artisans/me/stats", headers=auth(artisan))
    assert me.status_code == 200
    assert me.json()["response_time_avg_minutes"] is None

    b = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=30
    )
    accept(client, artisan, b)
    stored = _profile(db, artisan).response_time_avg_minutes
    me = client.get("/api/v1/profiles/artisans/me/stats", headers=auth(artisan))
    assert me.json()["response_time_avg_minutes"] == stored


# --------------------------------------- the stat must never put the acceptance at risk


def test_accept_survives_the_stat_update_raising(db, service, client, monkeypatch):
    customer, artisan = _people(db)
    b = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=30
    )

    def boom(*a, **k):
        raise RuntimeError("stat exploded")

    monkeypatch.setattr(bookings_endpoints, "record_acceptance", boom)
    r = accept(client, artisan, b)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    db.expire_all()
    saved = db.get(Booking, b.id)
    assert saved.status == BookingStatus.ACCEPTED and saved.accepted_at is not None
    assert _profile(db, artisan).response_time_avg_minutes is None  # stat skipped, not wrong


def test_accept_survives_a_database_error_inside_the_stat_update(db, service, client, monkeypatch):
    """A real DB error aborts the transaction unless it is contained in the savepoint."""
    from sqlalchemy import text

    customer, artisan = _people(db)
    first = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=30
    )

    def db_error(session, booking):
        session.execute(text("SELECT 1/0"))

    monkeypatch.setattr(bookings_endpoints, "record_acceptance", db_error)
    r = accept(client, artisan, first)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Booking, first.id).status == BookingStatus.ACCEPTED
    assert _profile(db, artisan).response_time_avg_minutes is None

    # the next accept recomputes from the bookings table, so the stat self-heals
    monkeypatch.undo()
    monkeypatch.setattr(bookings_endpoints, "_notify_user", lambda *a, **k: None)
    second = _booking(
        db, service, customer, artisan, status=BookingStatus.PENDING, requested_minutes_ago=50
    )
    assert accept(client, artisan, second).status_code == 200
    # (30 + 50) / 2 = 40: the first booking, accepted while the stat failed, is included
    assert 39 <= _profile(db, artisan).response_time_avg_minutes <= 41
