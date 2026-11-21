"""
Characterization tests that pin behaviour the dependency-security bump must not change:
JWT issue/decode/expiry, JSON bodies without a Content-Type header, and multipart image
uploads through Pillow. They pass on the pre-bump stack too (fastapi 0.115 / starlette 0.38 /
pillow 10 / python-jose 3.3) and must keep passing after upgrades.
"""

import base64
import io
import json
import os
from datetime import timedelta

import pytest
from jose import jwt
from PIL import Image

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, get_password_hash
from tests.admin.conftest import auth, make_user


@pytest.fixture(autouse=True)
def _fresh_login_limiter():
    # /auth/login is limited to 5 per 15 min per IP in Redis; keep reruns independent.
    limiter.reset()


ME = "/api/v1/profiles/customers/me"
PICTURE = "/api/v1/profiles/me/profile-picture"


def _b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --------------------------------------------------------------------------- JWT


def test_valid_token_is_decoded_and_authenticates(client, db):
    user = make_user(db)
    r = client.get(ME, headers=auth(user))
    assert r.status_code == 200
    assert r.json()["id"] == str(user.id)


def test_token_carries_sub_and_integer_exp():
    token = create_access_token({"sub": "abc"}, expires_delta=timedelta(minutes=5))
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert claims["sub"] == "abc"
    assert isinstance(claims["exp"], int)


def test_expired_token_is_rejected(client, db):
    user = make_user(db)
    token = create_access_token({"sub": str(user.id)}, expires_delta=timedelta(seconds=-30))
    r = client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Could not validate credentials"


def test_token_signed_with_other_secret_is_rejected(client, db):
    user = make_user(db)
    forged = jwt.encode({"sub": str(user.id)}, "not-the-secret", algorithm=settings.ALGORITHM)
    r = client.get(ME, headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_unsigned_alg_none_token_is_rejected(client, db):
    user = make_user(db)
    unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': str(user.id)})}."
    r = client.get(ME, headers={"Authorization": f"Bearer {unsigned}"})
    assert r.status_code == 401


def test_token_with_other_hmac_algorithm_is_rejected(client, db):
    user = make_user(db)
    other = jwt.encode({"sub": str(user.id)}, settings.SECRET_KEY, algorithm="HS512")
    r = client.get(ME, headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 401


def test_missing_authorization_header_is_403_not_401(client):
    # FastAPI >= 0.122 would answer 401 with the stock HTTPBearer; the API has always said 403.
    r = client.get(ME)
    assert r.status_code == 403
    assert r.json() == {"detail": "Not authenticated"}


def test_non_bearer_authorization_scheme_is_403(client):
    r = client.get(ME, headers={"Authorization": "Basic abc"})
    assert r.status_code == 403
    assert r.json() == {"detail": "Invalid authentication credentials"}


def test_garbage_bearer_token_is_rejected(client):
    r = client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


# ------------------------------------------------------------- request parsing


def test_login_accepts_json_body_without_content_type_header(client, db):
    # Mobile/HTTP clients that omit Content-Type must keep working: FastAPI >= 0.132 rejects
    # these unless FastAPI(strict_content_type=False) is set in app/main.py.
    user = make_user(db, email="nocontenttype@example.com")
    user.hashed_password = get_password_hash("Passw0rd!x")
    db.commit()
    body = json.dumps({"email": "nocontenttype@example.com", "password": "Passw0rd!x"})
    r = client.post("/api/v1/auth/login", content=body)
    assert r.status_code == 200, r.text
    claims = jwt.decode(r.json()["token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert claims["sub"] == str(user.id)


def test_login_with_json_content_type_still_works(client, db):
    user = make_user(db, email="withcontenttype@example.com")
    user.hashed_password = get_password_hash("Passw0rd!x")
    db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "withcontenttype@example.com", "password": "Passw0rd!x"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "withcontenttype@example.com"


# ------------------------------------------------------------ image uploads


def _image_bytes(mode: str, fmt: str, size=(1500, 1200)) -> bytes:
    colour = {"RGBA": (10, 120, 200, 128), "RGB": (10, 120, 200), "P": 5}[mode]
    img = Image.new(mode, size, colour)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def local_uploads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "USE_CLOUDINARY", False)
    return tmp_path / "uploads" / "profile_pictures"


@pytest.mark.parametrize(
    "mode,fmt,name,mime",
    [
        ("RGBA", "PNG", "avatar.png", "image/png"),
        ("RGB", "JPEG", "avatar.jpg", "image/jpeg"),
        ("P", "GIF", "avatar.gif", "image/gif"),
    ],
)
def test_profile_picture_multipart_upload_is_resized_and_stored(
    client, db, local_uploads, mode, fmt, name, mime
):
    user = make_user(db)
    r = client.put(
        PICTURE,
        headers=auth(user),
        files={"profile_picture": (name, _image_bytes(mode, fmt), mime)},
    )
    assert r.status_code == 200, r.text
    url = r.json()["profile_picture_url"]
    assert url.startswith("/static/profile_pictures/")
    stored = local_uploads / os.path.basename(url)
    assert stored.exists()
    with Image.open(stored) as img:
        assert max(img.size) <= 1080
    db.refresh(user)
    assert user.profile_picture_url == url


def test_profile_picture_upload_requires_auth(client, local_uploads):
    r = client.put(
        PICTURE, files={"profile_picture": ("a.png", _image_bytes("RGB", "PNG"), "image/png")}
    )
    assert r.status_code == 403


def test_corrupt_image_upload_is_a_400(client, db, local_uploads):
    user = make_user(db)
    r = client.put(
        PICTURE,
        headers=auth(user),
        files={"profile_picture": ("fake.png", b"definitely not an image", "image/png")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid image file or corrupted image"


def test_non_image_extension_upload_is_a_400(client, db, local_uploads):
    user = make_user(db)
    r = client.put(
        PICTURE,
        headers=auth(user),
        files={"profile_picture": ("evil.exe", _image_bytes("RGB", "PNG"), "image/png")},
    )
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Invalid file type")
