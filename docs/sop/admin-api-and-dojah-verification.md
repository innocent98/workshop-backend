# SOP: Admin API + Dojah artisan verification

**What shipped:** a minimal, audited admin API (`/api/v1/admin/*`, `users.is_admin` flag) and real artisan
identity verification (NIN + selfie through **Dojah's hosted Identity widget**, confirmed server-side) replacing
the temporary "email verified => artisan verified" rule. PR: <https://github.com/innocent98/workshop-backend/pull/1>.
Frontend contract: [`docs/fe-integration-guide-verification-admin.md`](../fe-integration-guide-verification-admin.md).

## Why

* Disputed bookings (`status=disputed`) had no way out: nothing could release the money to the artisan or refund
  the customer, and nobody but a DB admin could see users/bookings/payments.
* Every artisan was auto-verified on email OTP, so the "verified" badge meant nothing.

## How (decisions and tradeoffs)

### Admin

| Decision | Choice | Rejected alternative / why |
|---|---|---|
| Admin identity | `users.is_admin` boolean; admins log in via normal `/auth/login` | New `UserType.ADMIN`: would touch enums/queries/Flutter. A flag is additive. |
| Guard | `require_admin` in `app/api/deps.py`, applied as a **router-level dependency** so no admin route can be added unguarded | Per-route dependency (easy to forget) |
| First admin | `scripts/create_admin.py` from `FIRST_SUPERUSER_EMAIL/PASSWORD`; idempotent; never prints the password; never overwrites an existing admin's password (`--reset-password` is explicit); **refuses** to promote a pre-existing non-admin account (exit 2) unless `--promote-existing`, which takes the account over (password reset, email marked verified) | Silently promoting an existing user: a pre-registered account with that email would inherit admin (found by the automated security review) |
| Release resolution | sets `completion_confirmed_by_client_at`, clears `completion_disputed_at/_reason`, booking back to `completed`; original dispute fields snapshotted in `dispute_resolutions` | Leaving the dispute flag set: the payout/wallet queries require `disputed_at IS NULL`, so the unchanged payout flow would never unlock |
| Refund resolution | **Intent first, then Paystack** (see "Refund safety" below). Paystack `POST /refund` (`PaystackService.refund`) -> payment `refunded` + `refunded_at`, booking `cancelled` with reason, `refund_status` stored | Calling Paystack inside the same transaction as the state change: a timeout or failed commit after Paystack processed the refund left the booking `disputed`/payment `success`, so `release_to_artisan` could pay out refunded money (found in review) |
| Idempotency | row lock on the booking + `UNIQUE(dispute_resolutions.booking_id)`; same accepted resolution again => 200 `already_resolved:true` without calling Paystack; a different one => 409 | Application-level check only (racy) |
| Refund preconditions | payment must be `success` (funds still held); `released` => 409 | Refunding after release: needs clawback, out of scope |
| Audit | every admin mutation writes `admin_audit_logs` in the same transaction; resolutions also in `dispute_resolutions` | Logs only |

### Refund safety (the refund / release double-spend)

`refund_customer` runs in three steps: (1) under the booking lock, **commit** a `dispute_resolutions` row with
`refund_status='requested'` (the booking stays `disputed`, which also keeps the payout/wallet queries closed);
(2) call Paystack with **no lock held**; (3) in a new transaction mark payment `refunded`, booking `cancelled`, store
Paystack's status. `release_to_artisan` is refused (409 `refund_in_progress`) whenever a refund row exists, unless
Paystack confirmed it `failed`. When the Paystack call errors, the code never assumes "nothing happened": it asks
Paystack (`GET /refund?transaction=`) and adopts an existing non-failed refund; nothing found + a definite 4xx
rejection rolls the intent back (`refund_failed`); anything else keeps the intent (`refund_unconfirmed`, retry
reconciles first). Paystack refunds are asynchronous, so `handle_refund_event` applies `refund.pending|processing|
processed|failed` (never moves backwards; `processed` is final; `failed` puts payment back to `success` and the
booking back to `disputed` so the admin can retry or release). The events are wired into the Paystack
webhook in `payments.py` (`REFUND_WEBHOOK_EVENTS` in `_handle_webhook_event`, signature-checked like every event; an
unknown transaction is acknowledged as `ignored`). A `refund.failed` event is never trusted on its own (it would reopen the dispute and unblock a release): it is ignored when it names a different refund than the one we hold (a late event for an earlier, already-retried refund), and otherwise applied only if Paystack's refund list shows no live refund; if that lookup fails nothing changes. Concurrency (review round 3): a retry from `requested` is refused while the
last attempt's lease (`refund_attempt_at`, 90 s) is fresh (409 `refund_attempt_in_progress`), so attempts do not race
normally; the intent row is **never deleted** (a definite rejection marks it `failed`); `_complete_refund` re-reads
under the booking lock and adopts Paystack's word (also adopting a refund a stale attempt had marked `failed`, and a
`refund.processed|pending|processing` event arriving while the row is `requested|failed` completes the booking too, but
only after Paystack's refund list confirms a live refund matching the event's id; replays are idempotent). If a refund succeeds at Paystack **after the dispute was released** to the artisan, the release is never
overwritten: the call/event returns 409 `refund_conflict` (or is ignored for events), logs critical and writes a
`refund.conflict` audit row for manual reconciliation, because money then went both ways.

