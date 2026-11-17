# SOP: Account-deletion review follow-ups (lock order, customer lock, fail-closed limiter)

Follow-up to [account-deletion.md](account-deletion.md) (PR #5). Fixes the non-blocking items an Opus review left.
PR: `fix/deletion-review-followups` (see the PR for the head sha).

## What shipped
| # | Change | Where |
|---|---|---|
| 1 | `apply_charge_success` locks **booking then payment**, the same order as `delete_account`; a late `charge.success` for a customer who is already deleted is recorded but flagged `needs_refund` | `app/services/payment_service.py` |
| 2 | `POST /bookings` re-checks the customer is active **under a row lock** and returns 409 `account_unavailable` | `app/api/v1/endpoints/bookings.py` |
| 3 | Delete-account and change-password limiters **fail closed** (503 `limiter_unavailable`) on a Redis outage, and count the attempt **atomically** before the credential is checked | `app/core/attempt_limit.py`, `app/api/v1/endpoints/auth.py` |

## Why
1. **Deadlock.** Settlement locked Payment then Booking; deletion locks every Booking of the user, then their Payments. Two transactions on the same booking could each hold one lock and wait for the other.
2. **Booking after anonymisation.** `create_booking` only locked the *artisan* row. A customer mid-deletion (holding their own user row `FOR UPDATE`) could insert a PENDING booking after `delete_account` had already closed the pending ones, leaving a live booking on an anonymised account.
3. **Limiter.** The per-user counter failed open, so with Redis down a stolen token could guess the password without bound on the two endpoints where that matters. Read-then-write (`is_locked`, check credential, `register_failure`) also let N parallel guesses all pass the check before any was counted.

## How (decisions and tradeoffs)
| Area | Decision | Rejected |
|---|---|---|
| Lock order | Unlocked probe read of the payment to learn `booking_id` (a payment never changes booking), `SELECT ... FOR UPDATE` the booking, then lock the payment by reference and read it fresh. Idempotency, mismatch and duplicate handling are unchanged | Changing `delete_account` to lock payments first: it locks them via a join on the user's bookings, so booking-first is the natural order and settlement is the one place that deviated |
| Fresh read under the lock | The locked payment query (`find_payment_by_reference(lock=True)`) and the booking query use `populate_existing()`. `FOR UPDATE` alone does not refresh an instance the session already holds (the unlocked probe, or `/payments/verify`'s earlier read), so without it a settlement committed between the probe and the lock was invisible and the charge settled twice (verified: the two race tests failed before the fix). `/payments/verify` needs no change: its early reads only gate, the decision is made inside `apply_charge_success` | Expiring the probe by hand at each call site |
| Deleted customer | After the booking lock is held (so a deletion in flight has committed or is waiting behind us) read `users.is_active` and `deleted_at`; if inactive: payment becomes SUCCESS (the money is real), `needs_refund = True`, booking is **not** moved to PAID, artisan is not notified, error logged | Dropping the charge (money would be lost to nobody), or marking PAID (the artisan could start a job nobody can pay for) |
| Customer lock | Column read `User.is_active` `FOR SHARE` on the customer's own row before the artisan lookup. Deletion holds that row `FOR UPDATE`, so we wait and then see the committed state. A column read (not an entity) avoids a stale identity-map copy. Shared locks do not conflict with each other, so concurrent bookings are not serialised | `FOR UPDATE` (would serialise a customer's own requests for no benefit) |
| Limiter atomicity | `begin_attempt` runs one Lua script: `INCR`, and `EXPIRE` only when the key is new or has no TTL. The attempt is counted **before** the credential check; success `clear`s, a request that failed for another reason (400 `password_required`, validation, a 409 blocker) `release_attempt`s (floor 0). The window is not refreshed by later attempts, so hammering a locked key cannot extend the lockout, and a crash cannot leave a key that never expires | `INCR` + `EXPIRE` in a pipeline (not atomic against a missing TTL); `WATCH`/`MULTI` (more round trips) |
| Fail closed | `begin_attempt(..., fail_closed=True)` raises `LimiterUnavailable`; the endpoints answer 503 `limiter_unavailable` and the module logs at ERROR. Default stays fail-open | A global switch: login must keep working through a Redis outage |

Login is unchanged: it is guarded by the per-IP slowapi limiter, never by `attempt_limit`, and `attempt_limit` still defaults to fail-open.

## What's involved
* `app/services/payment_service.py`: `apply_charge_success` (lock order + `customer_gone` branch); imports `User`.
* `app/api/v1/endpoints/bookings.py`: `create_booking` customer lock.
* `app/core/attempt_limit.py`: `LimiterUnavailable`, `begin_attempt`, `release_attempt`, Lua scripts, `fail_closed` on the read/write helpers (existing `is_locked`/`register_failure` kept, now atomic expiry).
* `app/api/v1/endpoints/auth.py`: `_begin_credential_attempt`, `_reauthenticate_for_deletion`, `change_password`.
* No migration, no new config.

## Verification
Local checks only (CI runs the suites). Tests run on a scratch PostGIS + Redis.
* `tests/services/test_payment_service.py`: `test_charge_success_locks_the_booking_before_the_payment` (a second session holds the booking; settlement must wait **without** holding the payment: `FOR UPDATE NOWAIT` on the payment succeeds meanwhile), `test_late_charge_for_a_deleted_customer_is_flagged_needs_refund`, and two race tests that commit a settlement from a second session between the probe and the lock (`..._seen_as_already_settled`, `..._flagged_duplicate`).
* `tests/api/test_booking_account_races.py`: `test_create_booking_waits_for_a_deleting_customer_then_409s` (customer row held, then deactivated), plus a positive control.
* `tests/test_attempt_limit.py`: 5-then-refuse, 20 concurrent attempts admit exactly 5, window set once and not extended, missing TTL repaired, release floors at 0, fail-open vs fail-closed on a broken client and on no client.
* `tests/api/test_account_deletion.py`: delete and change-password return 503 `limiter_unavailable` with Redis down (account unchanged, password unchanged), a correct password followed by a 409 blocker does not consume the budget.

## Operate / roll back
No config. Revert the PR to roll back. During a Redis outage deletion and password change answer 503 until Redis is back (intended; sign-in is unaffected).

## Follow-ups
* A `charge.success` that arrives for a deleted customer now sits in `needs_refund`; there is no admin UI yet beyond the existing refund flow.
* The change-password 429/503 shapes are not in the captured FE evidence (see the FE guide verification table).
