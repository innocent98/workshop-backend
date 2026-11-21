# SOP: Artisan response time + abusive-review filter

PR: `feature/response-time-review-filter` (see the PR for the head sha). FE contract:
[fe-integration-guide-reviews-response-time.md](../fe-integration-guide-reviews-response-time.md), live captures in
`docs/fe-captures/reviews-response-time/`.

## What shipped
| # | Change | Where |
|---|---|---|
| 1 | `artisan_profiles.response_time_avg_minutes` is now real: recomputed when an artisan accepts a booking, and backfilled for existing artisans | `app/services/response_time.py`, `app/api/v1/endpoints/bookings.py` (`accept_booking`), migration |
| 2 | First-pass abusive-language filter on review creation. A hit hides the review from public lists **and** from the artisan's rating/review count, but the reviewer still gets a normal `201` | `app/services/review_moderation.py`, `app/data/review_abuse_terms.json`, `app/api/v1/endpoints/reviews.py` |
| 3 | `POST /reviews/{id}/report` (any signed-in user except the author, one per user per review, rate limited) | `app/api/v1/endpoints/reviews.py`, `ReviewReport` model |
| 4 | Admin moderation: `GET /admin/reviews` (queue), `GET /admin/reviews/{id}`, `POST .../flag`, `POST .../unflag`, each state change audited | `app/api/v1/endpoints/admin.py`, `app/services/admin.py` |
| 5 | One helper derives the public rating figures from unflagged reviews and is used by create, flag and unflag | `app/services/review_ratings.py` |
| 6 | `GET /search/artisans?sort_by=response_time` now sorts artisans with no figure **last** in both directions | `app/api/v1/endpoints/search.py` |

## Why
The PRD asks for response-time stats shown to customers and for abusive-review filtering. A code check showed both existed only as unused fields: `response_time_avg_minutes` was exposed by the search and profile schemas but never written, and `reviews.is_flagged` was honoured by the public listing queries but nothing ever set it. The profile aggregates (`average_rating`, `total_ratings`) were already computed excluding flagged rows at creation time, but nothing recalculated them when a flag changed.

