# SOP: In-app account deletion (`DELETE /auth/me`)

**What shipped:** an authenticated, re-authenticated account-deletion endpoint that soft-deletes and anonymises
the user (Apple App Store / Google Play requirement). PR: see the PR for branch `feature/account-deletion`.
Frontend contract: [`docs/fe-integration-guide-account-deletion.md`](../fe-integration-guide-account-deletion.md).

## Why
Both stores require users to be able to delete their account from inside the app. A hard delete is not possible:
bookings, payments and withdrawals must remain for accounting and cascade from `users`.

## How (decisions and tradeoffs)

| Decision | Choice | Rejected alternative / why |
|---|---|---|
| Delete model | soft delete: keep the `users` row, anonymise it, set `is_active=false` and `deleted_at` | Hard delete: the `ondelete=CASCADE` foreign keys would wipe bookings, payments and withdrawals |
| Placeholders | email `deleted+<uuid hex>@deleted.invalid`, phone `del_<12 hex>` (<= 20 chars), name `Deleted User`; password hash and `google_id` set NULL | Reusing one placeholder: both columns are unique. UUID-based placeholders never collide, and the real email/phone can register again |
| Re-auth, password accounts | `password` in the body; 400 `password_required`, 403 `invalid_password` (403, not 401, so the app does not treat it as a logged-out session) | Token only: a stolen/unattended session could delete the account |
| Re-auth, Google-only accounts | a **fresh Firebase ID token** (`google_token`) for the same Google user: verified with the same Firebase check as `/auth/google` (extracted to `verify_google_claims`), `uid == users.google_id`, and `auth_time` within 5 minutes | A "recent login" timestamp: we do not store one, and a fresh token proves the user can sign in to Google right now |
| Token revocation | the presented token is blacklisted (Redis); **every other token dies** because `get_current_user` rejects inactive users | Enumerating tokens (impossible: they are stateless JWTs) |
| Blockers (409) | accepted/paid/in_progress/disputed bookings (as customer or artisan); a withdrawal in `processing` or `needs_review`; earnings not yet withdrawn (completed jobs with a `success` payment and no withdrawal: withdrawable now **or** still in the confirmation window). All blockers are returned in `detail.blockers`, `detail.code` is the first | Only the "available" balance: money still inside the dispute window would be orphaned |
| Pending bookings | closed automatically (customer's -> cancelled, artisan's -> rejected) and the other side notified: they hold no money | Blocking on them: it would trap users behind requests nobody answers |
| Admins | cannot self-delete (409 `admin_account`) | Lock-out / abuse of the admin role |
| Audit | `admin_audit_logs` row `user.self_delete` with the user as actor; details hold no personal data (user type, count of closed pending bookings) | Logging the email/name |
| Race safety | the user row is locked (`FOR UPDATE`) while blockers are checked and the account is anonymised, in one transaction | Check-then-act without a lock |
| Rate limit | 10 / 15 min / IP via the shared limiter, so the password step cannot be brute-forced from a stolen token | none |

## What is removed vs kept

| Removed or replaced | Kept |
|---|---|
| name, email, phone, password hash, Google link, bio, profile picture, user location | bookings (amounts, status, references, addresses and descriptions) |
| push devices, in-app notifications, OTPs, password-reset tokens, selected services, verification attempt records | payments (amounts, Paystack references), with `customer_name/email` scrubbed to the placeholders |
| portfolio rows; portfolio + profile images deleted from storage in the background (best effort) | withdrawals (amounts, references, status), with `account_name` cleared; only the last 4 digits were ever stored |
| artisan profile: location, address, specialization, documents, NIN last 4, verification reference; set offline | reviews (ratings and text; the author shows as `Deleted User`) |

## What's involved
`app/api/v1/endpoints/auth.py` (`DELETE /auth/me`, `verify_google_claims`), `app/services/account_deletion.py`
(`find_blockers`, `delete_account`), `app/schemas/auth.py`, `app/db/models/user.py` (`deleted_at`),
`alembic/versions/d3f5a7c9e1b2_add_users_deleted_at.py` (down_revision `b8e1c4a7d2f3`), `tests/api/test_account_deletion.py`.

## Verification
* 25 tests (`tests/api/test_account_deletion.py`, scratch PostGIS + Redis): auth, re-auth (password and Google paths),
  anonymisation + kept financial rows, token revocation (including a second token), re-registration with the same
  email/phone, every blocker and the combined list, settled history not blocking, pending bookings closed, artisan
  portfolio/profile scrub. Migration: single head, upgrade/downgrade/upgrade round trip.
* Live capture against the running app: 19 captures in `docs/fe-captures/account-deletion/`.
* **Not verified live:** Firebase ID-token verification (stubbed in the capture server; no Firebase credentials here)
  and the `auth_time` claim shape; Cloudinary image deletion.

## Operate / roll back
No new config. Rollback: `alembic downgrade b8e1c4a7d2f3` drops `users.deleted_at`; accounts already deleted stay
anonymised (the data is not recoverable by design).

## Follow-ups
* Legal retention: booking free text and job locations of a deleted customer are kept for the counterparty's records
  and disputes. Decide if they must also be scrubbed after a retention period.
* There is no restore or grace period (deletion is immediate). A 30-day grace window would need a scheduled purge.
* Deleted users still appear as `Deleted User` on old reviews/bookings in the other party's app.
* Stale `deleted_at` rows could be listed in the admin API (`GET /admin/users` has no `deleted` filter yet).
