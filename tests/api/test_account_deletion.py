"""DELETE /auth/me: in-app account deletion (App Store / Play requirement).

Soft-delete + anonymise: financial rows stay (accounting) but point at an anonymised user.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints import auth as auth_endpoints
from app.core.rate_limit import limiter
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.models.admin import AdminAuditLog
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.otp import OTP
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.portfolio import Portfolio
from app.db.models.push_device import PushDevice
from app.db.models.user import User, UserType
from app.db.models.user_notification import UserNotification
from app.db.models.withdrawal import Withdrawal, WithdrawalStatus
from tests.admin.conftest import auth, make_booking, make_user
from tests.factories import make_booking as fx_booking
from tests.factories import make_payment as fx_payment
from tests.factories import make_service as fx_service
from tests.factories import make_withdrawable

URL = "/api/v1/auth/me"
PW = "Correct-horse-1"


@pytest.fixture()
def service(db):
    s = fx_service(db)
    db.commit()
    return s


@pytest.fixture(autouse=True)
def no_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture()
def deleted_images(monkeypatch):
    urls = []

    async def fake_delete(url):
        urls.append(url)
        return True

    monkeypatch.setattr(auth_endpoints, "delete_image", fake_delete)
    return urls


@pytest.fixture()
def blacklisted(monkeypatch):
    tokens = []
    monkeypatch.setattr(auth_endpoints, "blacklist_token", lambda t, *a, **k: tokens.append(t))
    return tokens


def user_with_pw(db, user_type=UserType.CLIENT, **kw):
    u = make_user(db, user_type=user_type, **kw)
    u.hashed_password = get_password_hash(PW)
    db.commit()
    return u


def delete(client, user, body=None, token=None):
    headers = auth(user) if token is None else {"Authorization": f"Bearer {token}"}
    return client.request("DELETE", URL, headers=headers, json=body if body is not None else {})


def blockers(r):
    return {b["code"]: b for b in r.json()["detail"]["blockers"]}


# ----------------------------------------------------------------- authorisation


def test_requires_authentication(client):
    assert client.request("DELETE", URL, json={"password": PW}).status_code in (401, 403)


def test_password_account_needs_the_current_password(client, db):
    u = user_with_pw(db)
    r = delete(client, u, {})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "password_required"
    r = delete(client, u, {"password": "wrong-password"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invalid_password"
    db.expire_all()
    assert db.get(User, u.id).is_active is True  # untouched


def test_admin_accounts_cannot_self_delete(client, db):
    u = user_with_pw(db, is_admin=True)
    r = delete(client, u, {"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "admin_account"


# ------------------------------------------------------------- happy path + anonymise


def test_delete_client_anonymises_but_keeps_financial_rows(
    client, db, service, blacklisted, deleted_images, notifications
):
    customer = user_with_pw(
        db,
        full_name="Ada Customer",
        email="ada@example.com",
        phone_number="+2348011112222",
        bio="hello",
        profile_picture_url="https://res.cloudinary.com/x/me.jpg",
        location_address="12 Real Street",
        location_latitude=6.5,
        location_longitude=3.3,
        google_id="g-123",
    )
    artisan = make_user(db, user_type=UserType.ARTISAN)
    done = make_booking(
        db, service, customer, artisan, status=BookingStatus.COMPLETED, disputed=False
    )
    pay = db.query(Payment).one()
    pay.customer_name, pay.customer_email = "Ada Customer", "ada@example.com"
    db.add_all(
        [
            PushDevice(user_id=customer.id, fcm_token="tok-1", platform="android", is_active=True),
            UserNotification(user_id=customer.id, title="t", body="b"),
            OTP(
                user_id=customer.id,
                otp_code="123456",
                otp_type="phone_verification",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ),
        ]
    )
    db.commit()
    token = create_access_token({"sub": str(customer.id)})

    r = delete(client, customer, {"password": PW}, token=token)
    assert r.status_code == 200, r.text
    assert r.json() == {"success": True, "message": "Your account has been deleted."}

    db.expire_all()
    u = db.get(User, customer.id)
    assert u.is_active is False and u.deleted_at is not None
    assert u.full_name == "Deleted User"
    for original in ("ada@example.com", "+2348011112222", "Ada", "12 Real"):
        assert original not in " ".join(
            str(v) for v in (u.full_name, u.email, u.phone_number, u.bio, u.location_address) if v
        )
    assert u.email.endswith("@deleted.invalid") and u.phone_number.startswith("del_")
    assert len(u.phone_number) <= 20
    assert u.hashed_password is None and u.google_id is None
    assert u.bio is None and u.profile_picture_url is None
    assert (u.location_address, u.location_latitude, u.location_longitude) == (None, None, None)
    assert u.is_email_verified is False

    # tokens revoked, devices/notifications/OTPs gone
    assert blacklisted == [token]
    assert db.query(PushDevice).filter_by(user_id=customer.id).count() == 0
    assert db.query(UserNotification).filter_by(user_id=customer.id).count() == 0
    assert db.query(OTP).filter_by(user_id=customer.id).count() == 0
    assert deleted_images == ["https://res.cloudinary.com/x/me.jpg"]

    # financial rows remain, linked to the anonymised user, with the PII scrubbed
    b = db.get(Booking, done.id)
    assert b.customer_id == customer.id and b.agreed_amount == Decimal("8000")
    p = db.query(Payment).one()
    assert p.amount == Decimal("8000") and p.paystack_reference
    assert p.customer_name == "Deleted User" and p.customer_email == u.email

    audit = db.query(AdminAuditLog).filter_by(action="user.self_delete").one()
    assert audit.admin_id == customer.id and audit.target_id == str(customer.id)
    assert "ada" not in str(audit.details).lower()


def test_deleted_user_can_no_longer_use_any_token_or_log_in(client, db):
    u = user_with_pw(db, email="ada2@example.com")
    other_device_token = create_access_token(  # a different token, never blacklisted
        {"sub": str(u.id)}, expires_delta=timedelta(minutes=7)
    )
    assert delete(client, u, {"password": PW}).status_code == 200
    # a token from another device still dies: the account is inactive
    r = client.get(
        "/api/v1/profiles/customers/me", headers={"Authorization": f"Bearer {other_device_token}"}
    )
    assert r.status_code == 403
    r = client.post("/api/v1/auth/login", json={"email": "ada2@example.com", "password": PW})
    assert r.status_code in (401, 403)


def test_same_email_and_phone_can_be_registered_again(client, db):
    u = user_with_pw(db, email="again@example.com", phone_number="+2348022223333")
    delete(client, u, {"password": PW})
    again = make_user(db, email="again@example.com", phone_number="+2348022223333")
    assert again.id != u.id  # unique constraints were freed by the placeholders


def test_two_deleted_users_do_not_collide(client, db):
    a, b = user_with_pw(db), user_with_pw(db)
    assert delete(client, a, {"password": PW}).status_code == 200
    assert delete(client, b, {"password": PW}).status_code == 200


def test_delete_is_not_repeatable(client, db):
    u = user_with_pw(db)
    token = create_access_token({"sub": str(u.id)})
    assert delete(client, u, {"password": PW}, token=token).status_code == 200
    assert delete(client, u, {"password": PW}, token=token).status_code in (401, 403)


def test_artisan_is_anonymised_unlisted_and_portfolio_removed(
    client, db, deleted_images, blacklisted
):
    artisan = user_with_pw(
        db, user_type=UserType.ARTISAN, profile_picture_url="https://x.test/a.jpg"
    )
    prof = db.query(ArtisanProfile).one()
    prof.specialization = "Plumbing"
    prof.location_address = "Real address"
    prof.nin_last4 = "1234"
    prof.verification_documents = '["https://x.test/doc.jpg"]'
    db.add(Portfolio(artisan_id=artisan.id, image_url="https://x.test/p1.jpg", title="Job 1"))
    db.add(Portfolio(artisan_id=artisan.id, image_url="https://x.test/p2.jpg"))
    db.commit()

    assert delete(client, artisan, {"password": PW}).status_code == 200
    db.expire_all()
    assert db.query(Portfolio).count() == 0
    assert sorted(deleted_images) == [
        "https://x.test/a.jpg",
        "https://x.test/p1.jpg",
        "https://x.test/p2.jpg",
    ]
    prof = db.query(ArtisanProfile).one()
    assert prof.location_address is None and prof.specialization is None
    assert prof.nin_last4 is None and prof.verification_documents is None
    assert prof.availability_status.value == "offline"


# ----------------------------------------------------------------------- blockers


@pytest.mark.parametrize("state", ["accepted", "paid", "in_progress", "disputed"])
def test_active_bookings_block_deletion_for_both_sides(client, db, service, state):
    customer, artisan = user_with_pw(db), user_with_pw(db, user_type=UserType.ARTISAN)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus(state),
        payment_status=None,
        disputed=state == "disputed",
    )
    for who in (customer, artisan):
        r = delete(client, who, {"password": PW})
        assert r.status_code == 409, who
        assert r.json()["detail"]["code"] == "active_bookings"
        assert blockers(r)["active_bookings"]["count"] == 1
    db.expire_all()
    assert db.get(User, customer.id).is_active and db.get(User, artisan.id).is_active


def test_unfinished_withdrawal_blocks(client, db, service):
    artisan, customer = user_with_pw(db, user_type=UserType.ARTISAN), make_user(db)
    booking, payment = make_withdrawable(db, artisan, customer, fx_service(db))
    db.add(
        Withdrawal(
            artisan_id=artisan.id,
            amount=Decimal("9000"),
            status=WithdrawalStatus.PROCESSING,
            reference="WD-TEST-1",
            bank_code="058",
            account_number_last4="1234",
            account_name="Real Name",
        )
    )
    payment.status = (
        PaymentStatus.RELEASED
    )  # money already assigned elsewhere: only the withdrawal blocks
    db.commit()
    r = delete(client, artisan, {"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "unfinished_withdrawal"


def test_needs_review_withdrawal_blocks(client, db):
    artisan = user_with_pw(db, user_type=UserType.ARTISAN)
    db.add(
        Withdrawal(
            artisan_id=artisan.id,
            amount=Decimal("100"),
            status=WithdrawalStatus.NEEDS_REVIEW,
            reference="WD-TEST-2",
            bank_code="058",
            account_number_last4="1234",
        )
    )
    db.commit()
    assert (
        delete(client, artisan, {"password": PW}).json()["detail"]["code"]
        == "unfinished_withdrawal"
    )


def test_withdrawable_balance_blocks_with_the_amount(client, db):
    artisan, customer = user_with_pw(db, user_type=UserType.ARTISAN), make_user(db)
    make_withdrawable(db, artisan, customer, fx_service(db), amount="10000.00")
    db.commit()
    r = delete(client, artisan, {"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "wallet_balance"
    assert Decimal(str(blockers(r)["wallet_balance"]["amount"])) == Decimal("9000.00")


def test_earnings_still_awaiting_confirmation_also_block(client, db):
    """Completed but inside the dispute window: not withdrawable yet, still the artisan's money."""
    artisan, customer = user_with_pw(db, user_type=UserType.ARTISAN), make_user(db)
    booking = fx_booking(
        db, artisan, customer, fx_service(db), status=BookingStatus.COMPLETED, deadline_hours=12
    )
    fx_payment(db, booking, status=PaymentStatus.SUCCESS, paid_at=datetime.now(timezone.utc))
    db.commit()
    r = delete(client, artisan, {"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "wallet_balance"


def test_all_blockers_are_listed(client, db, service):
    artisan, customer = user_with_pw(db, user_type=UserType.ARTISAN), make_user(db)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.IN_PROGRESS,
        payment_status=None,
        disputed=False,
    )
    make_withdrawable(db, artisan, customer, fx_service(db))
    db.add(
        Withdrawal(
            artisan_id=artisan.id,
            amount=Decimal("1"),
            status=WithdrawalStatus.PROCESSING,
            reference="WD-TEST-3",
            bank_code="058",
            account_number_last4="1234",
        )
    )
    db.commit()
    r = delete(client, artisan, {"password": PW})
    assert r.status_code == 409
    assert set(blockers(r)) == {"active_bookings", "unfinished_withdrawal", "wallet_balance"}
    assert r.json()["detail"]["code"] == "active_bookings"  # first blocker


def test_settled_history_does_not_block(client, db, service):
    """Completed, paid out, cancelled, rejected: only history, so deletion goes through."""
    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.COMPLETED,
        payment_status=PaymentStatus.RELEASED,
        disputed=False,
    )
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.REFUNDED,
        disputed=False,
    )
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.REJECTED,
        payment_status=None,
        disputed=False,
    )
    assert delete(client, customer, {"password": PW}).status_code == 200


