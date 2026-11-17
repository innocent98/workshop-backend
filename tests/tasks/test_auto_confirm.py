from datetime import datetime, timedelta, timezone

from app.db.models.booking import BookingStatus
from app.db.models.booking_progress_log import BookingProgressLog
from app.db.models.user import UserType
from app.tasks.booking_tasks import AUTO_CONFIRM_LOG_NOTE, auto_confirm_due_bookings
from tests.factories import make_booking, make_service, make_user


def _world(db):
    return (
        make_user(db, UserType.ARTISAN),
        make_user(db, UserType.CLIENT),
        make_service(db),
    )


def test_confirms_only_overdue_undisputed_unconfirmed_completed_bookings(db, notifications):
    artisan, customer, service = _world(db)
    C = BookingStatus.COMPLETED
    due = make_booking(db, artisan, customer, service, status=C, deadline_hours=-2)
    not_due = make_booking(db, artisan, customer, service, status=C, deadline_hours=3)
    no_deadline = make_booking(db, artisan, customer, service, status=C)
    confirmed = make_booking(
        db, artisan, customer, service, status=C, deadline_hours=-2, confirmed=True
    )
    disputed_flag = make_booking(
        db, artisan, customer, service, status=C, deadline_hours=-2, disputed=True
    )
    disputed_status = make_booking(
        db, artisan, customer, service, status=BookingStatus.DISPUTED, deadline_hours=-2
    )
    paid = make_booking(
        db, artisan, customer, service, status=BookingStatus.PAID, deadline_hours=-2
    )
    db.commit()

    assert auto_confirm_due_bookings(db) == 1

    for b in (due, not_due, no_deadline, confirmed, disputed_flag, disputed_status, paid):
        db.refresh(b)
    assert due.completion_confirmed_by_client_at is not None
    assert not_due.completion_confirmed_by_client_at is None
    assert no_deadline.completion_confirmed_by_client_at is None
    assert disputed_flag.completion_confirmed_by_client_at is None
    assert disputed_status.completion_confirmed_by_client_at is None
    assert paid.completion_confirmed_by_client_at is None
    assert due.status == C  # status is unchanged: only the confirmation is recorded

    logs = db.query(BookingProgressLog).all()
    assert len(logs) == 1
    assert logs[0].booking_id == due.id and logs[0].description == AUTO_CONFIRM_LOG_NOTE

    recipients = {n["user_id"] for n in notifications}
    assert recipients == {str(artisan.id), str(customer.id)}
    assert {n["data"]["event"] for n in notifications} == {"completion_auto_confirmed"}


def test_is_idempotent(db, notifications):
    artisan, customer, service = _world(db)
    make_booking(db, artisan, customer, service, status=BookingStatus.COMPLETED, deadline_hours=-2)
    db.commit()

    assert auto_confirm_due_bookings(db) == 1
    assert auto_confirm_due_bookings(db) == 0
    assert db.query(BookingProgressLog).count() == 1
    assert len(notifications) == 2  # one per party, once


def test_respects_explicit_now(db):
    artisan, customer, service = _world(db)
    make_booking(
        db, artisan, customer, service, status=BookingStatus.COMPLETED, deadline_hours=5
    )
    db.commit()
    assert auto_confirm_due_bookings(db) == 0
    assert auto_confirm_due_bookings(db, now=datetime.now(timezone.utc) + timedelta(hours=6)) == 1
