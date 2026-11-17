# SOP: Payments & payout safety (money paths)

**What shipped:** a hardened Paystack charge flow, a real withdrawal ledger (one Paystack transfer per
withdrawal), transfer webhooks, wallet reads that reflect withdrawals, a locked-down release endpoint, an
hourly auto-confirm task, review notifications, one shared Redis-backed rate limiter, and a CI that can
actually run the tests.
**PR:** `fix/payments-payout-safety` → `main` (see PR link in the lead's report). **Migration:** `c8a1d2e3f4b5`
(down_revision `f7b8c9d0e1f2`).

## Why

A code audit found real defects in the money paths:

| Defect | Effect |
|---|---|
| `PaymentMethod(data['channel'])` raised for Paystack channels outside the enum (`bank`, `mobile_money`, `qr`, `eft`) | The webhook 500'd after the customer had paid; booking never reached `PAID` |
| Webhook and `GET /payments/verify` had two copies of the settle logic, neither checked amount/currency; verify marked `abandoned` charges `FAILED` | Wrong-amount charges settled; a customer who simply had not paid yet was marked failed |
| `POST /wallet/payout/request` made one Paystack transfer per payment, flipped payments to `RELEASED` immediately, did no locking, had no idempotency, returned `str(e)` from Paystack | Double tap = double payout; a failed transfer still burned the payments; raw provider errors leaked |
| Wallet reads had no notion of in-flight money | Processing payouts still counted as available |
| `POST /payments/{id}/release` let the artisan mark a payment released with no transfer | Fake releases |
| No auto-confirm; two `TODO` review notifications | Artisans waited forever for clients who never confirm; reviews were silent |
| Two separate in-memory `Limiter`s | Limits were per-process and counted twice/never |
| CI used plain `postgres:15` and SQLite conftest | Tests could not create the PostGIS schema; lint failure hid the test step |

## How (decisions and trade-offs)

1. **One settlement service** (`app/services/payment_service.py`): `apply_charge_success` / `apply_charge_failed`
   are used by both the webhook and `verify`. They lock the payment + booking rows (`FOR UPDATE`), are idempotent
   and compare Paystack's `amount` (kobo, int) and `currency` to the stored payment; a mismatch is **not**
   settled (logged at ERROR; webhook still answers 200 so Paystack stops retrying). Only `ACCEPTED → PAID`; the
   booking is never moved backwards. A late `charge.success` after a `FAILED` payment still settles (Paystack is
   the truth). `verify` only marks `FAILED` when Paystack says `failed`; `abandoned`/`pending` leave it `PENDING`.
2. **Channel mapping** (`map_paystack_channel`): every known Paystack channel maps to a `PaymentMethod`; anything
   unknown maps to `OTHER`. `payments.payment_method` is `VARCHAR(20)` in the real schema (see
   `d7f8e9a1b2c3`), so adding enum members needs **no migration** (no `ALTER TYPE`).
3. **Withdrawal ledger** (`app/db/models/withdrawal.py`, migration `c8a1d2e3f4b5`): `withdrawals` table + nullable
   `payments.withdrawal_id` (FK `ON DELETE SET NULL`). Status is `VARCHAR(20)` (`processing|success|failed|reversed`),
   not a PG enum, so it is easy to extend. Only the last 4 digits of the account are stored. Payments in a
   withdrawal are excluded from the available balance and stay `SUCCESS` until `transfer.success`.
4. **Payout request** (`app/services/withdrawal_service.py`, endpoint `wallet.py`):
   - Stateless Paystack calls (account verify, recipient) happen *before* any lock; then one transaction takes a
     per-artisan mutex (`SELECT ... FOR UPDATE` on the user row), re-checks the idempotency key, locks eligible
     payments (`FOR UPDATE OF payments`), picks whole payments oldest-first (greedy, skipping any that would
     overshoot) and creates + links the withdrawal. The Paystack transfer is initiated after the commit.
   - `Idempotency-Key` header (≤100 chars): a repeat returns the original withdrawal (`idempotent_replay: true`).
     Reusing a key with a different account/bank is `409`. Unique `(artisan_id, idempotency_key)` is the backstop.
   - The Paystack transfer `reference` is our own `wdr_<uuid>`, so a retry can never double-pay.
   - Outcome handling: 4xx from Paystack = definitive rejection → withdrawal `failed`, payments unlinked, client
     gets a generic `502`. Timeout/5xx = outcome unknown → stays `processing` (the webhook settles it). Transfer
     status `otp` → the transfer EXISTS at Paystack, so the withdrawal stays `processing` (payments stay locked) with an
     ERROR log (Paystack transfer OTP must be disabled in the dashboard); freeing the payments there could pay twice.
   - `MIN_PAYOUT_NGN` (default `5000`) applies to the *requested* amount AND to the actual transfer total
     (whole-payment selection that would transfer less than the minimum is a 400, before Paystack is called).
     The response `amount` is the **actual** transfer total; `requested_amount` is echoed. If nothing fits: `400` naming the nearest withdrawable amount
     (the smallest eligible payment).
5. **Transfer webhooks** (`settle_transfer_success`, `settle_transfer_failure`): `transfer.success` → withdrawal
   `success`, payments `RELEASED` with `released_at` and a unique per-payment `payout_reference`
   (`<withdrawal.reference>:<payment_id>`, the column is unique). `transfer.failed` / `transfer.reversed` →
   `failed` / `reversed`, payments unlinked (money back in balance), artisan notified. A reversal after a success
   also restores released payments to `SUCCESS`. Redeliveries and out-of-order events are no-ops (logged).
   `transfer.success` with a different amount than the withdrawal is not settled.
6. **Wallet reads** keep every existing field and add: balance → `available_balance`, `pending_withdrawal`,
   `min_payout` (`pending_release` is unchanged in meaning: withdrawable now); earnings items → `withdrawal_id`,
   `withdrawal_status`; payouts → `withdrawals[]` (every withdrawal, any status) and `withdrawal_id` per payout;
   stats → `available_balance`, `pending_withdrawal`; payout response → `withdrawal_id`, `requested_amount`,
   `payments_count`, `idempotent_replay`. Queries now join `bookings` instead of loading all booking ids.
7. **`POST /payments/{id}/release`** returns `403` for everyone. It stays disabled until the admin role
   (`require_admin`, another stream) exists; payouts go through withdrawals only.
8. **Auto-confirm** (`app/tasks/booking_tasks.py`, beat `auto-confirm-completed-bookings`, hourly): `COMPLETED`
   bookings with `completion_confirmation_deadline_at <= now`, unconfirmed, undisputed get
   `completion_confirmed_by_client_at = now`, one `BookingProgressLog` entry
   ("Completion automatically confirmed ...") as the auto marker, and a notification to artisan and client. Rows
   are claimed with `FOR UPDATE SKIP LOCKED` in batches of 200, so overlapping runs are safe and re-runs are no-ops.
9. **Reviews**: the two `TODO`s now notify the artisan (`review_received`) and the customer (`review_response`).
10. **Rate limiting**: one `Limiter` in `app/core/rate_limit.py` (Redis storage, `RATE_LIMIT_STORAGE_URI` or
    `REDIS_URL`), imported by `main.py` and `auth.py`; the custom 429 handler is unchanged. If Redis is down slowapi
    falls back to in-memory (fail-open) rather than failing logins.
11. **CI**: the `test` job uses `postgis/postgis:15-3.4`, sets the full set of required env vars, runs
    `alembic heads` (must be exactly one) + `alembic upgrade head`, then `pytest`. `tests/conftest.py` runs against
    real Postgres (refuses a database whose name lacks `test`), enables PostGIS, `create_all` if empty, and
    TRUNCATEs after every test. Lint is its own job so a lint failure no longer hides test results.

**Rejected alternatives:** one transfer per payment (no atomicity, N Paystack fees); partial payments (breaks the
per-payment ledger); holding the DB lock across the Paystack call (would block the artisan's row for seconds);
a PG enum for withdrawal status (needs `ALTER TYPE` for every change).

## Review round 2 (Opus review of PR #2), all fixed

| Finding | Fix |
|---|---|
| Stuck money: timeout / 5xx / `status:false` left a withdrawal `processing` forever | Hourly beat task `reconcile_withdrawals` (`app/tasks/withdrawal_tasks.py`, `reconcile_processing_withdrawals`): for `processing` withdrawals older than 10 min call `GET /transfer/verify/:reference` (`PaystackService.verify_transfer`) and apply the same settle/fail functions as the webhooks; a Paystack 404 means the transfer never existed, so fail + unlink; pending/otp/unknown/errors are left for the next run. The payout response no longer says "initiated successfully" unless Paystack confirmed a `transfer_code`; otherwise `status: processing` with an honest "confirming with the bank" message |
| Double payout on `otp` | `otp` keeps the withdrawal `processing` (see above) |
| `transfer.success` ignored after `failed`/`reversed` | New status `needs_review`: payments untouched, ERROR log, artisan notified; money still linked to a `needs_review` withdrawal is reported in `pending_withdrawal`, never as available |
| `transfer.success` amount/currency | Missing amount, different amount, or different currency (when present) all go to `needs_review` instead of settling |
| Idempotency replay ignored the amount | `withdrawals.requested_amount` stored; same key with another amount is `409` |
| Re-initialised FAILED payment lost its old reference | `payment_references` table keeps old references; webhook and verify resolve them. A `charge.failed` for an old reference never fails the current attempt. A second successful charge on a different reference is flagged `needs_refund` |
| Success on a CANCELLED/REJECTED booking only warned | `payments.needs_refund = true` (admin refunds; the admin stream should list `needs_refund` payments) |
| Blocking work on the event loop | `request_payout`, `verify_payment`, `initialize_payment` are plain `def` (threadpool); the webhook keeps `async` only to read the raw body and runs the DB work in `run_in_threadpool` |

Schema (same migration `c8a1d2e3f4b5`, still unmerged): `withdrawals.requested_amount`, `payments.needs_refund`,
table `payment_references`. `needs_review` fits the existing `VARCHAR(20)` status column (no migration for the value).

## What's involved

| Area | Path |
|---|---|
| Settlement service | `app/services/payment_service.py` |
| Withdrawal service | `app/services/withdrawal_service.py` |
| Model + migration | `app/db/models/withdrawal.py`, `app/db/models/payment.py` (`withdrawal_id`, new `PaymentMethod` members), `alembic/versions/c8a1d2e3f4b5_add_withdrawals_ledger.py` |
| Endpoints | `app/api/v1/endpoints/payments.py` (verify, webhook, release), `app/api/v1/endpoints/wallet.py`, `app/schemas/wallet.py` |
| Paystack client | `app/services/paystack.py` (`recipient`/`transfer` now raise `PaystackError` with the HTTP status) |
| Notifications | `app/services/notify.py`, `app/api/v1/endpoints/reviews.py` |
| Tasks | `app/tasks/booking_tasks.py`, `app/tasks/withdrawal_tasks.py`, `app/celery_app.py` |
| Rate limit | `app/core/rate_limit.py`, `app/main.py`, `app/api/v1/endpoints/auth.py` |
| Config | `MIN_PAYOUT_NGN`, `RATE_LIMIT_STORAGE_URI` in `app/core/config.py` |
| CI / tests | `.github/workflows/ci.yml`, `.flake8`, `tests/` |

## Verification

| Check | Result |
|---|---|
| Migration chain | `alembic heads` = one head (`c8a1d2e3f4b5`); `upgrade head` -> `downgrade f7b8c9d0e1f2` -> `upgrade head` round trip on a scratch PostGIS 15-3.4 container: clean |
| New automated tests (this feature only; the full suite is left to CI) | Pass locally: `tests/services/` (commission split, channel mapping, charge settlement incl. amount/currency mismatch, no-regress, idempotency; withdrawal selection, balance, idempotency, failure/ambiguous/OTP paths, settlement, **real two-thread double-tap races**), `tests/api/` (webhook signature + events, verify/webhook parity, wallet endpoints, release 403), `tests/tasks/` (auto-confirm), `tests/test_rate_limit.py` |
| Tests can fail | Mutation-checked: removing the amount/currency check fails 3 tests; removing the row locks fails both concurrency tests |
| Live journey | `scripts/capture_payments_wallet.py` ran the real app against scratch Postgres with a local Paystack stand-in: initialize, webhook (`mobile_money`), redelivery, verify, wallet reads, payout (actual < requested), replay, no-fit/min/role errors, `transfer.success`, second payout, `transfer.failed`, release 403. Raw bodies: `docs/fe-integration-captures/payments-wallet/` and `docs/fe-integration-guide-payments-wallet.md` |
| Lint | New modules and tests are black/isort/flake8 clean (config in `.flake8`, black line length 100). Legacy files I only edited keep their pre-existing style debt |
| **Not verified live** | Real Paystack (initialize/transfer/webhook signatures with a real account), `transfer.reversed`, timeout/5xx and `otp` branches (unit-tested only), Celery beat run of the auto-confirm task, FCM delivery |

## Operate / roll back

- **Deploy:** run `alembic upgrade head` (API container only, per `SKIP_MIGRATIONS`). New env vars are optional
  (`MIN_PAYOUT_NGN`, `RATE_LIMIT_STORAGE_URI`).
- **Paystack dashboard:** register the webhook URL for `charge.success`, `charge.failed`, `transfer.success`,
  `transfer.failed`, `transfer.reversed`; **disable transfer OTP** (otherwise payouts revert with an ERROR log);
  keep the account balance funded.
- **Roll back code:** revert the PR; `withdrawals` rows are inert to old code, but old code will not honour
  `withdrawal_id` (in-flight payouts would look available), so only roll back when no withdrawal is `processing`.
- **Roll back schema:** `alembic downgrade f7b8c9d0e1f2` (drops `payments.withdrawal_id` and `withdrawals`).
- **Stuck `processing` withdrawals**: the hourly `reconcile_withdrawals` task resolves them (10 min age threshold);
  `needs_review` ones need a human: check the transfer in Paystack by `reference` and fix the row.

## Follow-ups

- Admin tooling to resolve `needs_review` withdrawals and refund `needs_refund` payments (flags exist, no endpoint yet).
- Admin-only manual release / refund flows (admin stream) must go through the same withdrawal ledger.
- Repo-wide `black`/`flake8` baseline is red on `main` (59 files); lint job stays red until a format-only PR.
- Webhook IP allow-listing / replay-window check is not implemented (signature only).
