"""
Capture REAL request/response bodies for docs/fe-integration-guide-payments-wallet.md.

Starts the actual FastAPI app (uvicorn subprocess) against a scratch PostGIS database that
already has `alembic upgrade head` applied, plus a tiny local stand-in for the Paystack REST API
(so the real PaystackService code paths run). Everything else (DB, locking, webhooks signature,
auth) is the real app. All data is obviously fake.

Usage (scratch DB + redis only!):
    DATABASE_URL=postgresql://test_user:test_password@localhost:55434/test_db \
    REDIS_URL=redis://localhost:56380/0 \
    poetry run python scripts/capture_payments_wallet.py

Output: docs/fe-integration-captures/payments-wallet/NN-<name>.json
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from sqlalchemy import text

APP_PORT, PAYSTACK_PORT = 18765, 18766
WEBHOOK_SECRET = "whsec_capture_placeholder"
OUT = Path(__file__).resolve().parents[1] / "docs/fe-integration-captures/payments-wallet"

db_url = os.environ["DATABASE_URL"]
assert "test" in db_url.rsplit("/", 1)[-1], "refusing to run against a non-test database"
os.environ.update(
    ENVIRONMENT="development",
    SERVER_HOST="http://localhost",
    SECRET_KEY="capture-secret-key",
    FIRST_SUPERUSER_EMAIL="admin@example.com",
    FIRST_SUPERUSER_PASSWORD="placeholder",
    PAYSTACK_BASE_URL=f"http://127.0.0.1:{PAYSTACK_PORT}",
    PAYSTACK_SECRET_KEY="sk_test_placeholder",
    PAYSTACK_WEBHOOK_SECRET=WEBHOOK_SECRET,
    FCM_ENABLED="false",
)


# --------------------------------------------------------------------------- fake Paystack
class FakePaystack(BaseHTTPRequestHandler):
    transfers = 0

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        return json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")

    def do_POST(self):
        body = self._json()
        if self.path == "/transaction/initialize":
            return self._send(
                {
                    "status": True,
                    "message": "Authorization URL created",
                    "data": {
                        "authorization_url": "https://checkout.paystack.com/placeholder",
                        "access_code": "placeholder_access",
                        "reference": body["reference"],
                    },
                }
            )
        if self.path == "/transferrecipient":
            return self._send(
                {
                    "status": True,
                    "message": "Recipient created",
                    "data": {"recipient_code": "RCP_placeholder"},
                }
            )
        if self.path == "/transfer":
            FakePaystack.transfers += 1
            return self._send(
                {
                    "status": True,
                    "message": "Transfer has been queued",
                    "data": {
                        "transfer_code": f"TRF_placeholder{FakePaystack.transfers}",
                        "reference": body["reference"],
                        "amount": body["amount"],
                        "status": "pending",
                    },
                }
            )
        self._send({"status": False, "message": "not found"}, 404)

    def do_GET(self):
        if self.path.startswith("/bank/resolve"):
            return self._send(
                {
                    "status": True,
                    "data": {"account_number": "0000000000", "account_name": "JANE PLACEHOLDER"},
                }
            )
        self._send({"status": False, "message": "not found"}, 404)

    def log_message(self, *a):
        pass


# --------------------------------------------------------------------------- helpers
BASE = f"http://127.0.0.1:{APP_PORT}/api/v1"
counter = [0]


def capture(
    name, method, path, *, token=None, json_body=None, headers=None, raw_body=None, note=None
):
    counter[0] += 1
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token['value']}"
    kwargs = {"headers": hdrs, "timeout": 30}
    if raw_body is not None:
        kwargs["data"] = raw_body
        shown_body = json.loads(raw_body)
    elif json_body is not None:
        kwargs["json"] = json_body
        shown_body = json_body
    else:
        shown_body = None
    r = requests.request(method, BASE + path, **kwargs)
    try:
        resp = r.json()
    except Exception:
        resp = r.text
    shown_headers = {k: v for k, v in hdrs.items() if k.lower() != "authorization"}
    if token:
        shown_headers["Authorization"] = f"Bearer <{token['who']} access token>"
    entry = {
        "request": {
            "method": method,
            "path": "/api/v1" + path,
            "headers": shown_headers,
            "body": shown_body,
        },
        "response": {"status": r.status_code, "body": resp},
    }
    if note:
        entry["note"] = note
    (OUT / f"{counter[0]:02d}-{name}.json").write_text(
        json.dumps(entry, indent=2, default=str) + "\n"
    )
    print(f"{counter[0]:02d} {name}: {r.status_code}")
    return r


def webhook(name, event, data, signature=None, note=None):
    body = json.dumps({"event": event, "data": data}).encode()
    sig = signature or hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha512).hexdigest()
    return _wh(name, body, sig, note)


def _wh(name, body, sig, note):
    counter[0] += 1
    r = requests.post(
        BASE + "/payments/webhook",
        data=body,
        timeout=30,
        headers={"x-paystack-signature": sig, "content-type": "application/json"},
    )
    entry = {
        "request": {
            "method": "POST",
            "path": "/api/v1/payments/webhook",
            "headers": {
                "x-paystack-signature": (
                    "<hmac-sha512(PAYSTACK_WEBHOOK_SECRET, raw body)>"
                    if sig != "invalid"
                    else "invalid"
                ),
                "content-type": "application/json",
            },
            "body": json.loads(body),
        },
        "response": {"status": r.status_code, "body": r.json()},
    }
    if note:
        entry["note"] = note
    (OUT / f"{counter[0]:02d}-{name}.json").write_text(json.dumps(entry, indent=2) + "\n")
    print(f"{counter[0]:02d} {name}: {r.status_code}")
    return r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()

    paystack = HTTPServer(("127.0.0.1", PAYSTACK_PORT), FakePaystack)
    threading.Thread(target=paystack.serve_forever, daemon=True).start()
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(APP_PORT),
            "--log-level",
            "warning",
        ],
        env=os.environ.copy(),
    )
    try:
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{APP_PORT}/health", timeout=1).ok:
                    break
            except Exception:
                time.sleep(0.5)

        from app.core.security import create_access_token
        from app.db.models import (
            Booking,
            BookingStatus,
            Payment,
            PaymentStatus,
            Service,
            User,
            UserType,
        )
        from app.db.session import SessionLocal
        from app.utils.commission import calculate_artisan_amount, calculate_platform_fee

        db = SessionLocal()
        # scratch DB only (guarded above): start every capture run from empty tables
        tables = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename NOT IN ('alembic_version','spatial_ref_sys')"
                )
            ).all()
        ]
        db.execute(
            text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE")
        )
        db.commit()
        now = datetime.now(timezone.utc)

        def mk_user(kind, n):
            u = User(
                id=uuid.uuid4(),
                full_name=f"Placeholder {kind.value.title()}",
                email=f"{kind.value}{n}@example.com",
                phone_number=f"080000000{n}",
                user_type=kind,
                is_email_verified=True,
                is_active=True,
                registration_completed=True,
            )
            db.add(u)
            db.flush()
            return u

        artisan, client_user = mk_user(UserType.ARTISAN, 1), mk_user(UserType.CLIENT, 2)
        service = Service(name="Placeholder Plumbing")
        db.add(service)
        db.flush()

        def mk_booking(amount, status, ref, confirmed=False):
            b = Booking(
                booking_reference=ref,
                customer_id=client_user.id,
                artisan_id=artisan.id,
                service_id=service.id,
                job_date=now + timedelta(days=1),
                job_location="SRID=4326;POINT(3.3792 6.5244)",
                job_address="1 Placeholder Street, Lagos",
                budget_min=Decimal("1000"),
                budget_max=Decimal("100000"),
                agreed_amount=Decimal(amount),
                status=status,
                accepted_at=now,
                completion_confirmed_by_client_at=now if confirmed else None,
                completion_confirmation_deadline_at=now - timedelta(hours=1) if confirmed else None,
            )
            db.add(b)
            db.flush()
            return b

        def mk_payment(booking, amount, ref, status, paid_days_ago=None):
            g = Decimal(amount)
            p = Payment(
                payment_reference=ref,
                booking_id=booking.id,
                amount=g,
                platform_fee=calculate_platform_fee(g, Decimal("10")),
                artisan_amount=calculate_artisan_amount(g, Decimal("10")),
                currency="NGN",
                status=status,
                customer_email=client_user.email,
                customer_name=client_user.full_name,
                paid_at=now - timedelta(days=paid_days_ago) if paid_days_ago else None,
            )
            db.add(p)
            db.flush()
            return p

        for amount, ref, days in (
            ("10000.00", "PAY-CAP-1", 3),
            ("20000.00", "PAY-CAP-2", 2),
            ("30000.00", "PAY-CAP-3", 1),
        ):
            b = mk_booking(amount, BookingStatus.COMPLETED, f"BK-CAP-{days}", confirmed=True)
            mk_payment(b, amount, ref, PaymentStatus.SUCCESS, days)
        live = mk_booking("15000.00", BookingStatus.ACCEPTED, "BK-CAP-LIVE")
        mismatch_b = mk_booking("5000.00", BookingStatus.ACCEPTED, "BK-CAP-MISMATCH")
        mismatch_p = mk_payment(mismatch_b, "5000.00", "PAY-CAP-MISMATCH", PaymentStatus.PENDING)
        db.commit()
        live_id, mismatch_ref = live.id, mismatch_p.payment_reference
        artisan_tok = {"value": create_access_token({"sub": str(artisan.id)}), "who": "artisan"}
        client_tok = {"value": create_access_token({"sub": str(client_user.id)}), "who": "client"}

        # 1. client pays: initialize -> webhook (non-enum channel) -> redelivery -> verify
        r = capture(
            "initialize-payment",
            "POST",
            "/payments/initialize",
            token=client_tok,
            json_body={"booking_id": live_id},
        )
        ref = r.json()["payment_reference"]
        data = {
            "reference": ref,
            "status": "success",
            "amount": 1_500_000,
            "currency": "NGN",
            "channel": "mobile_money",
        }
        webhook(
            "webhook-charge-success-mobile-money",
            "charge.success",
            data,
            note="channel 'mobile_money' used to crash the old webhook (not in the PaymentMethod enum)",
        )
        webhook(
            "webhook-charge-success-redelivery",
            "charge.success",
            data,
            note="Paystack retry: idempotent no-op",
        )
        capture("verify-after-webhook", "GET", f"/payments/verify/{ref}", token=client_tok)
        webhook(
            "webhook-charge-success-amount-mismatch",
            "charge.success",
            {
                "reference": mismatch_ref,
                "status": "success",
                "amount": 100,
                "currency": "NGN",
                "channel": "card",
            },
            note="amount differs from the stored payment: NOT settled (payment stays pending)",
        )
        webhook("webhook-bad-signature", "charge.success", data, signature="invalid")

        # 2. wallet before payout
        capture("wallet-balance-before", "GET", "/wallet/balance", token=artisan_tok)
        capture("wallet-earnings", "GET", "/wallet/earnings", token=artisan_tok)
        capture("wallet-stats-before", "GET", "/wallet/stats", token=artisan_tok)

        # 3. payout request: actual < requested, idempotent replay, no-fit, minimum, role
        body = {
            "amount": "20000.00",
            "account_number": "0000000000",
            "bank_code": "057",
            "account_name": "Jane Placeholder",
        }
        idem = {"Idempotency-Key": "capture-key-0001"}
        r = capture(
            "payout-request",
            "POST",
            "/wallet/payout/request",
            token=artisan_tok,
            json_body=body,
            headers=idem,
            note="requested 20000, only the 9000 payment fits as a whole payment: the response states the ACTUAL amount",
        )
        w1_ref = r.json()["payout_reference"]
        capture(
            "payout-request-replay",
            "POST",
            "/wallet/payout/request",
            token=artisan_tok,
            json_body=body,
            headers=idem,
            note="same Idempotency-Key (double tap): same withdrawal, no second transfer",
        )
        capture(
            "payout-request-no-fit",
            "POST",
            "/wallet/payout/request",
            token=artisan_tok,
            json_body=dict(body, amount="5000.00"),
        )
        capture(
            "payout-request-below-minimum",
            "POST",
            "/wallet/payout/request",
            token=artisan_tok,
            json_body=dict(body, amount="1000.00"),
        )
        capture(
            "payout-request-as-client",
            "POST",
            "/wallet/payout/request",
            token=client_tok,
            json_body=body,
        )
        capture("wallet-balance-processing", "GET", "/wallet/balance", token=artisan_tok)
        capture("wallet-payouts-processing", "GET", "/wallet/payouts", token=artisan_tok)

        # 4. transfer.success
        webhook(
            "webhook-transfer-success",
            "transfer.success",
            {
                "reference": w1_ref,
                "transfer_code": "TRF_placeholder1",
                "amount": 900_000,
                "status": "success",
            },
        )
        webhook(
            "webhook-transfer-success-redelivery",
            "transfer.success",
            {
                "reference": w1_ref,
                "transfer_code": "TRF_placeholder1",
                "amount": 900_000,
                "status": "success",
            },
        )
        capture("wallet-balance-after-success", "GET", "/wallet/balance", token=artisan_tok)
        capture("wallet-payouts-after-success", "GET", "/wallet/payouts", token=artisan_tok)
        capture("wallet-stats-after", "GET", "/wallet/stats", token=artisan_tok)

        # 5. a failed transfer returns the money
        r = capture(
            "payout-request-second",
            "POST",
            "/wallet/payout/request",
            token=artisan_tok,
            json_body=dict(body, amount="18000.00"),
            headers={"Idempotency-Key": "capture-key-0002"},
        )
        w2_ref = r.json()["payout_reference"]
        webhook(
            "webhook-transfer-failed",
            "transfer.failed",
            {
                "reference": w2_ref,
                "transfer_code": "TRF_placeholder2",
                "amount": 1_800_000,
                "reason": "Recipient bank unavailable",
            },
        )
        capture("wallet-balance-after-failed", "GET", "/wallet/balance", token=artisan_tok)
        capture("wallet-payouts-after-failed", "GET", "/wallet/payouts", token=artisan_tok)

        # 6. release is disabled
        pid = db.query(Payment).filter(Payment.payment_reference == "PAY-CAP-1").one().id
        capture(
            "release-payment-disabled",
            "POST",
            f"/payments/{pid}/release",
            token=artisan_tok,
            json_body={},
        )
    finally:
        server.terminate()
        paystack.shutdown()


if __name__ == "__main__":
    main()
