import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import settings
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.user import UserType
from app.db.models.verification_record import ArtisanVerificationRecord
from app.integrations.dojah.client import DojahClient, get_dojah_client
from app.main import app
from tests.admin.conftest import auth, make_user

BASE = "/api/v1/profiles/artisans/me/verification"
WEBHOOK = "/api/v1/verification/webhook"
NIN_FULL = "12345678917"  # placeholder, not a real NIN


def widget_payload(reference, status="Completed", gov=True, selfie=True, vtype="NIN", nin=NIN_FULL):
    record = {"entity": {"first_name": "Jane", "last_name": "Doe"}}
    if nin:
        record["entity"]["nin"] = nin
    return {
        "entity": {
            "reference_id": reference,
            "verification_status": status,
            "verification_type": vtype,
            "data": {
                "government_data": {"status": gov, "data": {vtype.lower(): record}},
                "selfie": {"status": selfie},
            },
        }
    }


class DojahStub:
    """Plays Dojah at the HTTP transport layer: reference -> payload (or status code)."""

    def __init__(self):
        self.results = {}
        self.calls = []

    def set(self, reference, payload=None, status=200):
        self.results[reference] = (status, payload)

    def handler(self, request: httpx.Request):
        ref = request.url.params["reference_id"]
        self.calls.append(ref)
        status, payload = self.results.get(ref, (404, None))
        return (
            httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
        )


