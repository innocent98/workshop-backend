"""DELETE /auth/me: in-app account deletion (App Store / Play requirement).

Soft-delete + anonymise: financial rows stay (accounting) but point at an anonymised user.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints import auth as auth_endpoints
from app.core.config import settings
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
from app.services.account_deletion import DeletionBlocked, delete_account, is_own_upload
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


@pytest.fixture(autouse=True)
def cloudinary_settings(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDINARY_CLOUD_NAME", "democloud")
    monkeypatch.setattr(settings, "CLOUDINARY_FOLDER", "workchop")


def own_url(user_id, kind="profile_pictures", name="abc", ext="jpg"):
    return (
        f"https://res.cloudinary.com/democloud/image/upload/v1700000000/workchop/{kind}/"
        f"{user_id}_{name}.{ext}"
    )


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
        location_address="12 Real Street",
        location_latitude=6.5,
        location_longitude=3.3,
        google_id="g-123",
    )
    customer.profile_picture_url = own_url(customer.id)
    db.commit()
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
    assert deleted_images == [own_url(customer.id)]

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
    artisan = user_with_pw(db, user_type=UserType.ARTISAN)
    artisan.profile_picture_url = own_url(artisan.id)
    prof = db.query(ArtisanProfile).one()
    prof.specialization = "Plumbing"
    prof.location_address = "Real address"
    prof.nin_last4 = "1234"
    prof.verification_documents = '["https://x.test/doc.jpg"]'
    p1, p2 = own_url(artisan.id, "portfolio", "p1"), own_url(artisan.id, "portfolio", "p2")
    db.add(Portfolio(artisan_id=artisan.id, image_url=p1, title="Job 1"))
    db.add(Portfolio(artisan_id=artisan.id, image_url=p2))
    db.commit()

    assert delete(client, artisan, {"password": PW}).status_code == 200
    db.expire_all()
    assert db.query(Portfolio).count() == 0
    assert sorted(deleted_images) == sorted([own_url(artisan.id), p1, p2])
    prof = db.query(ArtisanProfile).one()
    assert prof.location_address is None and prof.specialization is None
    assert prof.nin_last4 is None and prof.verification_documents is None
    assert prof.availability_status.value == "offline"


def test_only_this_users_own_uploads_reach_the_storage_delete(client, db, deleted_images):
    """A Google picture, a foreign URL, another user's file, traversal paths: never deleted."""
    artisan = user_with_pw(db, user_type=UserType.ARTISAN)
    other = make_user(db)
    artisan.profile_picture_url = "https://lh3.googleusercontent.com/a/photo.jpg"  # Google picture
    bad = [
        own_url(other.id, "portfolio", "stolen"),  # another user's upload
        "https://evil.example.com/workchop/portfolio/" + f"{artisan.id}_x.jpg",  # foreign host
        "https://res.cloudinary.com/othercloud/image/upload/workchop/portfolio/"
        + f"{artisan.id}_x.jpg",
        f"https://res.cloudinary.com/democloud/image/upload/other_folder/{artisan.id}_x.jpg",
        f"/static/portfolio/../../etc/{artisan.id}_x.jpg",  # traversal
        f"/static/other/{artisan.id}_x.jpg",
        "uploads/portfolio/" + f"{artisan.id}_x.jpg",
        "",
    ]
    good = own_url(artisan.id, "portfolio", "mine")
    local_good = f"/static/portfolio/{artisan.id}_local.jpg"
    for url in bad + [good, local_good]:
        db.add(Portfolio(artisan_id=artisan.id, image_url=url or "x"))
    db.commit()
    assert delete(client, artisan, {"password": PW}).status_code == 200
    assert sorted(deleted_images) == sorted([good, local_good])  # everything else was skipped
    db.expire_all()
    assert db.query(Portfolio).count() == 0  # rows are removed either way


def test_is_own_upload_rules():
    uid = "11111111-1111-1111-1111-111111111111"
    assert is_own_upload(own_url(uid), uid)
    assert is_own_upload(own_url(uid, "portfolio", ext="png"), uid)
    assert is_own_upload(f"/static/profile_pictures/{uid}_a.jpg", uid)
    assert not is_own_upload(own_url(uid, "progress_logs"), uid)  # not a user-owned folder
    assert not is_own_upload(own_url("22222222-2222-2222-2222-222222222222"), uid)
    assert not is_own_upload(None, uid)


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