## How (decisions and tradeoffs)
| Area | Decision | Rejected |
|---|---|---|
| Response-time storage | **Recompute** from the artisan's last 20 accepted bookings (`accepted_at` set) on every accept. Window is `RESPONSE_TIME_WINDOW` | Running average + count column: needs a new column and drifts if a booking is ever corrected. The recompute is one indexed query and the window makes the figure reflect current behaviour |
| What counts | Rows with `accepted_at`: request-to-acceptance minutes (`created_at` to `accepted_at`). Rejected, cancelled-before-accept and pending requests never get `accepted_at`, so they are excluded without special-casing | Counting expiry/rejection as a "response": the spec excludes them |
| Rounding | Whole minutes, **never below 1**; a negative gap (clock skew) counts as 0 before averaging | Allowing 0: it reads as "no data" to a falsy check in the app. `null` is the only "no data" value |
| Concurrency | The accept already holds the booking row `FOR UPDATE`. `record_acceptance` then locks the artisan's profile row `FOR NO KEY UPDATE` (`key_share=True`: still serialises recomputes, conflicts with fewer other locks), flushes, recomputes. Lock order is booking then profile, the same order account deletion uses (booking-first). Two simultaneous accepts of different bookings serialise on the profile, so neither overwrites the other with an average that misses it | Computing outside the lock (lost update) |
| Isolation | The stat is derived data and must never fail an accept. `_record_response_time` (bookings.py) runs it in a **SAVEPOINT** (`db.begin_nested()`) with `SET LOCAL lock_timeout = '3s'`, inside `try/except Exception` that logs with `logger.exception`. A lock wait, deadlock or DB error rolls back only the stat update; the acceptance still commits and returns 200. The next accept recomputes from the bookings table, so a skipped update self-heals | Letting the error propagate (a stat problem would 500 the accept and roll the acceptance back); a background job (stale, extra moving part) |
| No profile row | Accept still succeeds, the stat is skipped, no profile is created there | Failing the accept |
| Backfill | In the migration, one `UPDATE ... FROM (window function)` with the same maths as the service. Downgrade leaves the values (the column pre-dates this change and the figures are true) | A separate script to remember to run |
| Filter list | A JSON data file keyed by language (`en`, `pcm`, `yo`, `ha`, `ig`) plus `REVIEW_ABUSE_EXTRA_TERMS` (comma separated) for adding words without a deploy and `REVIEW_ABUSE_FILTER_ENABLED` as an off switch. No network calls | A third-party moderation API: latency, cost, an outage blocking reviews, and sending user text to a vendor |
| Matching | Lower-case, strip accents (Yoruba tone marks), map leetspeak (`0 1 3 4 5 7 @ $`), split on punctuation, collapse repeated letters, `*` as a one-letter wildcard (`f*ck`). Whole words and phrases only, so `class` and `Scunthorpe` do not match | Substring search (false positives) |
| Precision over recall | The list is deliberately high-precision. Ordinary vocabulary, names, towns and slang are left out: `ofe` (soup), `thief`, `dull`, `ara`, "your mother", and after review `ode`, `jaki`, `wawa`, `olodo` (a town in Oyo State), `karuwa`, `agbaya`, `werey`, `mugu`, bare `yeye`/`nzuzu`, `prick`, `retard` (a technical verb) and the phrase "i will find you". A false positive hides an honest review until an admin looks; a miss is caught by the report flow | A long aggressive list |
| Auto-flag behaviour | Review is stored with `is_flagged=true`, `flag_source='auto'`, a reason and `flagged_at`; the reviewer still gets `201` with their text; the artisan is **not** push-notified about a hidden review |
| Hidden = invisible to the artisan | `GET /reviews/booking/{id}` returns a flagged review to its author only; the artisan gets the same 404 as a booking with no review. `PATCH /reviews/{id}/respond` is a 404 for the artisan on a flagged review (a reply would notify the customer and confirm it exists). When an admin **unflags a hidden review**, the artisan gets the normal "New review" push then; dismissing reports on a visible review, or hiding one, sends nothing | Letting the artisan read it: the filter hides content from the person it is about, but they could still see, answer and screenshot it | Rejecting the review (the reviewer learns the filter and rewrites around it) |
| Reports never auto-hide | A report only increments `open_report_count` and queues the review for an admin. There is no report threshold | Auto-hide at N reports: a pile-on (or one person with several accounts) could silence an honest review |
| Report rules | Any signed-in user except the review's author. UNIQUE `(review_id, reporter_id)` plus an explicit check gives `409 already_reported`. The review row is locked `FOR UPDATE` so the counter cannot lose an increment | Restricting to the reviewed artisan: customers reading public reviews should be able to report too |
| Report limits | Two layers. **Per user**: `REVIEW_REPORTS_PER_USER_PER_HOUR` (default 10), counted from `review_reports`, answers `429 report_rate_limited`. **Per IP**: slowapi `REVIEW_REPORT_IP_RATE_LIMIT` (default `30/hour`) as a backstop | Per-IP only: Nigerian mobile carriers put many users behind one IP, so an IP limit alone is both too blunt and too weak |
| Admin decisions | `flag` hides (source `admin`, note becomes the reason), closes open reports, recalculates the rating. `unflag` restores a hidden review **or** dismisses open reports on a visible one (`409 review_not_flagged` when there is nothing to do). `flag` on an already-hidden review is allowed: it records the decision and closes the reports | Separate "dismiss reports" endpoint (one more route for the same effect) |
| Reports are history | `review_reports.resolved_at` is set when an admin acts; rows are never deleted. `reviews.open_report_count` is the number still open | Deleting reports on resolution (loses the trail) |
| Aggregates | `recalculate_artisan_rating` locks the profile row, flushes, recounts `is_flagged = false` reviews. Lock order for the review paths is review then profile; response-time is booking then profile; no cycle | Incremental +/- updates (drift) |
| Error shape | New endpoints use `{"detail": {"code", "message"}}` like the admin and account-deletion APIs | The older plain-string `detail` of the rest of `/reviews` |

