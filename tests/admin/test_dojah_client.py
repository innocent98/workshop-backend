"""Dojah client tests: httpx is mocked at the TRANSPORT layer, so the real request building,
retry and parsing code runs; nothing touches the network."""

import httpx
import pytest

from app.core.config import settings
from app.integrations.dojah import client as client_mod
from app.integrations.dojah.client import (
    PROD_HOST,
    SANDBOX_HOST,
    DojahClient,
    DojahError,
    get_dojah_client,
    resolve_base_url,
)

REF = "WC-NIN-0123456789abcdef"
NIN_FULL = "12345678917"  # placeholder, not a real NIN


def payload(status="Completed", gov=True, selfie=True, vtype="NIN", nin=NIN_FULL, with_nin=True):
    # gov/selfie are passed through untouched so tests can feed strings like "false"
    record = {"entity": {"first_name": "Jane", "last_name": "Doe", "date_of_birth": "01-Jan-1990"}}
    if with_nin:
        record["entity"]["nin"] = nin
    return {
        "entity": {
            "reference_id": REF,
            "verification_status": status,
            "verification_type": vtype,
            "data": {
                "government_data": {"status": gov, "data": {vtype.lower(): record}},
                "selfie": {"status": selfie, "message": "Successfully validated your liveness"},
            },
        }
    }


@pytest.fixture(autouse=True)
def dojah_settings(monkeypatch):
    monkeypatch.setattr(settings, "DOJAH_API_KEY", "secret-key-x")
    monkeypatch.setattr(settings, "DOJAH_APP_ID", "app-id-x")
    monkeypatch.setattr(settings, "DOJAH_ENVIRONMENT", "sandbox")
    monkeypatch.setattr(settings, "DOJAH_BASE_URL", PROD_HOST)


def make(handler):
    return DojahClient(transport=httpx.MockTransport(handler), backoff=0)


def fetch(handler):
    return make(handler).fetch_verification(REF)


# ------------------------------------------------------------------ request shape


def test_request_shape_and_success():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["method"] = request.method
        return httpx.Response(200, json=payload())

    r = fetch(handler)
    assert seen["method"] == "GET"
    assert seen["url"] == f"{SANDBOX_HOST}/api/v1/kyc/verification?reference_id={REF}"
    assert seen["headers"]["authorization"] == "secret-key-x"  # no "Bearer"
    assert seen["headers"]["appid"] == "app-id-x"
    assert r.status == "success" and r.id_verified and r.selfie_passed
    assert r.provider_reference == REF and r.nin_last4 == "8917"


def test_result_keeps_no_name_dob_or_full_nin():
    r = fetch(lambda req: httpx.Response(200, json=payload()))
    dumped = r.model_dump_json()
    for secret in (NIN_FULL, "Jane", "Doe", "1990"):
        assert secret not in dumped


# --------------------------------------------------------------------------- parse


def test_selfie_failed_and_dojah_failed():
    r = fetch(lambda req: httpx.Response(200, json=payload("Failed", selfie=False)))
    assert r.status == "failed" and r.id_verified and not r.selfie_passed


def test_government_check_failed():
    r = fetch(lambda req: httpx.Response(200, json=payload("Failed", gov=False)))
    assert r.status == "failed" and not r.id_verified


@pytest.mark.parametrize(
    "dojah_status,expected",
    [
        ("Completed", "success"),
        ("Pending", "pending"),
        ("Ongoing", "pending"),
        ("Failed", "failed"),
        ("Abandoned", "failed"),
        ("SomethingNew", "pending"),  # forward compatible: never fail/pass on an unknown status
        ("", "pending"),
    ],
)
def test_status_map(dojah_status, expected):
    r = fetch(lambda req: httpx.Response(200, json=payload(dojah_status)))
    assert r.status == expected


@pytest.mark.parametrize(
    "bad", ["false", "False", "failed", "no", "0", "", 0, 1, None, [], {}, "true"]
)
def test_only_a_real_boolean_true_counts_as_a_pass(bad):
    """bool("false") is True in Python: strings and numbers must never count as a pass."""
    r = fetch(lambda req: httpx.Response(200, json=payload(gov=bad, selfie=True)))
    assert r.id_verified is False
    r = fetch(lambda req: httpx.Response(200, json=payload(gov=True, selfie=bad)))
    assert r.selfie_passed is False