def test_delete_account_rechecks_blockers_under_locks_and_changes_nothing(db, service):
    """Even if a caller skipped the pre-check (or a booking was accepted a moment ago), the
    service itself refuses and leaves the account untouched."""
    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.ACCEPTED,
        payment_status=None,
        disputed=False,
    )
    pend = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.PENDING,
        payment_status=None,
        disputed=False,
    )
    user = db.query(User).filter(User.id == customer.id).with_for_update().one()
    with pytest.raises(DeletionBlocked) as exc:
        delete_account(db, user)
    assert exc.value.blockers[0]["code"] == "active_bookings"
    db.expire_all()
    u = db.get(User, customer.id)
    assert u.is_active and u.deleted_at is None and u.email != "" and u.hashed_password
    assert db.get(Booking, pend.id).status == BookingStatus.PENDING  # pending not closed either
    assert db.query(AdminAuditLog).count() == 0


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


# ------------------------------------------------- PII on financial rows / refunds / attempts

RAW_PAYSTACK = {
    "id": 4099,
    "status": "success",
    "reference": "ps_demo_1",
    "amount": 800000,
    "channel": "card",
    "currency": "NGN",
    "fees": 12000,
    "customer": {"id": 1, "email": "ada@example.com", "first_name": "Ada", "phone": "0801"},
    "authorization": {"last4": "4081", "bank": "TEST BANK", "account_name": "ADA CUSTOMER"},
    "log": {"history": [{"message": "Attempted to pay"}], "ip": "1.2.3.4"},
    "ip_address": "1.2.3.4",
    "metadata": {"booking_id": 1},
}


def test_raw_paystack_json_on_payments_is_scrubbed_but_accounting_fields_stay(client, db, service):
    import json

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
    p = db.query(Payment).one()
    p.paystack_response = json.dumps(RAW_PAYSTACK)
    p.payout_response = json.dumps(
        {
            "transfer_code": "TRF_1",
            "amount": 720000,
            "recipient": {"details": {"account_name": "ADA"}},
        }
    )
    db.commit()

    assert delete(client, customer, {"password": PW}).status_code == 200
    db.expire_all()
    p = db.query(Payment).one()
    raw = json.loads(p.paystack_response)
    for gone in ("customer", "authorization", "log", "ip_address"):
        assert gone not in raw
    blob = p.paystack_response + (p.payout_response or "")
    for pii in ("ada@example.com", "Ada", "4081", "ADA CUSTOMER", "1.2.3.4", "TEST BANK", "0801"):
        assert pii not in blob
    assert raw["amount"] == 800000 and raw["reference"] == "ps_demo_1" and raw["channel"] == "card"
    payout = json.loads(p.payout_response)
    assert payout["transfer_code"] == "TRF_1" and "recipient" not in payout


def test_unparseable_raw_json_is_nulled(client, db, service):
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
    p = db.query(Payment).one()
    p.paystack_response = "not json ada@example.com"
    db.commit()
    assert delete(client, customer, {"password": PW}).status_code == 200
    db.expire_all()
    assert db.query(Payment).one().paystack_response is None


def test_artisan_side_payout_json_is_scrubbed_too(client, db, service):
    import json

    customer, artisan = make_user(db), user_with_pw(db, user_type=UserType.ARTISAN)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.COMPLETED,
        payment_status=PaymentStatus.RELEASED,
        disputed=False,
    )
    p = db.query(Payment).one()
    p.payout_response = json.dumps(
        {"transfer_code": "TRF_9", "recipient": {"details": {"account_number": "0123456789"}}}
    )
    db.commit()
    assert delete(client, artisan, {"password": PW}).status_code == 200
    db.expire_all()
    out = db.query(Payment).one().payout_response
    assert "0123456789" not in out and "TRF_9" in out


