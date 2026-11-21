"""
Minimal live smoke journey against a deployed stack (staging).

Deliberately read-only / rejection-only: nothing here creates users, bookings or payments,
and nothing needs a Paystack or Dojah key. It proves the deployed image boots, the proxy and
TLS in front of it work, the database answers, and the webhook routes are reachable.

(A throwaway register -> login journey is not possible without reading the email OTP, and
registration would leave junk rows in the staging database on every deploy.)
"""

import uuid

import pytest

pytestmark = pytest.mark.e2e


def test_root_health(live):
    r = live.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_v1_health(live):
    r = live.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_services_categories_hits_the_database(live):
    # Public endpoint that runs a real query. The list may be empty until
    # scripts/seed_services.py has been run on this stack, so only the shape is asserted.
    r = live.get("/api/v1/services/categories")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    for category in body:
        assert {"id", "name"} <= set(category)


def test_protected_route_rejects_anonymous(live):
    r = live.get("/api/v1/auth/me/services")
    assert r.status_code in (401, 403)


def test_login_rejects_unknown_account(live):
    # Exercises the DB lookup + password path with an account that cannot exist.
    # Rate limited to 5/15min per IP; cd-staging.yml clears the limiter keys first.
    r = live.post(
        "/api/v1/auth/login",
        json={"email": f"e2e-{uuid.uuid4().hex[:12]}@example.com", "password": "not-a-real-pw"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/api/v1/payments/webhook", "/api/v1/verification/webhook"],
)
def test_webhooks_are_reachable_and_reject_unsigned_requests(live, path):
    # Proves nginx forwards the provider webhook paths unmodified and that the app
    # verifies signatures (fails closed) instead of accepting anything.
    r = live.post(path, content=b'{"event":"smoke.test"}')
    assert r.status_code == 401
