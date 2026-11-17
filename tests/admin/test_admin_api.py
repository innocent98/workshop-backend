from datetime import datetime, timezone

import pytest

from app.db.models.admin import AdminAuditLog, DisputeResolution
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.user import UserType
from app.services.paystack import PaystackService
from tests.admin.conftest import auth, make_booking, make_user

ADMIN_ROUTES = [
    ("get", "/api/v1/admin/users", None),
    ("get", "/api/v1/admin/bookings", None),
    ("get", "/api/v1/admin/payments", None),
    ("get", "/api/v1/admin/disputes", None),
    (
        "post",
        "/api/v1/admin/bookings/1/resolve-dispute",
        {"resolution": "release_to_artisan", "note": "note"},
    ),
    ("post", "/api/v1/admin/artisans/00000000-0000-0000-0000-000000000000/verify", {}),
    (
        "post",
        "/api/v1/admin/artisans/00000000-0000-0000-0000-000000000000/reject",
        {"note": "no"},
    ),
]


# --------------------------------------------------------------- authorization


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_non_admin_gets_403(client, db, method, path, body):
    user = make_user(db, user_type=UserType.CLIENT)
    resp = getattr(client, method)(
        path, headers=auth(user), **({"json": body} if body is not None else {})
    )
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Admin access required"}


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_artisan_gets_403(client, db, method, path, body):
    user = make_user(db, user_type=UserType.ARTISAN)
    resp = getattr(client, method)(
        path, headers=auth(user), **({"json": body} if body is not None else {})
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_unauthenticated_rejected(client, method, path, body):
    resp = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert resp.status_code in (401, 403)


# ------------------------------------------------------------------ pagination


def test_page_size_capped_at_100(client, admin_h):
    assert client.get("/api/v1/admin/users?page_size=100", headers=admin_h).status_code == 200
    assert client.get("/api/v1/admin/users?page_size=101", headers=admin_h).status_code == 422
    assert client.get("/api/v1/admin/users?page=0", headers=admin_h).status_code == 422


def test_users_pagination_and_filters(client, db, admin_h):
    for i in range(5):
        make_user(db, user_type=UserType.ARTISAN, full_name=f"Artisan {i}")
    make_user(db, user_type=UserType.CLIENT, full_name="Client Joe")

    r = client.get("/api/v1/admin/users?page=1&page_size=2", headers=admin_h)
    body = r.json()
    assert body["total"] == 7  # 5 artisans + client + admin
    assert body["pages"] == 4 and len(body["items"]) == 2

    r = client.get("/api/v1/admin/users?user_type=artisan", headers=admin_h).json()
    assert r["total"] == 5
    assert all(u["verification_status"] == "unverified" for u in r["items"])

    r = client.get("/api/v1/admin/users?q=Client%20Joe", headers=admin_h).json()
    assert [u["full_name"] for u in r["items"]] == ["Client Joe"]
    # wildcard characters are escaped, not interpreted
    assert client.get("/api/v1/admin/users?q=%25", headers=admin_h).json()["total"] == 0
    assert client.get("/api/v1/admin/users?is_admin=true", headers=admin_h).json()["total"] == 1


def test_bookings_and_payments_lists(client, db, admin_h, service):
    customer = make_user(db, full_name="Cust")
    artisan = make_user(db, user_type=UserType.ARTISAN, full_name="Art")
    make_booking(db, service, customer, artisan, status=BookingStatus.PAID, disputed=False)
    make_booking(db, service, customer, artisan, payment_status=PaymentStatus.RELEASED)

    r = client.get("/api/v1/admin/bookings?status=disputed", headers=admin_h).json()
    assert r["total"] == 1
    assert r["items"][0]["customer_name"] == "Cust"
    assert r["items"][0]["payment_status"] == "released"

    p = client.get("/api/v1/admin/payments?status=success", headers=admin_h).json()
    assert p["total"] == 1
    assert "paystack_access_code" not in p["items"][0]
    assert "paystack_reference" not in p["items"][0]
    assert client.get("/api/v1/admin/payments?status=bogus", headers=admin_h).status_code == 422


def test_disputes_lists_only_unresolved(client, db, admin_h, service):
    customer = make_user(db)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    disputed = make_booking(db, service, customer, artisan)
    make_booking(db, service, customer, artisan, status=BookingStatus.COMPLETED, disputed=False)
    r = client.get("/api/v1/admin/disputes", headers=admin_h).json()
    assert [d["booking_id"] for d in r["items"]] == [disputed.id]
    assert r["items"][0]["dispute_reason"] == "Work not done"


# ----------------------------------------------------------- resolve: release


def _resolve(client, headers, booking_id, resolution, note="Reviewed evidence"):
    return client.post(
        f"/api/v1/admin/bookings/{booking_id}/resolve-dispute",
        headers=headers,
        json={"resolution": resolution, "note": note},
    )


def test_release_to_artisan(client, db, admin, admin_h, service, notifications):
    customer = make_user(db)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    b = make_booking(db, service, customer, artisan)

    r = _resolve(client, admin_h, b.id, "release_to_artisan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_resolved"] is False
    assert body["booking_status"] == "completed"
    assert body["payment_status"] == "success"  # payout flow, not this endpoint, moves the money

    db.expire_all()
    b = db.get(Booking, b.id)
    # exactly the state the unchanged payout/wallet queries need: confirmed + not disputed
    assert b.completion_confirmed_by_client_at is not None
    assert b.completion_disputed_at is None

    res = db.query(DisputeResolution).one()
    assert res.admin_id == admin.id and res.resolution == "release_to_artisan"
    assert res.dispute_reason == "Work not done"  # snapshot kept
    assert db.query(AdminAuditLog).filter_by(action="dispute.release_to_artisan").count() == 1
    assert {n[0] for n in notifications} == {str(customer.id), str(artisan.id)}

    # gone from the open list
    assert client.get("/api/v1/admin/disputes", headers=admin_h).json()["total"] == 0


def test_resolve_idempotent_and_conflicting(client, db, admin_h, service, notifications):
    b = make_booking(db, service, make_user(db), make_user(db, user_type=UserType.ARTISAN))
    assert _resolve(client, admin_h, b.id, "release_to_artisan").status_code == 200
    n_sent = len(notifications)

    again = _resolve(client, admin_h, b.id, "release_to_artisan")
    assert again.status_code == 200 and again.json()["already_resolved"] is True
    assert len(notifications) == n_sent  # no duplicate notifications
    assert db.query(DisputeResolution).count() == 1
    assert db.query(AdminAuditLog).count() == 1

    other = _resolve(client, admin_h, b.id, "refund_customer")
    assert other.status_code == 409
    assert other.json()["detail"]["code"] == "already_resolved"


def test_resolve_requires_open_dispute(client, db, admin_h, service):
    b = make_booking(
        db,
        service,
        make_user(db),
        make_user(db, user_type=UserType.ARTISAN),
        status=BookingStatus.COMPLETED,
        disputed=False,
    )
    r = _resolve(client, admin_h, b.id, "release_to_artisan")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_disputed"
    assert _resolve(client, admin_h, 99999, "release_to_artisan").status_code == 404


def test_resolve_validates_body(client, db, admin_h):
    r = client.post(
        "/api/v1/admin/bookings/1/resolve-dispute",
        headers=admin_h,
        json={"resolution": "burn_it_down", "note": "x" * 5},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/admin/bookings/1/resolve-dispute",
        headers=admin_h,
        json={"resolution": "refund_customer", "note": ""},
    )
    assert r.status_code == 422


# ------------------------------------------------------------ resolve: refund


def test_refund_customer_with_fake_paystack(
    client, db, admin_h, service, notifications, monkeypatch
):
    calls = []

    def fake_refund(transaction_reference, amount=None, customer_note=None, merchant_note=None):
        calls.append(transaction_reference)
        return {"id": 4242, "status": "pending"}

    monkeypatch.setattr(PaystackService, "refund", staticmethod(fake_refund))
    customer = make_user(db)
    artisan = make_user(db, user_type=UserType.ARTISAN)
    b = make_booking(db, service, customer, artisan)

    r = _resolve(client, admin_h, b.id, "refund_customer", note="Artisan no-show")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["booking_status"] == "cancelled"
    assert body["payment_status"] == "refunded"
    assert body["refund_reference"] == "4242"

    db.expire_all()
    pay = db.query(Payment).one()
    assert pay.status == PaymentStatus.REFUNDED and pay.refunded_at is not None
    bk = db.get(Booking, b.id)
    assert bk.status == BookingStatus.CANCELLED
    assert "Artisan no-show" in bk.cancellation_reason
    assert {n[0] for n in notifications} == {str(customer.id), str(artisan.id)}

    # idempotent: no second Paystack call
    again = _resolve(client, admin_h, b.id, "refund_customer", note="Artisan no-show")
    assert again.status_code == 200 and again.json()["already_resolved"] is True
    assert calls == [db.query(Payment).one().paystack_reference]


def test_refund_rejected_when_funds_already_released(client, db, admin_h, service, monkeypatch):
    monkeypatch.setattr(
        PaystackService, "refund", staticmethod(lambda *a, **k: pytest.fail("must not be called"))
    )
    b = make_booking(
        db,
        service,
        make_user(db),
        make_user(db, user_type=UserType.ARTISAN),
        payment_status=PaymentStatus.RELEASED,
    )
    r = _resolve(client, admin_h, b.id, "refund_customer")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "payment_not_refundable"


# -------------------------------------------------------- artisan verify/reject


def test_admin_verify_and_reject_artisan(client, db, admin, admin_h, notifications):
    artisan = make_user(db, user_type=UserType.ARTISAN)

    r = client.post(
        f"/api/v1/admin/artisans/{artisan.id}/verify", headers=admin_h, json={"note": "docs ok"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_verified"] is True and body["verification_status"] == "verified"
    assert body["verification_method"] == "admin" and body["verified_at"]

    r = client.post(
        f"/api/v1/admin/artisans/{artisan.id}/reject",
        headers=admin_h,
        json={"note": "ID unreadable"},
    )
    body = r.json()
    assert body["is_verified"] is False and body["verification_status"] == "failed"
    assert body["verification_failure_reason"] == "ID unreadable"
    assert body["verified_at"] is None

    db.expire_all()
    assert db.query(ArtisanProfile).one().verified_by == admin.id
    assert [a.action for a in db.query(AdminAuditLog).order_by(AdminAuditLog.id)] == [
        "artisan.verify",
        "artisan.reject",
    ]


def test_admin_verify_unknown_or_client_user_404(client, db, admin_h):
    client_user = make_user(db, user_type=UserType.CLIENT)
    assert (
        client.post(
            f"/api/v1/admin/artisans/{client_user.id}/verify", headers=admin_h, json={}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/admin/artisans/00000000-0000-0000-0000-000000000000/reject",
            headers=admin_h,
            json={"note": "nope"},
        ).status_code
        == 404
    )
    assert datetime.now(timezone.utc)  # keep import used