def test_real_true_booleans_pass():
    r = fetch(lambda req: httpx.Response(200, json=payload(gov=True, selfie=True)))
    assert r.id_verified is True and r.selfie_passed is True


@pytest.mark.parametrize("vtype", ["", "BVN", "RC-NUMBER", "NIN-SLIP", "nin "])
def test_verification_type_must_be_exactly_nin(vtype):
    body = payload(vtype="NIN")
    body["entity"]["verification_type"] = vtype  # records still contain a "nin" block
    r = fetch(lambda req: httpx.Response(200, json=body))
    assert r.id_verified is False  # no "nin in records" fallback


def test_missing_verification_type_is_not_a_nin_pass():
    body = payload()
    del body["entity"]["verification_type"]
    assert fetch(lambda req: httpx.Response(200, json=body)).id_verified is False


def test_lowercase_nin_type_is_accepted():
    body = payload()
    body["entity"]["verification_type"] = "nin"
    assert fetch(lambda req: httpx.Response(200, json=body)).id_verified is True


def test_bvn_verification_is_not_accepted_as_nin():
    r = fetch(lambda req: httpx.Response(200, json=payload(vtype="BVN")))
    assert r.id_verified is False  # a mis-pointed BVN widget must never verify an artisan


def test_nin_missing_from_record_means_no_last4():
    r = fetch(lambda req: httpx.Response(200, json=payload(with_nin=False)))
    assert r.nin_last4 is None and r.id_verified


def test_garbage_payloads_do_not_crash():
    for body in ({}, {"entity": None}, {"entity": {"data": None}}, []):
        r = fetch(lambda req, b=body: httpx.Response(200, json=b))
        assert r.status == "pending" and not r.id_verified


# --------------------------------------------------------------------------- retry


def test_retries_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=payload())

    assert fetch(handler).status == "success"
    assert len(calls) == 3


def test_gives_up_after_three_attempts():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(DojahError):
        fetch(handler)
    assert len(calls) == 3


@pytest.mark.parametrize("status", [400, 401, 402, 404, 429])
def test_4xx_is_not_retried(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(DojahError):
        fetch(handler)
    assert len(calls) == 1


def test_transport_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("boom")

    with pytest.raises(DojahError):
        fetch(handler)
    assert len(calls) == 3


def test_timeout_is_flagged_so_the_endpoint_can_answer_pending():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(DojahError) as exc:
        fetch(handler)
    assert exc.value.timed_out is True

    with pytest.raises(DojahError) as exc2:
        fetch(lambda req: httpx.Response(500))
    assert exc2.value.timed_out is False


def test_max_attempts_and_timeout_are_caller_controlled():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(DojahError):
        make(handler).fetch_verification(REF, timeout=1.0, max_attempts=1)
    assert len(calls) == 1


def test_non_json_body_is_a_provider_error_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=b"<html>oops</html>")

    with pytest.raises(DojahError):
        fetch(handler)
    assert len(calls) == 1


def test_secrets_and_nin_never_logged(monkeypatch):
    lines = []
    for level in ("info", "warning", "error"):
        monkeypatch.setattr(client_mod.logger, level, lambda m, _l=lines: _l.append(m))

    def handler(request):
        raise httpx.ConnectError(f"boom {NIN_FULL} secret-key-x")

    with pytest.raises(DojahError):
        fetch(handler)
    fetch(lambda req: httpx.Response(200, json=payload()))
    blob = " ".join(lines)
    assert lines and NIN_FULL not in blob and "secret-key-x" not in blob


# ------------------------------------------------------------------ config / host


def test_environment_picks_host(monkeypatch):
    assert resolve_base_url() == SANDBOX_HOST
    monkeypatch.setattr(settings, "DOJAH_ENVIRONMENT", "production")
    assert resolve_base_url() == PROD_HOST
    monkeypatch.setattr(settings, "DOJAH_BASE_URL", "https://proxy.internal/")
    assert resolve_base_url() == "https://proxy.internal"  # explicit override wins


def test_factory_requires_api_key(monkeypatch):
    assert isinstance(get_dojah_client(), DojahClient)
    monkeypatch.setattr(settings, "DOJAH_API_KEY", None)
    assert get_dojah_client() is None
    with pytest.raises(RuntimeError):
        DojahClient()
