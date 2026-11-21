"""
Run the real app for the reviews / response-time capture walk-through (scratch DB, fake dev data).
No stand-ins: every request in the walk goes through the real code paths. The server is started with
REVIEW_REPORTS_PER_USER_PER_HOUR=2 so the per-user report cap can be shown with three reviews.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8013, log_level="warning")