@pytest.fixture(autouse=True)
def dojah_settings(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_API_KEY", "secret-key-x")
    monkeypatch.setattr(settings, "DOJAH_APP_ID", "app-id-x")
    monkeypatch.setattr(settings, "DOJAH_PUBLIC_KEY", "pk-x")
    monkeypatch.setattr(settings, "DOJAH_NIN_WIDGET_ID", "widget-nin-x")
    monkeypatch.setattr(settings, "DOJAH_WEBHOOK_SECRET", "whsec")


@pytest.fixture()
def dojah():
    stub = DojahStub()
    transport = httpx.MockTransport(stub.handler)
    app.dependency_overrides[get_dojah_client] = lambda: DojahClient(transport=transport, backoff=0)
    return stub


@pytest.fixture()
def artisan(db):
    user = make_user(db, user_type=UserType.ARTISAN)
    return user, auth(user)


def profile(db):
    db.expire_all()
    return db.query(ArtisanProfile).one()


def start(client, headers):
    return client.post(f"{BASE}/start", headers=headers)


def confirm(client, headers, reference):
    return client.post(f"{BASE}/confirm", headers=headers, json={"reference_id": reference})


def signed(client, body: dict, secret="whsec", signature=None):
    raw = json.dumps(body).encode()
    sig = (
        signature
        if signature is not None
        else hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    )
    return client.post(
        WEBHOOK, content=raw, headers={"x-dojah-signature": sig, "content-type": "application/json"}
    )


# ----------------------------------------------------------------- access / config


def test_clients_are_forbidden(client, db):
    h = auth(make_user(db, user_type=UserType.CLIENT))
    for method, path in [("get", "/config"), ("post", "/start"), ("get", "/status")]:
        assert getattr(client, method)(BASE + path, headers=h).status_code == 403
    assert confirm(client, h, "WC-NIN-0000000000").status_code == 403


def test_config(client, artisan):
    r = client.get(f"{BASE}/config", headers=artisan[1])
    assert r.status_code == 200
    assert r.json() == {
        "configured": True,
        "app_id": "app-id-x",
        "public_key": "pk-x",
        "widget_id": "widget-nin-x",
        "environment": "sandbox",
    }


def test_unconfigured_server(client, artisan, monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_NIN_WIDGET_ID", None)
    assert client.get(f"{BASE}/config", headers=artisan[1]).json()["configured"] is False
    r = start(client, artisan[1])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "verification_unavailable"


@pytest.mark.parametrize(
    "field,value",
    [
        ("DOJAH_API_KEY", "your-dojah-secret-key"),  # the .env.example placeholder
        ("DOJAH_API_KEY", "   "),
        ("DOJAH_API_KEY", ""),
        ("DOJAH_NIN_WIDGET_ID", "your-nin-widget-id"),
        ("DOJAH_NIN_WIDGET_ID", "Your-NIN-Widget-Id"),
        ("DOJAH_NIN_WIDGET_ID", ""),
    ],
)
def test_placeholder_or_blank_credentials_are_unconfigured(
    client, artisan, monkeypatch, field, value
):
    monkeypatch.setattr(settings, field, value)
    body = client.get(f"{BASE}/config", headers=artisan[1]).json()
    assert body["configured"] is False
    r = start(client, artisan[1])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "verification_unavailable"


def test_placeholder_public_fields_are_not_echoed(client, artisan, monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_APP_ID", "your-dojah-app-id")
    monkeypatch.setattr(settings, "DOJAH_PUBLIC_KEY", "your-dojah-public-key")
    monkeypatch.setattr(settings, "DOJAH_NIN_WIDGET_ID", "your-nin-widget-id")
    body = client.get(f"{BASE}/config", headers=artisan[1]).json()
    assert body["configured"] is False
    assert body["app_id"] is None and body["public_key"] is None and body["widget_id"] is None


def test_placeholder_api_key_yields_no_dojah_client(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_API_KEY", "your-dojah-secret-key")
    assert get_dojah_client() is None
    monkeypatch.setattr(settings, "DOJAH_API_KEY", "real-looking-key-123")
    assert get_dojah_client() is not None


def test_status_initial(client, artisan):
    r = client.get(f"{BASE}/status", headers=artisan[1])
    assert r.status_code == 200
    assert r.json() == {
        "verification_status": "unverified",
        "is_verified": False,
        "verified_at": None,
        "verification_method": None,
        "failure_reason": None,
        "nin_last4": None,
        "reference_id": None,
        "attempts_used": 0,
        "attempts_remaining": 5,
        "max_attempts": 5,
        "window_hours": 24,
        "retry_available_at": None,
    }


# ------------------------------------------------------------------------- start


def test_start_records_pending_attempt(client, db, artisan):
    user, h = artisan
    r = start(client, h)
    assert r.status_code == 200
    body = r.json()
    assert body["reference_id"].startswith("WC-NIN-") and len(body["reference_id"]) >= 10
    assert body["widget_id"] == "widget-nin-x" and body["email"] == user.email
    assert body["attempts_remaining"] == 4
    assert profile(db).verification_status == "pending"
    st = client.get(f"{BASE}/status", headers=h).json()
    assert st["verification_status"] == "pending" and st["attempts_used"] == 1
    assert st["reference_id"] == body["reference_id"]


def test_new_start_supersedes_old_pending(client, db, artisan, dojah):
    first = start(client, artisan[1]).json()["reference_id"]
    start(client, artisan[1])
    db.expire_all()
    old = db.query(ArtisanVerificationRecord).filter_by(provider_reference=first).one()
    assert old.status == "failed" and old.failure_reason == "superseded"
    # a late confirm on the superseded reference never reaches Dojah or changes anything
    r = confirm(client, artisan[1], first)
    assert r.status_code == 200 and dojah.calls == []


def test_attempt_limit_and_window_rollover(client, db, artisan):
    _, h = artisan
    for _ in range(5):
        assert start(client, h).status_code == 200
    r = start(client, h)
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "attempts_exhausted" and detail["retry_available_at"]
    st = client.get(f"{BASE}/status", headers=h).json()
    assert st["attempts_remaining"] == 0 and st["retry_available_at"]

    db.query(ArtisanVerificationRecord).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(hours=25)}
    )
    db.commit()
    assert start(client, h).status_code == 200  # window rolled over


def test_already_verified_cannot_start(client, db, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    assert confirm(client, h, ref).json()["verification_status"] == "verified"
    r = start(client, h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_verified"


# ------------------------------------------------------------------------ confirm


def test_confirm_success_verifies_artisan_and_stores_only_last4(
    client, db, artisan, dojah, notifications
):
    user, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    r = confirm(client, h, ref)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verification_status"] == "verified" and body["is_verified"] is True
    assert body["verification_method"] == "dojah" and body["verified_at"]
    assert body["nin_last4"] == "8917" and body["failure_reason"] is None

    p = profile(db)
    assert p.is_verified and p.verification_reference == ref
    rows = [
        str(getattr(r_, c.name))
        for r_ in (p, db.query(ArtisanVerificationRecord).one())
        for c in r_.__table__.columns
        if c.name != "location"
    ]
    assert NIN_FULL not in " ".join(rows) and "Jane" not in " ".join(rows)
    assert [n["title"] for n in notifications] == ["You're verified"]


@pytest.mark.parametrize(
    "kwargs,fragment",
    [
        ({"status": "Failed", "selfie": False}, "did not match"),
        ({"status": "Failed", "gov": False}, "could not verify this NIN"),
        ({"status": "Completed", "selfie": False}, "did not match"),  # Completed but selfie failed
        ({"status": "Abandoned", "gov": False, "selfie": False}, "not completed"),
        ({"status": "Completed", "vtype": "BVN"}, "could not verify this NIN"),
    ],
)
def test_confirm_failures_set_failed_with_reason(
    client, db, artisan, dojah, notifications, kwargs, fragment
):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref, **kwargs))
    body = confirm(client, h, ref).json()
    assert body["verification_status"] == "failed" and body["is_verified"] is False
    assert fragment in body["failure_reason"]
    assert profile(db).is_verified is False
    assert [n["title"] for n in notifications] == ["Verification failed"]
    # and the artisan can retry
    assert start(client, h).status_code == 200


def test_confirm_pending_stays_pending(client, db, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref, status="Ongoing", selfie=False))
    assert confirm(client, h, ref).json()["verification_status"] == "pending"
    dojah.set(ref, widget_payload(ref))
    assert confirm(client, h, ref).json()["verification_status"] == "verified"


def test_confirm_is_idempotent_after_success(client, artisan, dojah, notifications):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    confirm(client, h, ref)
    again = confirm(client, h, ref)
    assert again.json()["verification_status"] == "verified"
    assert dojah.calls == [ref]  # no second fetch
    assert len(notifications) == 1  # notified exactly once


def test_confirm_unknown_or_foreign_reference_is_404(client, db, artisan, dojah):
    _, h = artisan
    r = confirm(client, h, "WC-NIN-doesnotexist")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_reference"
    other = auth(make_user(db, user_type=UserType.ARTISAN))
    ref = start(client, other).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    assert confirm(client, h, ref).status_code == 404  # looks identical to unknown
    assert dojah.calls == []
    assert client.post(f"{BASE}/confirm", headers=h, json={}).status_code == 422


def test_provider_outage_leaves_pending_and_is_retryable(client, db, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, None, status=503)
    r = confirm(client, h, ref)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_error"
    assert profile(db).verification_status == "pending"
    dojah.set(ref, widget_payload(ref))
    assert confirm(client, h, ref).json()["verification_status"] == "verified"


def test_confirm_without_credentials_is_503(client, artisan, monkeypatch):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    monkeypatch.setattr(settings, "DOJAH_API_KEY", None)  # real dependency now returns None
    app.dependency_overrides.pop(get_dojah_client, None)
    r = confirm(client, h, ref)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "verification_unavailable"


def test_admin_decision_wins_over_late_dojah_result(client, db, artisan, dojah, admin_h):
    user, h = artisan
    ref = start(client, h).json()["reference_id"]
    r = client.post(
        f"/api/v1/admin/artisans/{user.id}/reject",
        headers=admin_h,
        json={"note": "Photo ID is fake"},
    )
    assert r.status_code == 200
    dojah.set(ref, widget_payload(ref))  # Dojah says pass, after the admin already rejected
    body = confirm(client, h, ref).json()
    assert body["verification_status"] == "failed" and body["is_verified"] is False
    assert body["failure_reason"] == "Photo ID is fake" and body["verification_method"] == "admin"


def test_admin_rejected_artisan_can_start_again(client, artisan, admin_h):
    user, h = artisan
    client.post(
        f"/api/v1/admin/artisans/{user.id}/reject", headers=admin_h, json={"note": "unclear"}
    )
    assert start(client, h).status_code == 200


def test_admin_verified_artisan_cannot_start(client, artisan, admin_h):
    user, h = artisan
    client.post(f"/api/v1/admin/artisans/{user.id}/verify", headers=admin_h, json={})
    assert start(client, h).status_code == 409


# ------------------------------------------------------------------------- status


def test_status_reconfirms_fresh_pending(client, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    st = client.get(f"{BASE}/status", headers=h).json()
    assert st["verification_status"] == "verified" and dojah.calls == [ref]


def test_status_tolerates_provider_errors(client, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, None, status=500)
    r = client.get(f"{BASE}/status", headers=h)
    assert r.status_code == 200 and r.json()["verification_status"] == "pending"


def test_status_does_not_recheck_stale_pending(client, db, artisan, dojah):
    _, h = artisan
    start(client, h)
    db.query(ArtisanVerificationRecord).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(hours=1)}
    )
    db.commit()
    assert client.get(f"{BASE}/status", headers=h).status_code == 200
    assert dojah.calls == []


