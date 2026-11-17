import hashlib
import hmac

from app.core.config import settings
from app.integrations.dojah.signature import verify_dojah_signature


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_and_invalid_signature(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_WEBHOOK_SECRET", "shh")
    body = b'{"reference_id":"WC-NIN-1234567890"}'
    assert verify_dojah_signature(body, sign("shh", body)) is True
    assert verify_dojah_signature(body, sign("shh", body).upper()) is True  # hex case-insensitive
    assert verify_dojah_signature(body, "deadbeef") is False
    assert verify_dojah_signature(body + b" ", sign("shh", body)) is False  # body tampered


def test_wrong_secret_rejected(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_WEBHOOK_SECRET", "shh")
    assert verify_dojah_signature(b"{}", sign("other", b"{}")) is False


def test_fails_closed_without_header_or_secret(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_WEBHOOK_SECRET", "shh")
    assert verify_dojah_signature(b"{}", "") is False
    assert verify_dojah_signature(b"{}", None) is False
    monkeypatch.setattr(settings, "DOJAH_WEBHOOK_SECRET", None)
    assert verify_dojah_signature(b"{}", sign("shh", b"{}")) is False


def test_non_ascii_or_junk_signature_is_rejected_not_an_error(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_WEBHOOK_SECRET", "shh")
    for junk in ("é" * 64, "\u2603", "\x00", " "):
        assert verify_dojah_signature(b"{}", junk) is False
