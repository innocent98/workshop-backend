"""Abusive-review filter end to end: auto-flag on creation, the public/aggregate view, user
reports, and the admin moderation endpoints (with audit log and rating recalculation)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.models.admin import AdminAuditLog
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import BookingStatus
from app.db.models.review import Review, ReviewReport
from app.db.models.user import UserType
from tests.admin.conftest import auth, make_booking, make_user
from tests.factories import make_service as fx_service

REVIEWS = "/api/v1/reviews"
ADMIN = "/api/v1/admin/reviews"
CLEAN = "Excellent work, finished on time and very professional."
ABUSIVE = "This man na mumu, total idiot. Never again."


@pytest.fixture()
def service(db):
    s = fx_service(db)
    db.commit()
    return s


@pytest.fixture(autouse=True)
def _generous_ip_limit(monkeypatch):
    # The per-IP slowapi backstop is shared process/Redis state: keep it out of the way except in
    # the test that exercises it.
    monkeypatch.setattr(settings, "REVIEW_REPORT_IP_RATE_LIMIT", "1000/hour")


@pytest.fixture()
def artisan(db):
    return make_user(db, user_type=UserType.ARTISAN)


def completed_booking(db, service, customer, artisan):
    b = make_booking(
        db,
        service,
        customer,
        artisan,
        status=BookingStatus.COMPLETED,
        payment_status=None,
        disputed=False,
    )
    b.completion_confirmed_by_client_at = datetime.now(timezone.utc)
    db.commit()
    return b


def post_review(client, db, service, artisan, rating, text, customer=None):
    customer = customer or make_user(db, user_type=UserType.CLIENT)
    b = completed_booking(db, service, customer, artisan)
    r = client.post(
        REVIEWS,
        json={"booking_id": b.id, "rating": rating, "review_text": text},
        headers=auth(customer),
    )
    return r, customer, b


def profile(db, artisan):
    db.expire_all()
    return db.query(ArtisanProfile).filter(ArtisanProfile.user_id == artisan.id).one()


def public(client, artisan):
    r = client.get(f"{REVIEWS}/artisan/{artisan.id}")
    assert r.status_code == 200
    return r.json()


# ------------------------------------------------------------ auto filter on creation


def test_clean_review_is_public_and_counts(client, db, service, artisan, notifications):
    r, _, _ = post_review(client, db, service, artisan, 4.0, CLEAN)
    assert r.status_code == 201
    assert r.json()["is_flagged"] is False
    p = profile(db, artisan)
    assert (p.total_ratings, p.average_rating) == (1, 4.0)
    assert public(client, artisan)["total"] == 1
    assert [n["data"]["event"] for n in notifications] == ["review_received"]


def test_abusive_review_is_accepted_but_hidden_and_not_counted(
    client, db, service, artisan, notifications
):
    r, customer, booking = post_review(client, db, service, artisan, 1.0, ABUSIVE)
    # the reviewer sees an ordinary accepted review
    assert r.status_code == 201
    assert r.json()["review_text"] == ABUSIVE
    # stored flagged with a reason; no flag detail leaks in the response schema
    review = db.query(Review).one()
    assert review.is_flagged is True
    assert review.flag_source == "auto"
    assert "abusive language" in review.flag_reason
    assert review.flagged_at is not None
    assert "flag_reason" not in r.json()
    # the reviewer can still read it back
    mine = client.get(f"{REVIEWS}/booking/{booking.id}", headers=auth(customer))
    assert mine.status_code == 200
    assert mine.json()["review_text"] == ABUSIVE
    # hidden from the public listing and the aggregates
    body = public(client, artisan)
    assert body["total"] == 0 and body["reviews"] == [] and body["average_rating"] == 0.0
    stats = client.get(f"{REVIEWS}/artisan/{artisan.id}/stats").json()
    assert stats["total_reviews"] == 0 and stats["average_rating"] == 0.0
    p = profile(db, artisan)
    assert (p.total_ratings, p.average_rating) == (0, 0.0)
    # the artisan is not pinged about a review nobody can see
    assert notifications == []


def test_mixed_reviews_average_only_the_unflagged(client, db, service, artisan):
    post_review(client, db, service, artisan, 5.0, CLEAN)
    post_review(client, db, service, artisan, 1.0, ABUSIVE)
    post_review(client, db, service, artisan, 3.0, None)
    p = profile(db, artisan)
    assert p.total_ratings == 2
    assert p.average_rating == pytest.approx(4.0)
    body = public(client, artisan)
    assert body["total"] == 2
    assert body["average_rating"] == pytest.approx(4.0)
    assert body["rating_distribution"]["1"] == 0


def test_filter_off_switch(client, db, service, artisan, monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_ABUSE_FILTER_ENABLED", False)
    r, _, _ = post_review(client, db, service, artisan, 2.0, ABUSIVE)
    assert r.status_code == 201 and db.query(Review).one().is_flagged is False


# --------------------------------------------------------------------- report review


def make_review(client, db, service, artisan, text=CLEAN, rating=4.0):
    r, customer, _ = post_review(client, db, service, artisan, rating, text)
    return r.json()["id"], customer


def test_report_requires_auth(client, db, service, artisan):
    rid, _ = make_review(client, db, service, artisan)
    assert client.post(f"{REVIEWS}/{rid}/report", json={"reason": "abusive"}).status_code in (
        401,
        403,
    )


def test_artisan_reports_a_review(client, db, service, artisan):
    rid, _ = make_review(client, db, service, artisan)
    r = client.post(
        f"{REVIEWS}/{rid}/report",
        json={"reason": "fake", "details": "  I never worked for this person.  "},
        headers=auth(artisan),
    )
    assert r.status_code == 201
    assert r.json() == {"review_id": rid, "reported": True}
    review = db.get(Review, rid)
    db.refresh(review)
    assert review.open_report_count == 1
    # a report alone never hides the review or changes the rating
    assert review.is_flagged is False
    assert profile(db, artisan).total_ratings == 1
    saved = db.query(ReviewReport).one()
    assert saved.reporter_id == artisan.id and saved.reason == "fake"
    assert saved.details == "I never worked for this person."


def test_other_customer_can_report_too(client, db, service, artisan):
    rid, _ = make_review(client, db, service, artisan)
    other = make_user(db, user_type=UserType.CLIENT)
    r = client.post(f"{REVIEWS}/{rid}/report", json={"reason": "spam"}, headers=auth(other))
    assert r.status_code == 201


def test_one_report_per_user_per_review(client, db, service, artisan):
    rid, _ = make_review(client, db, service, artisan)
    first = client.post(
        f"{REVIEWS}/{rid}/report", json={"reason": "abusive"}, headers=auth(artisan)
    )
    again = client.post(f"{REVIEWS}/{rid}/report", json={"reason": "spam"}, headers=auth(artisan))
    assert first.status_code == 201
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "already_reported"
    review = db.get(Review, rid)
    db.refresh(review)
    assert review.open_report_count == 1
    assert db.query(ReviewReport).count() == 1


def test_cannot_report_own_review(client, db, service, artisan):
    rid, customer = make_review(client, db, service, artisan)
    r = client.post(f"{REVIEWS}/{rid}/report", json={"reason": "other"}, headers=auth(customer))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "cannot_report_own_review"


def test_report_unknown_review_and_bad_reason(client, db, service, artisan):
    missing = client.post(f"{REVIEWS}/9999/report", json={"reason": "spam"}, headers=auth(artisan))
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "review_not_found"
    rid, _ = make_review(client, db, service, artisan)
    bad = client.post(
        f"{REVIEWS}/{rid}/report", json={"reason": "i dislike it"}, headers=auth(artisan)
    )
    assert bad.status_code == 422


def test_per_user_hourly_cap(client, db, service, artisan, monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_REPORTS_PER_USER_PER_HOUR", 2)
    reporter = make_user(db, user_type=UserType.CLIENT)
    ids = [make_review(client, db, service, artisan)[0] for _ in range(4)]
    codes = [
        client.post(f"{REVIEWS}/{i}/report", json={"reason": "spam"}, headers=auth(reporter))
        for i in ids
    ]
    assert [c.status_code for c in codes] == [201, 201, 429, 429]
    assert codes[2].json()["detail"]["code"] == "report_rate_limited"
    # reports older than an hour no longer count
    db.query(ReviewReport).update(
        {ReviewReport.created_at: datetime.now(timezone.utc) - timedelta(hours=2)}
    )
    db.commit()
    again = client.post(
        f"{REVIEWS}/{ids[2]}/report", json={"reason": "spam"}, headers=auth(reporter)
    )
    assert again.status_code == 201


def test_ip_rate_limit_backstop(client, db, service, artisan, monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_REPORT_IP_RATE_LIMIT", "2/13minutes")
    rid, _ = make_review(client, db, service, artisan)
    other = make_user(db, user_type=UserType.CLIENT)
    third = make_user(db, user_type=UserType.CLIENT)
    codes = [
        client.post(f"{REVIEWS}/{rid}/report", json={"reason": "spam"}, headers=auth(u)).status_code
        for u in (artisan, other, third)
    ]
    assert codes == [201, 201, 429]


# ----------------------------------------------------------------- admin moderation


@pytest.fixture()
def admin(db):
    return make_user(db, is_admin=True, full_name="Admin One")


def test_admin_endpoints_require_admin(client, db, service, artisan):
    rid, customer = make_review(client, db, service, artisan)
    for method, path, body in [
        ("get", ADMIN, None),
        ("get", f"{ADMIN}/{rid}", None),
        ("post", f"{ADMIN}/{rid}/flag", {"note": "nope"}),
        ("post", f"{ADMIN}/{rid}/unflag", {"note": "nope"}),
    ]:
        anon = getattr(client, method)(path, **({"json": body} if body else {}))
        assert anon.status_code in (401, 403)
        user = getattr(client, method)(
            path, headers=auth(customer), **({"json": body} if body else {})
        )
        assert user.status_code == 403


def test_queue_lists_flagged_and_reported_reviews(client, db, service, artisan, admin):
    clean_id, _ = make_review(client, db, service, artisan)
    reported_id, _ = make_review(client, db, service, artisan)
    hidden_id, _ = make_review(client, db, service, artisan, text=ABUSIVE, rating=1.0)
    client.post(f"{REVIEWS}/{reported_id}/report", json={"reason": "fake"}, headers=auth(artisan))

    def ids(queue):
        r = client.get(ADMIN, params={"queue": queue}, headers=auth(admin))
        assert r.status_code == 200
        return [i["id"] for i in r.json()["items"]]

    assert ids("flagged") == [hidden_id]
    assert ids("reported") == [reported_id]
    assert set(ids("needs_attention")) == {hidden_id, reported_id}
    assert clean_id not in ids("needs_attention")
    body = client.get(ADMIN, headers=auth(admin)).json()
    assert body["total"] == 2 and body["page"] == 1
    hidden = next(i for i in body["items"] if i["id"] == hidden_id)
    assert hidden["is_flagged"] is True and hidden["flag_source"] == "auto"
    assert "abusive language" in hidden["flag_reason"]
    assert hidden["review_text"] == ABUSIVE
    assert client.get(ADMIN, params={"queue": "bogus"}, headers=auth(admin)).status_code == 422
    only = client.get(
        ADMIN,
        params={"artisan_id": str(make_user(db, user_type=UserType.ARTISAN).id)},
        headers=auth(admin),
    )
    assert only.json()["total"] == 0


def test_detail_shows_reports(client, db, service, artisan, admin):
    rid, _ = make_review(client, db, service, artisan)
    client.post(
        f"{REVIEWS}/{rid}/report",
        json={"reason": "abusive", "details": "insults"},
        headers=auth(artisan),
    )
    r = client.get(f"{ADMIN}/{rid}", headers=auth(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["open_report_count"] == 1
    assert [x["reason"] for x in body["reports"]] == ["abusive"]
    assert body["reports"][0]["reporter_id"] == str(artisan.id)
    assert body["reports"][0]["resolved_at"] is None
    assert client.get(f"{ADMIN}/9999", headers=auth(admin)).status_code == 404


def test_admin_flag_hides_review_recalculates_and_audits(client, db, service, artisan, admin):
    good, _ = make_review(client, db, service, artisan, rating=5.0)
    bad, _ = make_review(client, db, service, artisan, rating=1.0, text="Rude and late")
    assert profile(db, artisan).total_ratings == 2
    client.post(f"{REVIEWS}/{bad}/report", json={"reason": "abusive"}, headers=auth(artisan))

    r = client.post(f"{ADMIN}/{bad}/flag", json={"note": "  targeted abuse  "}, headers=auth(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["is_flagged"] is True and body["flag_source"] == "admin"
    assert body["flag_reason"] == "targeted abuse"
    assert body["open_report_count"] == 0

    p = profile(db, artisan)
    assert (p.total_ratings, p.average_rating) == (1, 5.0)
    pub = public(client, artisan)
    assert (
        pub["total"] == 1 and pub["average_rating"] == 5.0 and pub["rating_distribution"]["1"] == 0
    )
    assert [x["id"] for x in pub["reviews"]] == [good]
    assert db.query(ReviewReport).one().resolved_at is not None

    log = db.query(AdminAuditLog).filter_by(action="review.flag").one()
    assert log.admin_id == admin.id and log.target_type == "review" and log.target_id == str(bad)
    assert log.details == {"note": "targeted abuse", "was_flagged": False, "reports_resolved": 1}


def test_admin_unflag_restores_review_and_rating(client, db, service, artisan, admin):
    make_review(client, db, service, artisan, rating=5.0)
    hidden, _ = make_review(client, db, service, artisan, rating=1.0, text=ABUSIVE)
    assert profile(db, artisan).total_ratings == 1

    r = client.post(
        f"{ADMIN}/{hidden}/unflag", json={"note": "slang, not abuse"}, headers=auth(admin)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_flagged"] is False
    assert (
        body["flag_source"] is None and body["flag_reason"] is None and body["flagged_at"] is None
    )

    p = profile(db, artisan)
    assert (p.total_ratings, p.average_rating) == (2, pytest.approx(3.0))
    pub = public(client, artisan)
    assert pub["total"] == 2 and pub["average_rating"] == pytest.approx(3.0)
    assert pub["rating_distribution"]["1"] == 1
    log = db.query(AdminAuditLog).filter_by(action="review.unflag").one()
    assert log.target_id == str(hidden) and log.details["was_flagged"] is True


def test_unflag_dismisses_reports_on_a_visible_review(client, db, service, artisan, admin):
    rid, _ = make_review(client, db, service, artisan)
    client.post(f"{REVIEWS}/{rid}/report", json={"reason": "spam"}, headers=auth(artisan))
    r = client.post(f"{ADMIN}/{rid}/unflag", json={"note": "reviewed, fine"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["open_report_count"] == 0
    assert db.query(ReviewReport).one().resolved_at is not None
    assert client.get(ADMIN, headers=auth(admin)).json()["total"] == 0
    assert profile(db, artisan).total_ratings == 1
    # a second dismissal has nothing to do
    again = client.post(f"{ADMIN}/{rid}/unflag", json={"note": "again"}, headers=auth(admin))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "review_not_flagged"


def test_flag_is_idempotent_and_confirms_an_auto_flag(client, db, service, artisan, admin):
    rid, _ = make_review(client, db, service, artisan, rating=1.0, text=ABUSIVE)
    r = client.post(f"{ADMIN}/{rid}/flag", json={"note": "confirmed abuse"}, headers=auth(admin))
    assert r.status_code == 200
    assert r.json()["flag_source"] == "admin" and r.json()["flag_reason"] == "confirmed abuse"
    assert profile(db, artisan).total_ratings == 0
    assert (
        db.query(AdminAuditLog).filter_by(action="review.flag").one().details["was_flagged"] is True
    )


def test_moderation_validation_and_unknown_review(client, db, service, artisan, admin):
    rid, _ = make_review(client, db, service, artisan)
    assert client.post(f"{ADMIN}/{rid}/flag", json={}, headers=auth(admin)).status_code == 422
    assert (
        client.post(f"{ADMIN}/{rid}/flag", json={"note": "x"}, headers=auth(admin)).status_code
        == 422
    )
    for action in ("flag", "unflag"):
        r = client.post(f"{ADMIN}/9999/{action}", json={"note": "whatever"}, headers=auth(admin))
        assert r.status_code == 404 and r.json()["detail"]["code"] == "review_not_found"
    assert db.query(AdminAuditLog).count() == 0


def test_flag_then_unflag_roundtrip_leaves_rating_unchanged(client, db, service, artisan, admin):
    a, _ = make_review(client, db, service, artisan, rating=4.0)
    b, _ = make_review(client, db, service, artisan, rating=2.0)
    before = profile(db, artisan)
    snapshot = (before.total_ratings, before.average_rating)
    client.post(f"{ADMIN}/{b}/flag", json={"note": "test flag"}, headers=auth(admin))
    assert (profile(db, artisan).total_ratings, profile(db, artisan).average_rating) == (1, 4.0)
    client.post(f"{ADMIN}/{b}/unflag", json={"note": "test unflag"}, headers=auth(admin))
    after = profile(db, artisan)
    assert (after.total_ratings, after.average_rating) == snapshot
    assert a != b