### Verification (Dojah hosted widget)

Owner decision: no custom "NIN + selfie upload" endpoint and no fake provider. The mobile app runs Dojah's widget;
the backend never sees the NIN or the selfie.

| Step | Detail |
|---|---|
| `GET .../verification/config` | serves `app_id`, `public_key`, `widget_id` (`DOJAH_NIN_WIDGET_ID`), `environment`, and `configured` |
| `POST .../verification/start` | mints `WC-NIN-<16 hex>` (Dojah requires >= 10 chars), inserts a pending `artisan_verification_records` row, sets profile `pending`. Counts as an attempt (5 per rolling 24h, counted from the records table under a profile row lock). A new start supersedes older pending rows |
| App launches the widget | `DojahKyc.launch(widgetId, referenceId:, email:)` (Dojah Flutter SDK docs) |
| `POST .../confirm` / `GET .../status` / `POST /verification/webhook` | all funnel into `confirm_verification`: fetch `GET {host}/api/v1/kyc/verification?reference_id=` (headers `Authorization: <secret>` without Bearer, `AppId`), re-lock the record after the fetch, idempotent. Confirm is bounded to 12 s and status to 8 s: on timeout the verification stays pending and is reconciled by the poll or webhook |
| Pass rule | Dojah `Completed` **and** `government_data.status` (NIN verified, and the verification type is NIN, not BVN) **and** `selfie.status` (widget's combined liveness + face match). Dojah status map: Completed->success, Pending/Ongoing->pending, Failed/Abandoned->failed, unknown->pending |
| Pass effect | `is_verified=true`, `verified_at`, `verification_status=verified`, `verification_method=dojah`, `verification_reference`, `nin_last4` only if Dojah returns the NIN. Fail effect: `verification_status=failed` + a user-facing `failure_reason` (bad NIN / selfie mismatch / abandoned) |
| Webhook | `POST /api/v1/verification/webhook`, unauthenticated, `x-dojah-signature` = HMAC-SHA256(raw body, per-subscription secret `DOJAH_WEBHOOK_SECRET`), constant-time compare, fails closed. The payload is **not trusted**: only `reference_id` is read and the result is re-fetched from Dojah. Unknown/malformed => 200 (no endless retries); Dojah unreachable => 502 so Dojah retries |
| Admin override wins | an admin verify/reject (`verification_method=admin`) is never overwritten by a late Dojah result; a profile that is already verified is not touched; an admin-rejected artisan can start again |
| Stored data | flags + `nin_last4` (only if returned) + references. Never the NIN, names, DOB or images |
| Grandfathering | the migration sets `verification_status='verified'`, `verification_method='legacy'` where `is_verified` is true |
| Unconfigured server | `start` returns 503 `verification_unavailable`; `config` returns `configured:false`. There is no fake provider anywhere |
| Strict parsing | a pass needs `government_data.status is True`, `selfie.status is True` (never `bool()` of a string such as `"false"`) and `verification_type` exactly `NIN` (no "a nin block exists" fallback). NOT verified that real Dojah always sends `verification_type: "NIN"`: if it does not, every artisan would fail verification; check on first live run |
| Threadpool, not the event loop | `start`/`confirm`/`status` are plain `def` (FastAPI threadpool) with a **sync** httpx client, because SQLAlchemy and Dojah calls block. Dojah calls are bounded (confirm 6 s x2 attempts, status 4 s x1); a timeout leaves the verification pending and `confirm` answers 200 `pending` (poll `status`). The webhook is `async` only to read the raw body, then runs the work via `run_in_threadpool` |
| Signature compare | compares bytes inside try/except, so a junk or non-ASCII `x-dojah-signature` is a 401, not a 500 |
| No new dependency | retry is a 3-attempt exponential loop in `client.py` (5xx and transport errors only), instead of adding `tenacity` to `poetry.lock` |

Structure follows the owner's Timpbills integration (`app/integrations/dojah/{client,schemas,signature}.py`, KYC
service/endpoints, records table). **That integration was only a test and never ran in production**, so every
request/response detail was checked against Dojah's docs instead:

