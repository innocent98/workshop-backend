"""
Run the real app for the account-deletion capture walk-through (scratch DB, fake dev data).
Only stand-in: Google/Firebase token verification (no Firebase credentials here), played by
POST /__stub/google which registers claims for a token string. Everything else is the real code
path; the Google re-auth round trip is therefore NOT VERIFIED LIVE against Firebase.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from app.api.v1.endpoints import auth as auth_endpoints  # noqa: E402
from app.main import app  # noqa: E402

CLAIMS: dict = {}


def fake_verify(token: str) -> dict:
    return CLAIMS[token]


auth_endpoints.verify_google_claims = fake_verify


@app.post("/__stub/google")
async def stub_google(request: Request):
    data = await request.json()
    CLAIMS[data["token"]] = data["claims"]
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8012, log_level="warning")
