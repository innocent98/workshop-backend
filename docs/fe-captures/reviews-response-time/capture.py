"""Walk the response-time stat and the review-moderation endpoints against the running capture
server and save every request/response (see capture_server.py). Seeds fake data into the scratch DB
named by DATABASE_URL (tables are created here, so point it at an empty database)."""

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx  # noqa: E402
from geoalchemy2 import WKTElement  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.db.base import Base, import_models  # noqa: E402
from app.db.models.admin import AdminAuditLog  # noqa: E402
from app.db.models.artisan_profile import ArtisanProfile  # noqa: E402
from app.db.models.booking import Booking, BookingStatus  # noqa: E402
from app.db.models.review import Review, ReviewReport  # noqa: E402
from app.db.models.service import Service  # noqa: E402
from app.db.models.user import User, UserType  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402

OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8013"
API = BASE + "/api/v1"
PW = "Placeholder-pw-1"
LAGOS = "POINT(3.3792 6.5244)"
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
        full_name=name,
        email=email,
        phone_number=phone,
        user_type=utype,
        hashed_password=get_password_hash(PW),
        is_active=True,
        is_email_verified=True,
        registration_completed=True,
        **kw,
    )
    db.add(u)
    db.commit()
    if utype == UserType.ARTISAN:
        db.add(
            ArtisanProfile(
                user_id=u.id,
                specialization="Plumbing",
                location=WKTElement(LAGOS, srid=4326),
                location_address="12 Example Street, Lagos",
            )
        )
        db.commit()
    return u


def mk_booking(db, ref, svc, cust, art, status, requested_minutes_ago=0, confirmed=False):
    now = datetime.now(timezone.utc)
    b = Booking(
        booking_reference=ref,
        customer_id=cust.id,
        artisan_id=art.id,
        service_id=svc.id,
        job_description="Fix leaking sink",
        job_date=now + timedelta(days=1),
        job_location=WKTElement(LAGOS, srid=4326),
        job_address="12 Example Street",
        budget_min=Decimal("5000"),
        budget_max=Decimal("10000"),
        agreed_amount=Decimal("8000") if status != BookingStatus.PENDING else None,
        status=status,
        created_at=now - timedelta(minutes=requested_minutes_ago),
        completion_confirmed_by_client_at=now if confirmed else None,
    )
    db.add(b)
    db.commit()
    return b