* get verification: <https://docs.dojah.io/api-reference/verifications/get-verification.md>
* webhook signature: <https://docs.dojah.io/api-reference/core-concepts/webhooks-signatures.md>
* Flutter widget: <https://docs.dojah.io/api-reference/widget-sdks/flutter.md>
* environments: <https://docs.dojah.io/api-reference/get-started/environments.md>

**Never exercised live from this repo:** the Dojah call itself, the nested `entity.data.government_data` / `selfie`
response parsing (docs sample elides it; shape taken from the Timpbills notes), whether the widget result contains the
NIN (hence `nin_last4` may stay null), the webhook delivery, and sandbox host behaviour. Tests mock httpx at the
transport layer only. Check all of these on first use with real keys.

Note on the earlier draft: a first version of this PR had a multipart NIN + selfie endpoint with a deterministic fake
provider. It was replaced by the widget flow on the owner's decision; no trace of it remains in the code.

## What's involved

| Area | Files |
|---|---|
| Models / migration | `app/db/models/{user,artisan_profile,admin,verification_record}.py`, `alembic/versions/b8e1c4a7d2f3_add_admin_and_artisan_verification.py` (down_revision `c8a1d2e3f4b5`, the payments withdrawals migration: single linear head) |
| Guard | `app/api/deps.py` (`require_admin`) |
| Admin API | `app/api/v1/endpoints/admin.py`, `app/services/admin.py`, `app/schemas/admin.py`, mounted in `app/api/v1/api.py` |
| Refund | `app/services/paystack.py` (`PaystackService.refund`) |
| Dojah | `app/integrations/dojah/{client,schemas,signature}.py`, `app/services/artisan_verification.py`, `app/schemas/verification.py`, `app/api/v1/endpoints/artisan_verification.py` (`router` at `/profiles/artisans/me/verification`, `webhook_router` at `/verification`) |
| Removed | auto-verify in `app/services/auth.py` (OTP verification still creates the empty profile) |
| Config | `app/core/config.py` (`DOJAH_*`, `VERIFICATION_*`), `.env.example` placeholders |
| Script | `scripts/create_admin.py` |
| Tests | `tests/admin/` (needs Postgres+PostGIS from `DATABASE_URL`; refuses to run unless the DB name contains `test`) |

## Verification

* `tests/admin/` (147 tests, scratch PostGIS 15): non-admin/artisan/anonymous 403 on every admin route, `page_size`
  cap, filters, LIKE-wildcard escaping, dispute release, refund with a faked Paystack, **refund safety** (intent committed before the Paystack call, timeout
  reconciled to an existing refund, unconfirmed refund blocks release, retry, definite rejection rolls back, commit
  failure after Paystack success cannot lead to a release, `refund.*` events, `PaystackService.refund/list_refunds`),
  idempotent/conflicting resolution, no duplicate notifications, verify/reject + audit rows,
  `create_admin.py` idempotency and the refuse/promote rules; Dojah client with httpx mocked at the **transport**
  layer (request URL/query/headers incl. no `Bearer`, status map, BVN-not-accepted, last-4 only, garbage payloads,
  5xx retry then success, 3-attempt give-up, 4xx/non-JSON not retried, transport errors, secrets and NIN never logged,
  host selection); webhook signature (valid, case-insensitive, tampered, wrong secret, fail closed); verification
  service and endpoints (config, start, attempt limit and window rollover, supersede, confirm success/failure
  reasons/pending/idempotent/foreign reference, provider outage keeps pending, admin precedence, status re-check,
  webhook applies the re-fetched result and ignores the claimed one, bad signature 401, unknown ref acknowledged,
  provider error 502).