def test_artisan_profile_response_includes_verification_status(client, artisan):
    r = client.get("/api/v1/profiles/artisans/me", headers=artisan[1])
    assert r.status_code == 200
    assert r.json()["verification_status"] == "unverified" and r.json()["is_verified"] is False


# ------------------------------------------------------------------------ webhook


def test_webhook_bad_signature_rejected(client, artisan, dojah):
    ref = start(client, artisan[1]).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    for sig in ("deadbeef", ""):
        r = signed(client, {"reference_id": ref}, signature=sig)
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_signature"
    r = signed(client, {"reference_id": ref}, secret="wrong-secret")
    assert r.status_code == 401
    r = client.post(WEBHOOK, json={"reference_id": ref})  # no header at all
    assert r.status_code == 401
    assert dojah.calls == []


def test_webhook_applies_result_via_refetch_not_payload(client, db, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref, status="Failed", selfie=False))
    # the webhook body claims success: it must be ignored in favour of Dojah's API answer
    r = signed(client, {"reference_id": ref, "verification_status": "Completed", "status": True})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    p = profile(db)
    assert p.verification_status == "failed" and p.is_verified is False


def test_webhook_success_marks_verified_and_is_idempotent(
    client, db, artisan, dojah, notifications
):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref))
    assert signed(client, {"reference_id": ref}).status_code == 200
    assert signed(client, {"reference_id": ref}).status_code == 200
    assert profile(db).is_verified and dojah.calls == [ref]
    assert len(notifications) == 1
    # app opens later and sees the final state without calling confirm
    assert client.get(f"{BASE}/status", headers=h).json()["verification_status"] == "verified"