def test_customer_with_a_refund_owed_cannot_delete_yet(client, db, service):
    """A payment flagged needs_refund is money we still owe back: block, so the customer can be
    contacted and refunded (the refund itself works by Paystack reference either way)."""
    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.SUCCESS,
        disputed=False,
    )
    pay = db.query(Payment).one()
    pay.needs_refund = True
    db.commit()
    r = delete(client, customer, {"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "refund_pending"
    assert blockers(r)["refund_pending"]["count"] == 1
    pay.needs_refund = False  # refunded by an admin
    db.commit()
    assert delete(client, customer, {"password": PW}).status_code == 200


def test_refunds_in_flight_after_an_admin_resolution_do_not_block(client, db, service):
    """A refund accepted by Paystack (cancelled + refunded) completes by reference."""
    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.REFUNDED,
        disputed=False,
    )
    assert delete(client, customer, {"password": PW}).status_code == 200


def test_wrong_passwords_are_limited_per_user_not_only_per_ip(client, db):
    u = user_with_pw(db)
    for _ in range(5):
        assert delete(client, u, {"password": "nope-nope"}).status_code == 403
    r = delete(client, u, {"password": PW})  # even the right password is refused while locked
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"
    db.expire_all()
    assert db.get(User, u.id).is_active is True

    other = user_with_pw(db)  # another user (same IP) is not affected
    assert delete(client, other, {"password": PW}).status_code == 200


def test_a_successful_delete_resets_nothing_it_needs_and_failures_expire(db, client):
    from app.core import attempt_limit

    u = user_with_pw(db)
    assert delete(client, u, {"password": "nope-nope"}).status_code == 403
    assert attempt_limit.failures("account_delete", str(u.id)) == 1
    assert delete(client, u, {"password": PW}).status_code == 200
    assert attempt_limit.failures("account_delete", str(u.id)) == 0  # cleared on success


# ---------------------------------------- in-flight dispute refunds (review: blocker)


def refund_resolution(db, booking, admin, refund_status):
    from app.db.models.admin import DisputeResolution

    db.add(
        DisputeResolution(
            booking_id=booking.id,
            admin_id=admin.id,
            resolution="refund_customer",
            note="Artisan no-show",
            refund_status=refund_status,
            refund_reference="4242",
        )
    )
    db.commit()


@pytest.mark.parametrize("refund_status", ["requested", "pending", "processing", "needs-attention"])
@pytest.mark.parametrize("side", ["customer", "artisan"])
def test_in_flight_dispute_refund_blocks_both_parties(client, db, service, refund_status, side):
    """refund_customer cancels the booking and marks the payment REFUNDED once Paystack accepts it;
    a later refund.failed puts both back to disputed/success. Until the refund is final
    (processed) neither party may delete, or the reopened dispute would be owed to a deleted user.
    """
    customer, artisan = user_with_pw(db), user_with_pw(db, user_type=UserType.ARTISAN)
    admin = make_user(db, is_admin=True)
    b = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.REFUNDED,
        disputed=False,
    )
    refund_resolution(db, b, admin, refund_status)
    who = customer if side == "customer" else artisan
    r = delete(client, who, {"password": PW})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "refund_pending"
    assert blockers(r)["refund_pending"]["count"] == 1
    db.expire_all()
    assert db.get(User, who.id).is_active is True


def test_a_processed_refund_no_longer_blocks(client, db, service):
    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    admin = make_user(db, is_admin=True)
    b = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.REFUNDED,
        disputed=False,
    )
    refund_resolution(db, b, admin, "processed")
    assert delete(client, customer, {"password": PW}).status_code == 200


def test_release_resolutions_never_block(client, db, service):
    from app.db.models.admin import DisputeResolution

    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    admin = make_user(db, is_admin=True)
    b = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.COMPLETED,
        payment_status=PaymentStatus.RELEASED,
        disputed=False,
    )
    db.add(
        DisputeResolution(
            booking_id=b.id, admin_id=admin.id, resolution="release_to_artisan", note="ok ok"
        )
    )
    db.commit()
    assert delete(client, customer, {"password": PW}).status_code == 200