# ----------------------------------------------------------- pending bookings


def test_pending_bookings_are_closed_and_counterparty_notified(client, db, service, notifications):
    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    pend = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.PENDING,
        payment_status=None,
        disputed=False,
    )
    assert delete(client, customer, {"password": PW}).status_code == 200
    db.expire_all()
    b = db.get(Booking, pend.id)
    assert b.status == BookingStatus.CANCELLED and "deleted" in b.cancellation_reason.lower()
    assert [n["user_id"] for n in notifications] == [str(artisan.id)]


def test_pending_requests_to_a_deleted_artisan_are_rejected(client, db, service):
    customer, artisan = make_user(db), user_with_pw(db, user_type=UserType.ARTISAN)
    pend = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.PENDING,
        payment_status=None,
        disputed=False,
    )
    assert delete(client, artisan, {"password": PW}).status_code == 200
    db.expire_all()
    b = db.get(Booking, pend.id)
    assert b.status == BookingStatus.REJECTED and b.rejection_reason


# ------------------------------------------------------------------ google accounts


class FakeFirebase:
    def __init__(self, monkeypatch):
        self.claims = {}
        monkeypatch.setattr(
            auth_endpoints, "verify_google_claims", lambda token: self.claims[token]
        )


@pytest.fixture()
def firebase(monkeypatch):
    return FakeFirebase(monkeypatch)