## What's involved
* **Migration** `alembic/versions/a4c8e2f6b1d9_review_moderation_and_response_time_backfill.py` (down revision `d3f5a7c9e1b2`, single head): `reviews.flag_source`, `flag_reason`, `flagged_at`, `open_report_count` (NOT NULL, server default 0), index `ix_reviews_is_flagged`; table `review_reports` (`review_id`, `reporter_id`, `reason`, `details`, `created_at`, `resolved_at`, UNIQUE `uq_review_report_once`, FKs `ON DELETE CASCADE`); the response-time backfill.
* Models: `app/db/models/review.py` (`Review` new columns, `ReviewReport`), registered in `app/db/models/__init__.py` and `app/db/base.py`.
* Services: `app/services/response_time.py`, `app/services/review_ratings.py`, `app/services/review_moderation.py`, admin additions in `app/services/admin.py` (`admin_flag_review`, `admin_unflag_review`, `review_item`, `review_detail`).
* Endpoints: `bookings.py` (`accept_booking` calls `record_acceptance`), `reviews.py` (`create_review`, `report_review`), `admin.py` (`/admin/reviews...`), `search.py` (`nulls_last` for `response_time`).
* Schemas: `app/schemas/review.py` (`ReportReviewRequest/Response`), `app/schemas/admin.py` (`AdminReviewItem`, `AdminReviewDetail`, `AdminReviewReportItem`, `ReviewModerationRequest`).
* Config (`app/core/config.py`, all optional, defaults shown): `REVIEW_ABUSE_FILTER_ENABLED=true`, `REVIEW_ABUSE_EXTRA_TERMS=""`, `REVIEW_REPORT_IP_RATE_LIMIT="30/hour"`, `REVIEW_REPORTS_PER_USER_PER_HOUR=10`, `RESPONSE_TIME_WINDOW=20`.
* Data: `app/data/review_abuse_terms.json` (shipped in the image: the Dockerfile copies `./app`).
* Schemas of existing responses are **unchanged**: `response_time_avg_minutes` was already in the search/profile/stats schemas.

## Verification
Local checks only (CI runs the suites): `black --check`, `isort --check-only`, `flake8` on `app tests`, plus the files below on a scratch PostGIS.
* `tests/services/test_review_moderation.py` (~30 cases): each language, leetspeak/repeats/`*` masks/tone marks, whole-word and false-positive guards (soup, names, towns, `class`, `retard the cement`, "I will find you a better plumber"), phrases, multi-language counts, off switch, extra terms from settings, a broken list never blocks a review.
* `tests/api/test_response_time.py` (15): none until the first accepted booking, plain average, rejected/pending/cancelled not counted, last-N window, other artisans do not leak, instant acceptance reads 1 not 0, negative gap, and the accept endpoint hook (records, updates the running average, reject leaves it alone, a failed accept leaves it alone, accept without a profile row, value visible on `/profiles/artisans/me/stats`), and the isolation: a forced exception, and a real DB error (`SELECT 1/0`) inside the stat update, both still return 200 with the booking ACCEPTED and committed, and the next accept recomputes including the earlier booking.
* `tests/api/test_review_moderation_api.py` (28): clean vs abusive creation (201 for the reviewer, hidden, not counted, artisan not notified), mixed average, off switch, report success/duplicate/own review/404/invalid reason/per-user cap (and the cap window expiring)/per-IP backstop, admin auth (anonymous and non-admin refused on every route), queue views, detail, flag (rating recalculated, reports closed, audit row), unflag restore, dismiss reports, idempotent flag, validation and 404 (no audit rows written), flag-then-unflag round trip leaves the rating unchanged; the artisan gets 404 on the booking-review read and on respond for a hidden review (indistinguishable from "no review"), can read and reply once restored; restoring a hidden review sends the "New review" push, dismissing reports or hiding sends none.
* `tests/api/test_booking_account_races.py` re-run as the one bounded regression for the accept endpoint (the four touched files: 91 pass).
* **Migration** on a scratch DB built with `alembic upgrade head`: `alembic heads` shows one head; upgrade, `downgrade -1`, upgrade again all succeed. **Backfill** checked with seeded history (artisan with accepted bookings after 10/20/30 min plus a rejected and a pending one: 20; artisan with 22 accepted where the two oldest took 1000 min: 5, proving the 20-booking window; artisan with only a rejection: NULL).
* **Live walk** against the running app with real responses captured in `docs/fe-captures/reviews-response-time/` (48 requests + the end DB state, including the artisan-404 checks for hidden reviews); every body in the FE guide comes from there.

