"""
Run the real app for the capture walk-through (scratch DB, fake dev data).

Two stand-ins, both at the edge so every line of app code between them is the real code path:
  * Dojah is played at the HTTP TRANSPORT layer (httpx.MockTransport) inside the real DojahClient:
    request building, headers, parsing and status mapping are real, the answers are scripted via
    POST /__stub/dojah (control route that exists only in this capture server).
  * PaystackService.refund / list_refunds are stubbed (a real refund needs a live Paystack transaction);
    POST /__stub/paystack {"mode": "ok"|"timeout"} switches between success and an ambiguous timeout.
Neither Dojah nor Paystack is contacted: those round trips are NOT VERIFIED LIVE.

Usage (env as in docs/sop): python docs/fe-captures/verification-admin/capture_server.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from app.integrations.dojah.client import DojahClient, get_dojah_client  # noqa: E402
from app.main import app  # noqa: E402
from app.services.paystack import PaystackService  # noqa: E402

from app.services.paystack import PaystackError  # noqa: E402

PAYSTACK_MODE = {"mode": "ok"}  # "ok" | "timeout" (ambiguous failure, nothing found on lookup)


def _refund(transaction_reference, **kw):
    if PAYSTACK_MODE["mode"] == "timeout":
        raise PaystackError("Paystack API request failed: ReadTimeout")
    return {"id": 3141592, "status": "pending", "transaction": 0}


PaystackService.refund = staticmethod(_refund)
PaystackService.list_refunds = staticmethod(lambda transaction_reference: [])

SCRIPT: dict = {}  # reference -> (http status, json body)


def dojah_handler(request: httpx.Request) -> httpx.Response:
    status, body = SCRIPT.get(request.url.params["reference_id"], (404, None))
    return httpx.Response(status, json=body) if body is not None else httpx.Response(status)


_transport = httpx.MockTransport(dojah_handler)
app.dependency_overrides[get_dojah_client] = lambda: DojahClient(transport=_transport, backoff=0)


@app.post("/__stub/paystack")
async def stub_paystack(request: Request):
    PAYSTACK_MODE["mode"] = (await request.json())["mode"]
    return {"ok": True}


@app.post("/__stub/dojah")
async def stub_dojah(request: Request):
    data = await request.json()
    SCRIPT[data["reference_id"]] = (data.get("status", 200), data.get("body"))
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8011, log_level="warning")
