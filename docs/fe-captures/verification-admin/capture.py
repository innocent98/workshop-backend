"""
Walk the verification + admin flows against the running capture server and save every
request/response pair as JSON next to this file. Seeds FAKE dev data straight into the DB.
Placeholder NINs only (11 digits, last digit selects the fake Dojah outcome).
"""

import hashlib
import hmac
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx  # noqa: E402
from geoalchemy2 import WKTElement  # noqa: E402

from app.core.security import get_password_hash  # noqa: E402
from app.db.base import import_models  # noqa: E402
from app.db.models.artisan_profile import ArtisanProfile  # noqa: E402
from app.db.models.booking import Booking, BookingStatus  # noqa: E402
from app.db.models.payment import Payment, PaymentStatus  # noqa: E402
from app.db.models.service import Service  # noqa: E402
from app.db.models.user import User, UserType  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8011/api/v1"
PW = "Placeholder-pw-1"
WEBHOOK_SECRET = "whsec-capture-placeholder"
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


def mk_user(db, name, email, phone, utype, admin=False):
    u = User(
        full_name=name,
        email=email,
        phone_number=phone,
        user_type=utype,
        hashed_password=get_password_hash(PW),
        is_admin=admin,
        is_active=True,
        is_email_verified=True,
        registration_completed=True,
    )
    db.add(u)
    db.commit()
    if utype == UserType.ARTISAN:
        db.add(ArtisanProfile(user_id=u.id))
        db.commit()
    return u


def mk_booking(db, ref, svc, cust, art, status, pay_status, disputed):
    now = datetime.now(timezone.utc)
    b = Booking(
        booking_reference=ref,
        customer_id=cust.id,
        artisan_id=art.id,
        service_id=svc.id,
        job_description="Fix leaking kitchen sink",
        job_date=now + timedelta(days=1),
        job_location=WKTElement("POINT(3.3792 6.5244)", srid=4326),
        job_address="12 Example Street, Lagos",
        budget_min=Decimal("5000"),
        budget_max=Decimal("10000"),
        agreed_amount=Decimal("8000"),
        status=status,
        completion_notes="Sink replaced",
        completion_disputed_at=now - timedelta(hours=3) if disputed else None,
        completion_dispute_reason="Leak is still there" if disputed else None,
    )
    db.add(b)
    db.flush()
    db.add(
        Payment(
            payment_reference="PAY-" + ref[-6:],
            paystack_reference="ps_demo_" + ref[-6:],
            booking_id=b.id,
            amount=Decimal("8000"),
            platform_fee=Decimal("800"),
            artisan_amount=Decimal("7200"),
            status=pay_status,
            customer_email=cust.email,
            customer_name=cust.full_name,
        )
    )
    db.commit()
    return b