def test_refund_failed_after_the_block_cannot_strand_money_on_a_deleted_account(
    client, db, service, monkeypatch
):
    """End to end: while the refund is pending the delete is refused; once Paystack's failed event
    reopens the dispute the booking is disputed (still blocking); only a processed refund frees it.
    """
    from app.services.admin import handle_refund_event
    from app.services.paystack import PaystackService

    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    admin = make_user(db, is_admin=True)
    b = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.CANCELLED,
        payment_status=PaymentStatus.REFUNDED,
        disputed=False,
    )
    refund_resolution(db, b, admin, "pending")
    assert delete(client, customer, {"password": PW}).status_code == 409
    ref = db.query(Payment).one().paystack_reference
    monkeypatch.setattr(PaystackService, "list_refunds", staticmethod(lambda tx: []))
    assert (
        handle_refund_event(db, "refund.failed", {"transaction_reference": ref, "id": 4242})
        == "failed"
    )
    db.expire_all()
    assert db.get(Booking, b.id).status == BookingStatus.DISPUTED
    r = delete(client, customer, {"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "active_bookings"


# ----------------------------------------------- change-password attempt limit (per user)

CHANGE_URL = "/api/v1/auth/change-password"


def change(client, user, current, new="Brand-new-pass-1"):
    return client.post(
        CHANGE_URL,
        headers=auth(user),
        json={"current_password": current, "new_password": new, "confirm_password": new},
    )


def test_change_password_wrong_attempts_are_limited_per_user(client, db):
    u = user_with_pw(db)
    for _ in range(5):
        r = change(client, u, "wrong-password-1")
        assert r.status_code == 400
    r = change(client, u, PW)  # even the right password is refused while locked
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"
    db.expire_all()
    assert verify_password(PW, db.get(User, u.id).hashed_password)  # unchanged

    other = user_with_pw(db)
    assert change(client, other, PW).status_code == 200  # another user is unaffected


def test_change_password_success_clears_the_counter(client, db):
    from app.core import attempt_limit

    u = user_with_pw(db)
    assert change(client, u, "wrong-password-1").status_code == 400
    assert attempt_limit.failures("change_password", str(u.id)) == 1
    assert change(client, u, PW).status_code == 200
    assert attempt_limit.failures("change_password", str(u.id)) == 0


# ------------------------------------------- Redis outage: delete / change-password fail CLOSED


class _BrokenRedis:
    def __getattr__(self, name):
        def boom(*args, **kwargs):
            raise ConnectionError("redis is down")

        return boom


@pytest.fixture()
def redis_down(monkeypatch):
    from app.core import attempt_limit

    monkeypatch.setattr(attempt_limit, "redis_client", _BrokenRedis())


def test_delete_fails_closed_with_503_when_the_limiter_is_down(client, db, redis_down):
    u = user_with_pw(db)
    r = delete(client, u, {"password": PW})  # even the correct password: no unlimited guessing
    assert r.status_code == 503 and r.json()["detail"]["code"] == "limiter_unavailable"
    db.expire_all()
    assert db.get(User, u.id).is_active is True


def test_change_password_fails_closed_with_503_when_the_limiter_is_down(client, db, redis_down):
    u = user_with_pw(db)
    r = change(client, u, PW)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "limiter_unavailable"
    db.expire_all()
    assert verify_password(PW, db.get(User, u.id).hashed_password)  # unchanged


def test_login_is_unaffected_by_a_limiter_outage(client, db, redis_down):
    user_with_pw(db, email="outage@example.com")
    r = client.post("/api/v1/auth/login", json={"email": "outage@example.com", "password": PW})
    assert r.status_code == 200, r.text


def test_a_blocked_delete_does_not_use_up_the_attempt_budget(client, db, service):
    """A correct password followed by a 409 blocker is not a failure: it is given back."""
    from app.core import attempt_limit

    customer, artisan = user_with_pw(db), make_user(db, user_type=UserType.ARTISAN)
    make_booking(db, service, customer, artisan, status=BookingStatus.ACCEPTED, disputed=False)
    for _ in range(7):
        r = delete(client, customer, {"password": PW})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "active_bookings"
    assert attempt_limit.failures("account_delete", str(customer.id)) == 0


def test_change_password_and_delete_counters_are_independent(client, db):
    u = user_with_pw(db)
    for _ in range(5):
        change(client, u, "wrong-password-1")
    # the delete counter is separate: a wrong delete password is a normal 403, not a lockout
    r = delete(client, u, {"password": "wrong-password-1"})
    assert r.status_code == 403