def test_webhook_unknown_or_malformed_is_acknowledged(client, dojah):
    assert signed(client, {"reference_id": "DJ-NOT-OURS-1"}).json() == {"status": "ok"}
    assert signed(client, {"nothing": 1}).status_code == 200
    raw = b"not json"
    sig = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    assert client.post(WEBHOOK, content=raw, headers={"x-dojah-signature": sig}).status_code == 200
    assert dojah.calls == []


def test_webhook_provider_error_returns_non_2xx_so_dojah_retries(client, artisan, dojah):
    ref = start(client, artisan[1]).json()["reference_id"]
    dojah.set(ref, None, status=500)
    assert signed(client, {"reference_id": ref}).status_code == 502


def test_webhook_non_ascii_signature_header_is_401_not_500(client, artisan, dojah):
    ref = start(client, artisan[1]).json()["reference_id"]
    r = client.post(
        WEBHOOK,
        content=json.dumps({"reference_id": ref}).encode(),
        headers={"x-dojah-signature": ("\u00e9" * 64).encode("latin-1")},
    )
    assert r.status_code == 401


def test_confirm_timeout_returns_pending_not_an_error(client, db, artisan):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]

    def slow(request):
        raise httpx.ReadTimeout("slow")

    app.dependency_overrides[get_dojah_client] = lambda: DojahClient(
        transport=httpx.MockTransport(slow), backoff=0
    )
    r = confirm(client, h, ref)
    assert r.status_code == 200 and r.json()["verification_status"] == "pending"
    assert profile(db).verification_status == "pending"


def test_dojah_string_false_never_verifies_through_the_endpoint(client, db, artisan, dojah):
    _, h = artisan
    ref = start(client, h).json()["reference_id"]
    dojah.set(ref, widget_payload(ref, gov="false", selfie="failed"))
    body = confirm(client, h, ref).json()
    assert body["verification_status"] == "failed" and body["is_verified"] is False


def test_endpoints_are_threadpool_functions_not_event_loop_blocking():
    """confirm/status touch sync SQLAlchemy and a blocking HTTP client: they must be plain `def`."""
    import inspect

    from app.api.v1.endpoints import artisan_verification as mod

    for fn in (mod.start_verification, mod.confirm_verification, mod.get_verification_status):
        assert not inspect.iscoroutinefunction(fn), fn.__name__