def google_user(db):
    u = make_user(db, google_id="g-uid-1", email="g@example.com")
    assert u.hashed_password is not None
    u.hashed_password = None
    db.commit()
    return u


def now_ts(delta=0):
    return int((datetime.now(timezone.utc) + timedelta(seconds=delta)).timestamp())


def test_google_account_needs_a_fresh_matching_google_token(client, db, firebase):
    u = google_user(db)
    r = delete(client, u, {})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "reauth_required"

    firebase.claims["stale"] = {"uid": "g-uid-1", "auth_time": now_ts(-3600)}
    r = delete(client, u, {"google_token": "stale"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "reauth_required"

    firebase.claims["other"] = {"uid": "someone-else", "auth_time": now_ts()}
    r = delete(client, u, {"google_token": "other"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invalid_reauth"

    db.expire_all()
    assert db.get(User, u.id).is_active is True

    firebase.claims["fresh"] = {"uid": "g-uid-1", "auth_time": now_ts(-30)}
    assert delete(client, u, {"google_token": "fresh"}).status_code == 200
    db.expire_all()
    assert db.get(User, u.id).google_id is None


def test_invalid_google_token_is_403_not_a_crash(client, db, monkeypatch):
    u = google_user(db)

    def boom(token):
        raise ValueError("bad token")

    monkeypatch.setattr(auth_endpoints, "verify_google_claims", boom)
    r = delete(client, u, {"google_token": "junk"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "invalid_reauth"


def test_account_with_password_and_google_accepts_the_password(client, db):
    u = user_with_pw(db, google_id="g-linked")
    assert delete(client, u, {"password": PW}).status_code == 200


def test_password_hash_is_gone_so_the_old_password_is_useless(db, client):
    u = user_with_pw(db)
    old_hash = u.hashed_password
    delete(client, u, {"password": PW})
    db.expire_all()
    assert not db.get(User, u.id).hashed_password
    assert verify_password(PW, old_hash)  # sanity: it was a valid hash before