def main():
    import_models()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)
    if "cap" not in (engine.url.database or ""):
        sys.exit("refusing to wipe a database whose name does not contain 'cap'")
    with engine.begin() as conn:  # idempotent re-runs: start from empty tables
        names = ", ".join(
            f'"{t.name}"' for t in Base.metadata.sorted_tables if t.name != "spatial_ref_sys"
        )
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    db = SessionLocal()
    svc = Service(name="Plumbing (demo)")
    db.add(svc)
    db.commit()
    art = mk_user(db, "Demo Artisan", "artisan@example.com", "+2348000000002", UserType.ARTISAN)
    art2 = mk_user(
        db, "Newcomer Artisan", "newcomer@example.com", "+2348000000008", UserType.ARTISAN
    )
    cust1 = mk_user(db, "Customer One", "cust1@example.com", "+2348000000003", UserType.CLIENT)
    cust2 = mk_user(db, "Customer Two", "cust2@example.com", "+2348000000004", UserType.CLIENT)
    cust3 = mk_user(db, "Customer Three", "cust3@example.com", "+2348000000005", UserType.CLIENT)
    other = mk_user(db, "Other Customer", "other@example.com", "+2348000000006", UserType.CLIENT)
    admin = mk_user(
        db, "Demo Admin", "admin@example.com", "+2348000000007", UserType.CLIENT, is_admin=True
    )
    # Requests are seeded with back-dated created_at (the walk cannot wait 25 minutes). The
    # acceptance time is the real server clock when the PATCH arrives.
    p = BookingStatus.PENDING
    b_fast = mk_booking(db, "BKG-RT0001", svc, cust1, art, p, requested_minutes_ago=25)
    b_slow = mk_booking(db, "BKG-RT0002", svc, cust2, art, p, requested_minutes_ago=40)
    b_rej = mk_booking(db, "BKG-RT0003", svc, cust3, art, p, requested_minutes_ago=10)
    done = BookingStatus.COMPLETED
    c1 = mk_booking(db, "BKG-RV0001", svc, cust1, art, done, confirmed=True)
    c2 = mk_booking(db, "BKG-RV0002", svc, cust2, art, done, confirmed=True)
    c3 = mk_booking(db, "BKG-RV0003", svc, cust3, art, done, confirmed=True)
    uid = {
        "artisan": str(art.id),
        "newcomer": str(art2.id),
        "cust1": str(cust1.id),
        "cust2": str(cust2.id),
        "cust3": str(cust3.id),
        "other": str(other.id),
        "admin": str(admin.id),
    }
    ids = {
        "art": str(art.id),
        "art2": str(art2.id),
        "fast": b_fast.id,
        "slow": b_slow.id,
        "rej": b_rej.id,
        "c1": c1.id,
        "c2": c2.id,
        "c3": c3.id,
    }
    db.close()

    c = httpx.Client(timeout=30)

    # Tokens are minted with the app's own signer: POST /auth/login is limited to 5 per 15 minutes
    # per IP and the walk needs seven users. (Login itself is not part of this feature.)
    h = {k: {"Authorization": "Bearer " + create_access_token({"sub": v})} for k, v in uid.items()}

    def get(name, path, headers=None, params=None, note=None):
        r = c.get(API + path, headers=headers, params=params)
        shown = path + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
        return save(name, "GET", shown, r, None, note)

    def send(method, name, path, headers, body, note=None):
        r = c.request(method, API + path, headers=headers, json=body)
        return save(name, method, path, r, body, note)

    # ------------------------------------------------------------ response time
    get(
        "rt-stats-before",
        "/profiles/artisans/me/stats",
        h["artisan"],
        note="no accepted booking yet",
    )
    send(
        "PATCH",
        "rt-accept-first",
        f"/bookings/{ids['fast']}/accept",
        h["artisan"],
        {"agreed_amount": 8000},
        "request seeded 25 min ago",
    )
    get("rt-stats-after-first", "/profiles/artisans/me/stats", h["artisan"])
    send(
        "PATCH",
        "rt-accept-second",
        f"/bookings/{ids['slow']}/accept",
        h["artisan"],
        {"agreed_amount": 8000},
        "request seeded 40 min ago",
    )
    get(
        "rt-stats-after-second",
        "/profiles/artisans/me/stats",
        h["artisan"],
        note="average of the two",
    )
    send(
        "PATCH",
        "rt-reject",
        f"/bookings/{ids['rej']}/reject",
        h["artisan"],
        {"rejection_reason": "fully booked that day"},
        "rejections are not counted",
    )
    get("rt-stats-after-reject", "/profiles/artisans/me/stats", h["artisan"], note="unchanged")
    get("rt-public-profile", f"/profiles/artisans/{ids['art']}", None, note="what a customer sees")
    get(
        "rt-public-profile-newcomer",
        f"/profiles/artisans/{ids['art2']}",
        None,
        note="no accepted booking: null",
    )
    for order in ("asc", "desc"):
        get(
            f"rt-search-{order}",
            "/search/artisans",
            None,
            {
                "latitude": 6.5244,
                "longitude": 3.3792,
                "sort_by": "response_time",
                "sort_order": order,
            },
            note="artisans with no figure sort last in both directions",
        )

    # ----------------------------------------------------------------- reviews
    rev = lambda cust, bid, rating, text: {  # noqa: E731
        "booking_id": bid,
        "rating": rating,
        "review_text": text,
        "is_anonymous": False,
    }
    r1 = send(
        "POST",
        "review-create-clean",
        "/reviews",
        h["cust1"],
        rev(1, ids["c1"], 5.0, "Excellent work, finished on time and very professional."),
    )
    r2 = send(
        "POST",
        "review-create-abusive",
        "/reviews",
        h["cust2"],
        rev(2, ids["c2"], 1.0, "This man na mumu, total idiot. Never again."),
        "auto-filter hit: still 201 for the reviewer",
    )
    r3 = send(
        "POST",
        "review-create-clean-2",
        "/reviews",
        h["cust3"],
        rev(3, ids["c3"], 3.0, "Decent job, a bit slow but the sink is fixed."),
    )
    get(
        "review-reviewer-reads-own",
        f"/reviews/booking/{ids['c2']}",
        h["cust2"],
        note="the reviewer still sees the hidden review",
    )
    get(
        "review-public-list",
        f"/reviews/artisan/{ids['art']}",
        None,
        note="flagged review is absent; total/average exclude it",
    )
    get("review-public-stats", f"/reviews/artisan/{ids['art']}/stats", None)
    get(
        "review-profile-ratings",
        "/profiles/artisans/me/stats",
        h["artisan"],
        note="average_rating/total_ratings exclude the hidden review",
    )

    # ------------------------------------------------------------------ report
    rep = lambda reason, details=None: {"reason": reason, "details": details}  # noqa: E731
    path = lambda r: f"/reviews/{r['id']}/report"  # noqa: E731
    send("POST", "report-no-auth", path(r1), None, rep("fake"))
    send(
        "POST",
        "report-ok",
        path(r1),
        h["other"],
        rep("fake", "I do not know this customer."),
        "any signed-in user except the author",
    )
    send("POST", "report-duplicate", path(r1), h["other"], rep("spam"))
    send("POST", "report-own-review", path(r1), h["cust1"], rep("other"))
    send("POST", "report-not-found", "/reviews/99999/report", h["other"], rep("spam"))
    send("POST", "report-invalid-reason", path(r3), h["other"], rep("i dislike it"))
    send("POST", "report-ok-2", path(r2), h["other"], rep("abusive"))
    send(
        "POST",
        "report-user-cap",
        path(r3),
        h["other"],
        rep("spam"),
        "capture server runs with REVIEW_REPORTS_PER_USER_PER_HOUR=2 (default is 10)",
    )
    send(
        "POST",
        "report-by-artisan",
        path(r3),
        h["artisan"],
        rep("fake", "Never booked me for this."),
        "the reviewed artisan reports too",
    )

    # ------------------------------------------------------------------- admin
    get("admin-list-no-auth", "/admin/reviews", None)
    get("admin-list-not-admin", "/admin/reviews", h["cust1"])
    get(
        "admin-queue",
        "/admin/reviews",
        h["admin"],
        note="flagged OR open reports, most reports first",
    )
    get("admin-queue-flagged", "/admin/reviews", h["admin"], {"queue": "flagged"})
    get("admin-queue-reported", "/admin/reviews", h["admin"], {"queue": "reported"})
    get(
        "admin-detail",
        f"/admin/reviews/{r1['id']}",
        h["admin"],
        note="includes the individual reports",
    )
    send(
        "POST",
        "admin-flag-validation",
        f"/admin/reviews/{r1['id']}/flag",
        h["admin"],
        {"note": "x"},
    )
    send(
        "POST",
        "admin-flag",
        f"/admin/reviews/{r1['id']}/flag",
        h["admin"],
        {"note": "Reporter is right: this person never used the service."},
    )
    get(
        "admin-after-flag-public-list",
        f"/reviews/artisan/{ids['art']}",
        None,
        note="r1 now hidden too",
    )
    get("admin-after-flag-profile", "/profiles/artisans/me/stats", h["artisan"])
    send(
        "POST",
        "admin-unflag",
        f"/admin/reviews/{r1['id']}/unflag",
        h["admin"],
        {"note": "Booking records confirm the job; restoring."},
    )
    get("admin-after-unflag-public-list", f"/reviews/artisan/{ids['art']}", None)
    send(
        "POST",
        "admin-unflag-auto-flagged",
        f"/admin/reviews/{r2['id']}/unflag",
        h["admin"],
        {"note": "Reviewed: harsh but fair, slang."},
        "restoring an auto-flagged review",
    )
    get(
        "admin-after-restore-profile",
        "/profiles/artisans/me/stats",
        h["artisan"],
        note="r2 counted again (1.0 star)",
    )
    send(
        "POST",
        "admin-unflag-nothing-to-do",
        f"/admin/reviews/{r2['id']}/unflag",
        h["admin"],
        {"note": "again"},
    )
    send(
        "POST",
        "admin-flag-not-found",
        "/admin/reviews/99999/flag",
        h["admin"],
        {"note": "does not exist"},
    )

    db = SessionLocal()
    state = {
        "reviews": [
            {
                "id": r.id,
                "rating": r.rating,
                "is_flagged": r.is_flagged,
                "flag_source": r.flag_source,
                "flag_reason": r.flag_reason,
                "open_report_count": r.open_report_count,
            }
            for r in db.query(Review).order_by(Review.id)
        ],
        "reports": [
            {
                "review_id": r.review_id,
                "reason": r.reason,
                "resolved": r.resolved_at is not None,
            }
            for r in db.query(ReviewReport).order_by(ReviewReport.id)
        ],
        "audit_log": [
            {"action": a.action, "target": f"{a.target_type}:{a.target_id}", "details": a.details}
            for a in db.query(AdminAuditLog).order_by(AdminAuditLog.id)
        ],
    }
    n_ = len(list(OUT.glob("[0-9][0-9]-*.json"))) + 1
    (OUT / f"{n_:02d}-db-state-at-end.json").write_text(
        json.dumps(state, indent=2, default=str) + "\n"
    )
    print("db state saved")


if __name__ == "__main__":
    main()
