# SOP: Dependency security bump (clear fixable HIGH/CRITICAL CVEs from the Trivy image scan)

**What shipped:** `pyproject.toml` + `poetry.lock` bumped so the Python dependencies carry no fixable HIGH or
CRITICAL advisory, plus the two small code changes needed to keep the API behaving exactly as before, the Dockerfile `setuptools` upgrade, and Trivy switched back to blocking.
**PR:** `fix/dependency-security-bump` → `main` (number in the PR). Not merged by the author.

## Why

The Trivy image scan added in the deploy pipeline (PR #10) found real HIGH/CRITICAL CVEs in the Python deps
(table in the PR #10 notes). Trivy was made report-only so the pipeline could merge; after this PR merges the
lead flips it back to `exit-code: '1'`. Goal: zero **fixable** HIGH/CRITICAL, with no feature change.

## Versions (before → after)

Direct deps are in `pyproject.toml`; the rest are transitive and only move in `poetry.lock`.
"Fixed in" is from the OSV advisory database (queried per version), which is what picked each target.

| Package | Before | After | Direct? | Clears |
|---|---|---|---|---|
| fastapi | 0.115.0 | **0.136.3** | direct | pulls starlette 1.x (0.115 caps starlette < 0.39) |
| starlette | 0.38.6 | **1.3.1** | transitive | GHSA-f96h (multipart DoS), GHSA-82w8 (`request.form()` limits ignored, HIGH, fixed only in 1.3.1), StaticFiles UNC SSRF, Host-header poisoning |
| pillow | 10.4.0 | **13.0.0** | direct | 38 advisories; 13.0.0 is the only release with none left |
| python-multipart | 0.0.20 | **0.0.31** | direct | 3 HIGH + 3 LOW (0.0.31 clears all) |
| python-jose | 3.3.0 | **3.5.0** | direct | the 3.4.0 fix for CVE-2024-33663; **3.4.0 itself was not installable** (it pins `pyasn1<0.5`, which blocks the pyasn1 fix) |
| PyJWT | 2.11.0 | 2.15.0 | transitive (firebase-admin) | 6 advisories incl. CRITICAL (2.14.0 would clear HIGH/CRITICAL; 2.15.0 also clears two MODERATE) |
| anyio | 4.12.1 | 4.14.2 | transitive | CRITICAL |
| certifi | 2026.1.4 | 2026.10.18 | transitive | CRITICAL |
| cryptography | 46.0.3 | 50.0.0 | transitive | 4 HIGH; 50.0.0 is the first release that clears all (PKCS#7, verifier, bundled OpenSSL) |
| urllib3 | 2.6.3 | 2.8.0 | transitive | 4 HIGH |
| pyasn1 | 0.6.2 | 0.6.5 | transitive | 8 HIGH |
| mako | 1.3.10 | 1.3.12 | transitive (alembic) | 2 HIGH (one MODERATE, Windows-only, needs 1.4.2: not taken) |
| dnspython | 2.8.0 | 2.9.2 | transitive | 2 HIGH |
| httplib2 | 0.31.2 | 0.32.0 | transitive | HIGH |
| msgpack | 1.1.2 | 1.2.3 | transitive | 2 HIGH |
| lxml | 6.0.2 | 6.1.0 | transitive (emails/premailer) | HIGH `iterparse()` default config. Trivy printed "no fix"; OSV lists 6.1.0 as fixed, so it is bumped anyway |
| annotated-doc | - | 0.0.7 | new transitive | new FastAPI dependency |

Method: temporary exact pins for the transitive packages, `poetry lock`, then removed the pins and re-locked (Poetry
2.2.1 keeps locked versions), so `pyproject.toml` only carries the four direct bumps. Resolved versions verified
unchanged after the pins were removed.

### Base-image findings (fixed in the Dockerfile, not the lock)

| Finding | Why | Fix |
|---|---|---|
| `jaraco.context` 5.3.0 and `wheel` 0.45.1 (both HIGH) | both are **vendored inside `setuptools`** (79.0.1 in the base image, `setuptools/_vendor/...`), not in our lock. CI's first Trivy scan of this PR reported exactly these two as the only remaining findings (`Total: 2`). setuptools >= 80.10.2 vendors jaraco.context 6.1.0 and wheel 0.46.3 | `RUN pip install --no-cache-dir -U "setuptools>=80.10.2"` in **both** Dockerfile stages. The runtime stage needs its own: its `COPY` from the builder only overlays files, so the base image's old vendored `*.dist-info` directories would otherwise survive |
| `zlib1g` (HIGH, OS) | handled by `apt-get upgrade` in the runtime stage | none |

### Accepted: unfixed, no upstream release (Trivy hides these via `ignore-unfixed`)

| Package | Advisory | Why accepted |
|---|---|---|
| python-jose 3.5.0 (latest) | GHSA-3qf3-8w2g-rqmx CRITICAL: HS256 verification accepts a DER-encoded public key as the HMAC secret when `algorithms` is not restricted | Not exploitable here: `HS256` with `settings.SECRET_KEY` (a symmetric secret), and `jwt.decode(..., algorithms=[settings.ALGORITHM])` pins the algorithm. No public key is involved. `tests/test_dependency_upgrade_guards.py` asserts alg-none, other-secret and HS512 tokens are rejected. python-jose is unmaintained: moving to PyJWT (already installed) is the durable fix, see follow-ups |
| ecdsa 0.19.1 | GHSA-wj6h Minerva timing attack (HIGH), no fix | transitive of python-jose; we sign and verify HS256 only, never ECDSA |

Because Trivy runs with `ignore-unfixed: true`, these two are invisible to the blocking scan today. The moment upstream ships a fix they surface and fail `image-check`, which forces the bump (or the PyJWT migration below).

## Code changes (behaviour preservation)

Both found by comparing the old stack (fastapi 0.115 / starlette 0.38) with the new one on the same requests.

| Change | File | Why |
|---|---|---|
| `FastAPI(strict_content_type=False)` | `app/main.py` | FastAPI >= 0.132 rejects a JSON body that has no JSON `Content-Type` (422). The old stack parsed it. A client that omits the header would have broken, so strictness is switched off. |
| `HTTPBearer403` subclass used for `security` | `app/api/deps.py` | FastAPI >= 0.122 changed a missing/non-Bearer `Authorization` header from **403** to **401** (and added `WWW-Authenticate`). The API, the FE guides (`fe-integration-guide-reviews-response-time.md`: "403 not 401") and the mobile client's `auth_interceptor` (which treats 401, and a 403 that looks like an auth failure, as an auth failure) were built against 403. The subclass returns the old status and detail strings exactly (`"Not authenticated"`, `"Invalid authentication credentials"`). |

## Behaviour that does change (cannot be switched off upstream)

| Change | Source | Effect |
|---|---|---|
| Empty-string `Form` values are treated as missing | FastAPI 0.123.2 | A blank portfolio `title` or `description` is now stored as NULL instead of `""` (the client already shows "Untitled project"; harmless). `bio` is unaffected: the Flutter app never sends it and `if bio:` in `app/services/auth.py` already ignored `""`. `display_order=""` becomes `0`. A required `Form(...)` sent as `""` is now 422 "Field required" instead of reaching the handler: `POST /bookings/{id}/progress-logs` with an empty `description` returns 422 (was 400 "at least 5 characters"). An empty optional file part is now accepted (was 422). |
| OpenAPI schema | FastAPI 0.129 / 0.13x | `UploadFile` is now `contentMediaType: application/octet-stream` instead of `format: binary`; `ValidationError` schema lists `ctx` and `input`. Paths (88) and schemas (126) are unchanged in count. Docs only: runtime 422 bodies already carried `input`/`ctx`. |

## What's involved

| Area | Files |
|---|---|
| Dependencies | `pyproject.toml` (fastapi, python-multipart, python-jose, pillow), `poetry.lock` (regenerated with Poetry 2.2.1) |
| Dockerfile / CI | `Dockerfile` (setuptools upgrade, both stages), `.github/workflows/ci.yml` (Trivy `exit-code: '1'`, job renamed `Image builds (Trivy)`, TEMPORARY labels removed), `docs/sop/deploy-pipeline.md`, `docs/deployment/OWNER-SETUP-CHECKLIST.md`, `docs/deployment/CICD_PIPELINE.md` |
| Code | `app/main.py` (`strict_content_type=False`), `app/api/deps.py` (`HTTPBearer403`) |
| Tests | `tests/test_dependency_upgrade_guards.py` (17 characterization tests, below) |
| Not touched | migrations (no schema change), Pillow/jose/multipart call sites (no API they use was removed) |

Pillow 13 removals (`Image._show`, `Image.Image.get_child_images`, I-mode PNG save, `fromarray` mode) do not touch
`app/utils/file_upload.py`, which uses `Image.open/new/convert/split/paste/thumbnail(Image.Resampling.LANCZOS)/save`.
python-jose is used only for `jwt.encode`, `jwt.decode`, `JWTError` (`app/core/security.py`, `app/api/deps.py`).
Starlette is used only for `BaseHTTPMiddleware` and `run_in_threadpool`, both still present in 1.x.

## Verification

Run locally with a scratch `postgis/postgis:15-3.4` container and a throwaway Redis, both removed afterwards.
Only black/isort/flake8 and the named test files, never the full suite (CI is the authority).

| Check | Result |
|---|---|
| Two-sided: 7 named files on the **old** stack (lock from `main`) | 142 passed |
| Same files on the new stack with no code change | 141 passed, 1 failed: JSON-without-Content-Type (the `strict_content_type` regression above) |
| Same files on the new stack with both code changes | 144 passed (127 existing + 17 guards) |
| Guard tests alone on the old stack | 17 passed (they pin pre-bump behaviour) |
| `black --check`, `isort --check-only`, `flake8` on `app tests` (project venv, pinned versions) | clean |
| `app.openapi()` old vs new | same 88 paths / 126 schemas; only the schema changes listed above |
| 8 error-shape probes old vs new (no header, bad scheme, 422 missing/bad JSON/form, 404, 405, upload 401) | identical after `HTTPBearer403` |
| OSV audit of the new lock (main group) | no HIGH/CRITICAL with a fix; the two accepted items above remain |
| CI `Image builds` Trivy scan on the PR image (head `beccd13`) | `Total: 2 (HIGH: 2, CRITICAL: 0)`: only the setuptools-vendored `jaraco.context` 5.3.0 and `wheel` 0.45.1; every Python package from the lock, and the OS layer, report 0 |

Named files: `tests/test_dependency_upgrade_guards.py`, `tests/api/test_payments_webhook.py` (Paystack raw-body
HMAC), `tests/admin/test_verification.py` and `tests/admin/test_signature.py` (Dojah raw-body HMAC),
`tests/api/test_account_deletion.py` (login, token decode, rate limiter), `tests/test_health.py`,
`tests/test_rate_limit.py`.

What the guard tests pin: token round trip and `sub`/integer `exp`; expired, wrong-secret, alg-none, HS512 and garbage
tokens all 401; missing and non-Bearer header 403; login with and without a JSON `Content-Type`; multipart profile
picture upload (RGBA PNG, JPEG, palette GIF) resized to <= 1080 px and stored; corrupt image and bad extension 400.

## Not verified (honest gaps)

- Google sign-in end to end (needs a Firebase service account and a real Google ID token). `firebase_admin` 6.6 verifies
  ID tokens with google-auth (unchanged), not PyJWT. The only new element is cryptography 50: a probe verified an
  RS256/x509 token on it, but a real Google sign-in has not been tested.
- Cloudinary upload path (needs credentials): only the local-storage branch ran. Pillow output is the same bytes either way.
- Celery worker/beat boot and real task execution on the new stack (imports only).
- Real email rendering through `emails`/`premailer` with lxml 6.1.0.
- The Flutter client was not run against the new backend.

## Operate / roll back

- Deploy is the normal pipeline. No migration, no config or env change.
- Roll back by reverting this PR (restores the previous lock, Dockerfile and report-only Trivy). The two code changes are self-contained.
- Trivy is blocking: a new fixable HIGH/CRITICAL in a dependency or base image now fails `image-check` and therefore the `CI gate`. Fix by bumping the package (or refreshing the base image); do not add a `.trivyignore` entry for something that has a fix.

## Follow-ups

- Replace python-jose with PyJWT in `app/core/security.py` and `app/api/deps.py` (two call sites, PyJWT already
  installed): removes the unfixable CRITICAL advisory and the unmaintained dependency. Needs its own PR and a
  decision on token `exp` handling (`datetime.utcnow()` is deprecated).
- Token header parsing mismatch (pre-existing, not changed here): logout (`app/api/v1/endpoints/auth.py` ~688) and
  account delete (~619) only find the token when the header starts with exactly `Bearer `, while the auth check
  accepts any case. A request sent as `bearer <token>` authenticates but logout does not revoke it. Fix later by
  using `credentials.credentials` from the security dependency.
- Starlette 1.3's `TestClient` emits an httpx deprecation warning in the test run; harmless now, track before the
  next httpx/starlette bump.
- Decide whether to keep `strict_content_type=False` once all clients send `Content-Type: application/json`.
- Consider a Dependabot/`pip-audit` gate so the next advisory is caught outside the image scan.
- Remaining MODERATE advisories (idna, requests, python-dotenv, ecdsa DoS, mako on Windows) are out of this PR's scope.