* Migration `b8e1c4a7d2f3`: single head; upgrade -> downgrade -> upgrade on a scratch PostGIS DB; grandfathering
  verified earlier on seeded rows.
* Live walk-through of the running app (Dojah scripted at the transport layer, Paystack refund/lookup stubbed): 44
  captures in `docs/fe-captures/verification-admin/`; `create_admin.py` run live (created, updated, refused,
  promoted).
* **Not verified live:** real Dojah calls/webhooks (no keys), the Paystack `/refund` call, push notifications.

## Operate / roll back

Create or repair the first admin (idempotent; env must hold `FIRST_SUPERUSER_EMAIL/PASSWORD`):

```bash
docker compose exec api python scripts/create_admin.py                    # create, or ensure an existing admin
docker compose exec api python scripts/create_admin.py --reset-password   # overwrite the admin's password
docker compose exec api python scripts/create_admin.py --promote-existing # take over a pre-existing non-admin account
```

Enable verification (server env only, never in git): `DOJAH_ENVIRONMENT` (`sandbox` | `production`; picks
`sandbox.dojah.io` vs `api.dojah.io`), `DOJAH_API_KEY` (secret key), `DOJAH_APP_ID`, `DOJAH_PUBLIC_KEY`,
`DOJAH_NIN_WIDGET_ID`, `DOJAH_WEBHOOK_SECRET`. In the Dojah dashboard: publish a NIN + selfie/liveness widget and
subscribe the webhook (`POST /api/v1/webhook/subscribe` or Developers > Webhooks, service `kyc_widget`) to
`https://<api-host>/api/v1/verification/webhook`; the secret shown there is `DOJAH_WEBHOOK_SECRET` (not the API key).
Sandbox keys only work on the sandbox host.

Rollback: `alembic downgrade c8a1d2e3f4b5` drops the new tables/columns (verification history and admin audit rows
are lost). Code rollback alone is safe: the new columns have defaults.

## Follow-ups

* The `refund.*` payload keys `handle_refund_event` reads (`transaction_reference` or `transaction.reference`, `id`,
  `status`) are NOT verified against a live Paystack webhook; confirm on the first real refund.
* **Legacy artisans (owner default):** artisans verified by the old auto-verify stay verified
  (`verification_method='legacy'`). A re-verification campaign through the widget is a follow-up: listing them is
  `GET /admin/users?user_type=artisan&verification_status=verified` filtered on method `legacy` (a `legacy` filter
  is not built yet), then ask them to verify and decide when the badge for unverified-by-Dojah artisans is retired.
* `POST /payments/{id}/release` (owned by the payments work) should now become admin-only using `require_admin`.
* First live run with real Dojah keys: confirm response parsing, `nin_last4` availability, webhook secret/headers,
  and that the widget `reference_id` round-trips.
* Identity binding (raised by the automated security review): a pass proves the person in the selfie owns *some* valid
  NIN, not that the NIN belongs to the account holder or is unique to one account (one person could verify several
  accounts, or a stranger's NIN could be used). Not built, because the owner's rule is to never store the NIN: options
  are (a) tolerant first/last-name match against Dojah's `government_data` record, routing mismatches to admin review,
  and/or (b) a keyed HMAC of the NIN in a unique column to refuse duplicates. (b) stores a NIN-derived value, so it needs
  the owner's explicit OK first.
* Optional hardening: admin audit-log read endpoint; admin web dashboard (deferred).
* `tests/admin/` reuses the shared `db`/`client`/`notifications` fixtures from `tests/conftest.py`.