def main():
    import_models()
    db = SessionLocal()
    svc = Service(name="Plumbing (demo)")
    db.add(svc)
    db.commit()
    admin = mk_user(db, "Demo Admin", "admin@example.com", "+2348000000001", UserType.CLIENT, True)
    art = mk_user(db, "Demo Artisan", "artisan@example.com", "+2348000000002", UserType.ARTISAN)
    art2 = mk_user(db, "Second Artisan", "artisan2@example.com", "+2348000000003", UserType.ARTISAN)
    art3 = mk_user(db, "Third Artisan", "artisan3@example.com", "+2348000000005", UserType.ARTISAN)
    cust = mk_user(db, "Demo Customer", "client@example.com", "+2348000000004", UserType.CLIENT)
    b_release = mk_booking(
        db, "BKG-DEMO01", svc, cust, art, BookingStatus.DISPUTED, PaymentStatus.SUCCESS, True
    )
    b_refund = mk_booking(
        db, "BKG-DEMO02", svc, cust, art, BookingStatus.DISPUTED, PaymentStatus.SUCCESS, True
    )
    mk_booking(db, "BKG-DEMO03", svc, cust, art, BookingStatus.PAID, PaymentStatus.SUCCESS, False)
    b_unsure = mk_booking(
        db, "BKG-DEMO04", svc, cust, art, BookingStatus.DISPUTED, PaymentStatus.SUCCESS, True
    )
    ids = {"art": str(art.id), "art2": str(art2.id), "art3": str(art3.id), "rel": b_release.id,
        "unsure": b_unsure.id, "ref": b_refund.id}
    db.close()

    c = httpx.Client(base_url=BASE, timeout=60)

    def login(email):
        r = c.post("/auth/login", json={"email": email, "password": PW})
        body = save(
            "login-" + email.split("@")[0],
            "POST",
            "/auth/login",
            r,
            {"email": email, "password": "<placeholder>"},
        )
        return {"Authorization": f"Bearer {body['token']}"}

    ah, uh, ch = login("admin@example.com"), login("artisan@example.com"), login("client@example.com")
    # token values are not saved in later files (headers are not recorded)

    # ---- artisan verification (Dojah hosted widget flow; Dojah answers are scripted, see capture_server.py)
    V = "/profiles/artisans/me/verification"

    def widget(ref, status="Completed", gov=True, selfie=True):
        return {"entity": {
            "reference_id": ref, "verification_status": status, "verification_type": "NIN",
            "data": {
                "government_data": {"status": gov, "data": {"nin": {"entity": {
                    "nin": "11111111117", "first_name": "Demo", "last_name": "Artisan"}}}},
                "selfie": {"status": selfie, "message": "Successfully validated your liveness"},
            }}}

    def script(ref, body, status=200):
        c.post(BASE.replace("/api/v1", "") + "/__stub/dojah", json={"reference_id": ref, "body": body, "status": status})

    def start(headers, name, note=None):
        r = c.post(f"{V}/start", headers=headers)
        return save(name, "POST", f"{V}/start", r, None, note)

    def confirm(headers, ref, name, note=None):
        r = c.post(f"{V}/confirm", headers=headers, json={"reference_id": ref})
        return save(name, "POST", f"{V}/confirm", r, {"reference_id": ref}, note)

    save("verif-config", "GET", f"{V}/config", c.get(f"{V}/config", headers=uh))
    save("verif-config-client-forbidden", "GET", f"{V}/config", c.get(f"{V}/config", headers=ch))
    save("verif-status-initial", "GET", f"{V}/status", c.get(f"{V}/status", headers=uh))
    save("verif-confirm-unknown-reference", "POST", f"{V}/confirm", c.post(f"{V}/confirm", headers=uh, json={"reference_id": "WC-NIN-doesnotexist"}), {"reference_id": "WC-NIN-doesnotexist"})

    s1 = start(uh, "verif-start-1")["reference_id"]
    save("verif-status-pending", "GET", f"{V}/status", c.get(f"{V}/status", headers=uh), None, "no Dojah answer scripted yet => Dojah 404 for the reference; status poll tolerates it")
    script(s1, widget(s1, "Failed", selfie=False))
    confirm(uh, s1, "verif-confirm-selfie-failed", "Dojah says Failed + selfie.status=false")
    s2 = start(uh, "verif-start-2")["reference_id"]
    script(s2, widget(s2, "Failed", gov=False, selfie=False))
    confirm(uh, s2, "verif-confirm-nin-failed", "Dojah says Failed + government_data.status=false")
    s3 = start(uh, "verif-start-3")["reference_id"]
    script(s3, widget(s3, "Ongoing", selfie=False))
    confirm(uh, s3, "verif-confirm-still-pending", "Dojah says Ongoing")
    script(s3, None, 503)
    confirm(uh, s3, "verif-confirm-provider-error", "Dojah answers 503 (retried 3x then 502); verification stays pending")
    script(s3, widget(s3))
    confirm(uh, s3, "verif-confirm-success", "Dojah says Completed, NIN verified, selfie passed")
    save("verif-status-verified", "GET", f"{V}/status", c.get(f"{V}/status", headers=uh))
    save("verif-start-already-verified", "POST", f"{V}/start", c.post(f"{V}/start", headers=uh))
    save("artisan-profile-me", "GET", "/profiles/artisans/me", c.get("/profiles/artisans/me", headers=uh))

    # webhook (signed like Dojah does) resolving the second artisan without the app calling confirm
    r = c.post("/auth/login", json={"email": "artisan2@example.com", "password": PW})
    h2 = {"Authorization": f"Bearer {r.json()['token']}"}
    w1 = c.post(f"{V}/start", headers=h2).json()["reference_id"]
    script(w1, widget(w1))
    raw = json.dumps({"reference_id": w1, "verification_status": "Completed"}).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = c.post("/verification/webhook", content=raw, headers={"x-dojah-signature": sig, "content-type": "application/json"})
    save("webhook-ok", "POST", "/verification/webhook", r, json.loads(raw), "header x-dojah-signature = HMAC-SHA256(raw body, DOJAH_WEBHOOK_SECRET) hex")
    r = c.post("/verification/webhook", content=raw, headers={"x-dojah-signature": "deadbeef", "content-type": "application/json"})
    save("webhook-bad-signature", "POST", "/verification/webhook", r, json.loads(raw))
    save("verif-status-after-webhook", "GET", f"{V}/status", c.get(f"{V}/status", headers=h2))

    # attempt exhaustion on a third artisan
    r = c.post("/auth/login", json={"email": "artisan3@example.com", "password": PW})
    h3 = {"Authorization": f"Bearer {r.json()['token']}"}
    for i in range(5):
        r = c.post(f"{V}/start", headers=h3)
    save("verif-start-5th", "POST", f"{V}/start", r, None, "5th start: attempts_remaining 0")
    save("verif-start-attempts-exhausted", "POST", f"{V}/start", c.post(f"{V}/start", headers=h3))

    # ---- admin
    A = "/admin"
    save("admin-users-nonadmin-403", "GET", f"{A}/users", c.get(f"{A}/users", headers=uh))
    save(
        "admin-users",
        "GET",
        f"{A}/users?page=1&page_size=3",
        c.get(f"{A}/users", params={"page": 1, "page_size": 3}, headers=ah),
    )
    save(
        "admin-users-filter",
        "GET",
        f"{A}/users?user_type=artisan&verification_status=failed",
        c.get(
            f"{A}/users",
            params={"user_type": "artisan", "verification_status": "failed"},
            headers=ah,
        ),
    )
    save(
        "admin-users-page-size-101",
        "GET",
        f"{A}/users?page_size=101",
        c.get(f"{A}/users", params={"page_size": 101}, headers=ah),
    )
    save(
        "admin-bookings",
        "GET",
        f"{A}/bookings?status=disputed",
        c.get(f"{A}/bookings", params={"status": "disputed"}, headers=ah),
    )
    save(
        "admin-payments",
        "GET",
        f"{A}/payments?status=success&page_size=2",
        c.get(f"{A}/payments", params={"status": "success", "page_size": 2}, headers=ah),
    )
    save("admin-disputes", "GET", f"{A}/disputes", c.get(f"{A}/disputes", headers=ah))

    R = lambda bid: f"{A}/bookings/{bid}/resolve-dispute"  # noqa: E731
    body = {"resolution": "release_to_artisan", "note": "Photos show the sink replaced"}
    save(
        "resolve-release", "POST", R(ids["rel"]), c.post(R(ids["rel"]), json=body, headers=ah), body
    )
    save(
        "resolve-release-repeat",
        "POST",
        R(ids["rel"]),
        c.post(R(ids["rel"]), json=body, headers=ah),
        body,
        "same resolution again: idempotent",
    )
    b2 = {"resolution": "refund_customer", "note": "x" * 3}
    save(
        "resolve-conflict",
        "POST",
        R(ids["rel"]),
        c.post(R(ids["rel"]), json=b2, headers=ah),
        b2,
        "different resolution after the fact",
    )
    body = {"resolution": "refund_customer", "note": "Artisan never showed up"}
    save(
        "resolve-refund",
        "POST",
        R(ids["ref"]),
        c.post(R(ids["ref"]), json=body, headers=ah),
        body,
        "Paystack POST /refund is STUBBED in capture_server.py (needs a real transaction): NOT VERIFIED LIVE against Paystack",
    )
    # refund whose Paystack outcome is unknown: intent kept, release blocked, retry reconciles
    STUB = BASE.replace("/api/v1", "") + "/__stub/paystack"
    c.post(STUB, json={"mode": "timeout"})
    body = {"resolution": "refund_customer", "note": "Customer proved the job was never done"}
    save("resolve-refund-unconfirmed", "POST", R(ids["unsure"]), c.post(R(ids["unsure"]), json=body, headers=ah), body,
         "Paystack stub: request times out and the refund lookup finds nothing => outcome unknown")
    body = {"resolution": "release_to_artisan", "note": "Changed my mind"}
    save("resolve-release-blocked-by-refund-intent", "POST", R(ids["unsure"]), c.post(R(ids["unsure"]), json=body, headers=ah), body,
         "a refund intent exists, so paying the artisan is refused (double-spend guard)")
    c.post(STUB, json={"mode": "ok"})
    body = {"resolution": "refund_customer", "note": "Customer proved the job was never done"}
    save("resolve-refund-retry", "POST", R(ids["unsure"]), c.post(R(ids["unsure"]), json=body, headers=ah), body, "retry after the outage")
    save(
        "resolve-not-disputed",
        "POST",
        R(ids["rel"] + 2),
        c.post(
            R(ids["rel"] + 2),
            json={"resolution": "release_to_artisan", "note": "n/a n/a"},
            headers=ah,
        ),
        None,
        "booking 3 is PAID, not disputed",
    )
    save(
        "resolve-bad-body",
        "POST",
        R(1),
        c.post(R(1), json={"resolution": "nope", "note": ""}, headers=ah),
    )
    save("admin-disputes-after", "GET", f"{A}/disputes", c.get(f"{A}/disputes", headers=ah))

    AV = f"{A}/artisans/{ids['art3']}"
    save(
        "admin-reject-artisan",
        "POST",
        f"{AV}/reject",
        c.post(f"{AV}/reject", json={"note": "ID photo unreadable"}, headers=ah),
        {"note": "ID photo unreadable"},
    )
    save(
        "admin-verify-artisan",
        "POST",
        f"{AV}/verify",
        c.post(f"{AV}/verify", json={"note": "Verified in person"}, headers=ah),
        {"note": "Verified in person"},
    )
    save("verif-status-after-admin-verify", "GET", f"{V}/status", c.get(f"{V}/status", headers=h3))


if __name__ == "__main__":
    main()
