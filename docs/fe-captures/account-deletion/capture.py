"""Walk DELETE /auth/me against the running capture server and save every request/response."""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx  # noqa: E402
from geoalchemy2 import WKTElement  # noqa: E402

from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.db.base import import_models  # noqa: E402
from app.db.models.booking import Booking, BookingStatus  # noqa: E402
from app.db.models.payment import Payment, PaymentStatus  # noqa: E402
from app.db.models.push_device import PushDevice  # noqa: E402
from app.db.models.service import Service  # noqa: E402
from app.db.models.user import User, UserType  # noqa: E402
from app.db.models.artisan_profile import ArtisanProfile  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8012"
API = BASE + "/api/v1"
PW = "Placeholder-pw-1"
n = 0


def save(name, method, path, resp, req_body=None, note=None):
    global n
    n += 1
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    shown = dict(body) if isinstance(body, dict) else body
    if isinstance(shown, dict) and "token" in shown:
        shown["token"] = "<jwt redacted>"
    rec = {
        "request": {"method": method, "path": path, "body": req_body},
        "status": resp.status_code,
        "response": shown,
    }
    if note:
        rec["note"] = note
    (OUT / f"{n:02d}-{name}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    print(f"{n:02d} {method} {path} -> {resp.status_code}")
    return body


def mk_user(db, name, email, phone, utype, **kw):
    u = User(
        full_name=name, email=email, phone_number=phone, user_type=utype,
        hashed_password=get_password_hash(PW), is_active=True, is_email_verified=True,
        registration_completed=True, **kw,
    )
    db.add(u)
    db.commit()
    if utype == UserType.ARTISAN:
        db.add(ArtisanProfile(user_id=u.id, specialization="Plumbing"))
        db.commit()
    return u


def mk_booking(db, ref, svc, cust, art, status, pay_status=None):
    now = datetime.now(timezone.utc)
    b = Booking(
        booking_reference=ref, customer_id=cust.id, artisan_id=art.id, service_id=svc.id,
        job_description="Fix leaking sink", job_date=now + timedelta(days=1),
        job_location=WKTElement("POINT(3.3792 6.5244)", srid=4326), job_address="12 Example Street",
        budget_min=Decimal("5000"), budget_max=Decimal("10000"), agreed_amount=Decimal("8000"),
        status=status,
    )
    db.add(b)
    db.flush()
    if pay_status:
        db.add(Payment(
            payment_reference="PAY-" + ref[-6:], paystack_reference="ps_demo_" + ref[-6:],
            booking_id=b.id, amount=Decimal("8000"), platform_fee=Decimal("800"),
            artisan_amount=Decimal("7200"), status=pay_status, customer_email=cust.email,
            customer_name=cust.full_name, paid_at=now,
        ))
    db.commit()
    return b


def main():
    import_models()
    db = SessionLocal()
    svc = Service(name="Plumbing (demo)")
    db.add(svc)
    db.commit()
    art = mk_user(db, "Demo Artisan", "artisan@example.com", "+2348000000002", UserType.ARTISAN)
    blocked = mk_user(db, "Blocked Customer", "blocked@example.com", "+2348000000003", UserType.CLIENT)
    leaving = mk_user(db, "Leaving Customer", "leaving@example.com", "+2348000000004", UserType.CLIENT,
                      bio="About me", location_address="12 Example Street", location_latitude=6.5, location_longitude=3.3)
    admin = mk_user(db, "Demo Admin", "admin@example.com", "+2348000000005", UserType.CLIENT, is_admin=True)
    googler = mk_user(db, "Google User", "googler@example.com", "+2348000000006", UserType.CLIENT, google_id="g-demo-uid")
    googler.hashed_password = None
    db.add(PushDevice(user_id=leaving.id, fcm_token="demo-token", platform="android", is_active=True))
    db.commit()
    mk_booking(db, "BKG-DEMO01", svc, blocked, art, BookingStatus.ACCEPTED)
    mk_booking(db, "BKG-DEMO02", svc, leaving, art, BookingStatus.PENDING)
    mk_booking(db, "BKG-DEMO03", svc, leaving, art, BookingStatus.COMPLETED, PaymentStatus.RELEASED)
    # artisan with earnings still owed (completed, not withdrawn)
    mk_booking(db, "BKG-DEMO04", svc, blocked, art, BookingStatus.COMPLETED, PaymentStatus.SUCCESS)
    ids = {"leaving": leaving.id, "googler": googler.id}
    g_uid = str(googler.id)
    db.close()

    c = httpx.Client(timeout=30)

    def login(email):
        r = c.post(f"{API}/auth/login", json={"email": email, "password": PW})
        body = save("login-" + email.split("@")[0], "POST", "/auth/login", r, {"email": email, "password": "<placeholder>"})
        return {"Authorization": f"Bearer {body['token']}"}

    h_art, h_blocked, h_leaving, h_admin = (
        login("artisan@example.com"), login("blocked@example.com"),
        login("leaving@example.com"), login("admin@example.com"),
    )
    h_google = {"Authorization": "Bearer " + create_access_token({"sub": g_uid})}

    def delete(name, headers, body, note=None):
        r = c.request("DELETE", f"{API}/auth/me", headers=headers, json=body)
        return save(name, "DELETE", "/auth/me", r, body, note)

    r = c.request("DELETE", f"{API}/auth/me", json={"password": PW})
    save("delete-no-auth", "DELETE", "/auth/me", r, {"password": "<placeholder>"})
    delete("delete-password-required", h_leaving, {})
    delete("delete-wrong-password", h_leaving, {"password": "not-my-password"})
    delete("delete-blocked-active-booking", h_blocked, {"password": PW}, "customer with an ACCEPTED booking")
    delete("delete-blocked-artisan", h_art, {"password": PW}, "artisan: active booking + completed job with earnings not yet withdrawn")
    delete("delete-admin-refused", h_admin, {"password": PW})

    stub = BASE + "/__stub/google"
    now = int(datetime.now(timezone.utc).timestamp())
    delete("delete-google-reauth-required", h_google, {}, "Google-only account, no token sent")
    c.post(stub, json={"token": "stale", "claims": {"uid": "g-demo-uid", "auth_time": now - 3600}})
    delete("delete-google-stale-token", h_google, {"google_token": "stale"}, "Firebase verification STUBBED (NOT VERIFIED LIVE against Firebase)")
    c.post(stub, json={"token": "other", "claims": {"uid": "someone-else", "auth_time": now}})
    delete("delete-google-wrong-account", h_google, {"google_token": "other"})
    c.post(stub, json={"token": "fresh", "claims": {"uid": "g-demo-uid", "auth_time": now - 20}})
    delete("delete-google-success", h_google, {"google_token": "fresh"}, "Firebase verification STUBBED (NOT VERIFIED LIVE against Firebase)")

    delete("delete-success", h_leaving, {"password": PW}, "customer: pending booking auto-cancelled, completed+paid history kept")
    delete("delete-repeat-same-token", h_leaving, {"password": PW}, "the token was revoked by the first delete")
    r = c.get(f"{API}/profiles/customers/me", headers=h_leaving)
    save("me-after-delete", "GET", "/profiles/customers/me", r, None, "same (revoked) token")
    r = c.post(f"{API}/auth/login", json={"email": "leaving@example.com", "password": PW})
    save("login-after-delete", "POST", "/auth/login", r, {"email": "leaving@example.com", "password": "<placeholder>"})

    db = SessionLocal()
    u = db.get(User, ids["leaving"])
    rows = {
        "user": {
            "full_name": u.full_name, "email": u.email, "phone_number": u.phone_number,
            "hashed_password": u.hashed_password, "bio": u.bio, "location_address": u.location_address,
            "is_active": u.is_active, "deleted_at_set": u.deleted_at is not None,
        },
        "bookings_kept": [(b.booking_reference, b.status.value, str(b.agreed_amount)) for b in db.query(Booking).filter(Booking.customer_id == u.id).order_by(Booking.id)],
        "payments_kept": [(p.payment_reference, p.status.value, str(p.amount), p.customer_name, p.customer_email) for p in db.query(Payment).join(Booking).filter(Booking.customer_id == u.id)],
        "push_devices": db.query(PushDevice).filter(PushDevice.user_id == u.id).count(),
    }
    (OUT / f"{n + 1:02d}-db-state-after-delete.json").write_text(json.dumps({"note": "direct DB read after the delete (not an API response)", "state": rows}, indent=2) + "\n")
    print("db state saved")
    db.close()
    time.sleep(0)


if __name__ == "__main__":
    main()