## Operate / roll back
* Deploy order: nothing special; the migration is additive and runs at deploy (`docker-entrypoint.sh`).
* **Check row counts before applying.** The whole migration is one transaction: `ALTER TABLE reviews` (four new columns: PostgreSQL 11+ adds a NOT NULL column with a constant default without rewriting the table, but the ALTER still takes a brief ACCESS EXCLUSIVE lock on `reviews`) and then the backfill UPDATE run together. The backfill reads every `bookings` row with `accepted_at` set (window function) and updates one `artisan_profiles` row per artisan. Run these first and judge the lock time against them:
  ```sql
  SELECT count(*) FROM bookings WHERE accepted_at IS NOT NULL;
  SELECT count(*) FROM artisan_profiles;
  SELECT count(*) FROM reviews;
  ```
  Fine at tens of thousands of rows. If `bookings` is large, apply in a quiet window.
* **The backfill overwrites** any existing non-null `response_time_avg_minutes` for artisans that have accepted bookings (the app never wrote the column before, so only a value set by hand would be lost). Artisans without accepted bookings keep `NULL`.
* Tune the list without a deploy: set `REVIEW_ABUSE_EXTRA_TERMS="word one, phrase two"`. Disable the whole filter with `REVIEW_ABUSE_FILTER_ENABLED=false` (already-hidden reviews stay hidden until an admin unflags them).
* Roll back the app: the new columns and table are harmless to old code (old code ignores them). Reviews hidden by the filter stay `is_flagged=true`, so they stay hidden under old code too.
* Roll back the schema: `alembic downgrade -1` drops the report table and the four review columns (reports are lost). Backfilled response-time values are kept.
* An admin who needs to find who reported what: `review_reports` (or `GET /admin/reviews/{id}`); who made each decision: `admin_audit_logs` rows with action `review.flag` / `review.unflag`.

## Follow-ups
* The app has no way to know a user already reported a review (no `viewer_has_reported` field); it relies on the `409`. Add it when the review list is next touched.
* `artisan_profiles.acceptance_rate` has the same problem response time had: exposed but never written.
* `create_review` still does `total_jobs_completed += 1` for every review (pre-existing, not changed here); that counter should move to the completion path.
* The auto-filter runs on review creation only (there is no review-edit endpoint) and not on `artisan_response`. If artisan replies can be abusive, run the same check there.
* The word list needs tuning with real traffic: review the admin queue for false positives and add misses via `REVIEW_ABUSE_EXTRA_TERMS`, then fold stable additions into the JSON.
* Pre-existing, found while testing: the Alembic-built schema stores `bookings.status` as `VARCHAR` while the ORM expects the native `bookingstatus` enum, so the ORM cannot insert into an Alembic-only database (the tests and the capture build tables with `create_all`). Worth checking against production.
* **Known limitation: profane but genuine complaints are hidden until an admin acts.** The filter cannot tell abuse from an angry honest review that contains a listed word, so a real 1-star complaint stays out of the artisan's rating and the public list until it is reviewed. Suggested follow-up: return queue counts in the admin list response (e.g. `counts: {flagged, reported, needs_attention, oldest_flagged_at}`) so the admin app can show a badge and an SLA, and consider auto-restoring an `auto` flag nobody has handled after N days.
* No push notification to the reporter when a decision is made.
