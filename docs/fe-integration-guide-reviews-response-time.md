# FE integration guide: artisan response time and review moderation

Backend PR branch: `feature/response-time-review-filter`. Base path for every endpoint below is `/api/v1`.
Every request/response body in this guide is **copied verbatim from the capture files in
[`docs/fe-captures/reviews-response-time/`](fe-captures/reviews-response-time/)**, produced by
`capture.py` against the real app (`capture_server.py`) on a scratch Postgres database with fake data.
The file number is shown next to each body so any claim can be re-derived. Ids, names, e-mails and
timestamps are throwaway capture data (placeholders), not real people.

How the captures were made, so you know how far to trust them:

- Real server, real database, real code paths for everything in this guide. No stand-ins.
- Bearer tokens were **minted with the app's own signer** instead of calling `POST /auth/login`
  (login is limited to 5 attempts per 15 minutes per IP and the walk needs seven users). Login is not
  part of this feature. Send `Authorization: Bearer <token>` as usual.
- Requests were seeded with back-dated `created_at` (25, 40 and 10 minutes ago) because the walk
  cannot wait. The acceptance time is the real server clock when `PATCH .../accept` arrives.
- The capture server ran with `REVIEW_REPORTS_PER_USER_PER_HOUR=2` so the per-user cap could be
  shown with three reviews. **The production default is 10 per hour.**
- No Redis was running, so the per-IP rate limiter used its in-memory fallback.

---

## 1. Response time

### What it is, in the app's terms

A number on every artisan: "usually replies in about N minutes". It is the average time between a
customer sending a booking request and the artisan accepting it, taken over the artisan's **last 20
accepted bookings**. It updates the moment the artisan accepts a booking.

- `response_time_avg_minutes` is an **integer number of minutes, or `null`**.
- `null` means "no data yet" (the artisan has never accepted a booking). **Do not render `null` as 0
  and do not show "0 min".** Hide the label (or show "New").
- The smallest real value is `1` (an instant acceptance still reads as 1, so `1` means "about a minute").
- Rejected, cancelled and still-pending requests are not counted.
- Existing artisans were backfilled from their historical accepted bookings when this shipped.

### Where the field appears (nesting traps)

| Endpoint | Where the field sits | Verified live |
|---|---|---|
| `GET /profiles/artisans/me/stats` | top level of the body | yes (01, 03, 05, 07) |
| `GET /profiles/artisans/{artisan_id}` (public profile) | top level of the body | yes (08, 09) |
| `GET /search/artisans` | **inside each item of `results[]`** (not at the top level) | yes (10, 11) |
| `GET /profiles/artisans/me`, `PUT /profiles/artisans/me`, `PATCH /profiles/artisans/me/availability` | top level (same column) | **NOT VERIFIED LIVE**: same schema field, not exercised in the walk |

### Artisan's own stats before any accepted booking

Request: `GET /profiles/artisans/me/stats` (artisan token). Capture 01, status 200.

```json
{
  "average_rating": 0.0,
  "total_ratings": 0,
  "total_jobs_completed": 0,
  "response_time_avg_minutes": null,
  "acceptance_rate": 0.0
}
```

### Artisan accepts a booking (existing endpoint, unchanged)

Request: `PATCH /bookings/1/accept`

```json
{
  "agreed_amount": 8000
}
```

Response, status 200 (trimmed to the fields relevant here, full booking body is in capture 02):

```json
{
  "id": 1,
  "status": "accepted",
  "agreed_amount": "8000.00",
  "created_at": "2026-11-18T21:41:09.145258Z",
  "accepted_at": "2026-11-18T22:06:09.380679Z"
}
```

Then the stats update (capture 03, request seeded 25 minutes before acceptance):

```json
{
  "average_rating": 0.0,
  "total_ratings": 0,
  "total_jobs_completed": 0,
  "response_time_avg_minutes": 25,
  "acceptance_rate": 0.0
}
```

After a second booking is accepted (requested 40 minutes before; average of the two, capture 05):

```json
{
  "average_rating": 0.0,
  "total_ratings": 0,
  "total_jobs_completed": 0,
  "response_time_avg_minutes": 33,
  "acceptance_rate": 0.0
}
```

### Rejection does not change it

Request: `PATCH /bookings/3/reject`

```json
{
  "rejection_reason": "fully booked that day"
}
```

Status 200. Stats afterwards (capture 07) still show `"response_time_avg_minutes": 33`.

### What customers see

Public profile of the artisan above (capture 08, status 200):

```json
{
  "id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "full_name": "Demo Artisan",
  "profile_picture_url": null,
  "bio": null,
  "location_address": "12 Example Street, Lagos",
  "service_radius_km": 10.0,
  "hourly_rate_min": null,
  "hourly_rate_max": null,
  "years_of_experience": null,
  "specialization": "Plumbing",
  "is_verified": false,
  "availability_status": "available",
  "average_rating": 0.0,
  "total_ratings": 0,
  "total_jobs_completed": 0,
  "response_time_avg_minutes": 33
}
```

Public profile of an artisan who has never accepted a booking (capture 09). The field is present and
`null` (it is not omitted):

```json
{
  "id": "1d7ba0d5-51e1-4b94-be57-f580ea2b544d",
  "full_name": "Newcomer Artisan",
  "profile_picture_url": null,
  "bio": null,
  "location_address": "12 Example Street, Lagos",
  "service_radius_km": 10.0,
  "hourly_rate_min": null,
  "hourly_rate_max": null,
  "years_of_experience": null,
  "specialization": "Plumbing",
  "is_verified": false,
  "availability_status": "available",
  "average_rating": 0.0,
  "total_ratings": 0,
  "total_jobs_completed": 0,
  "response_time_avg_minutes": null
}
```

### Search and sorting

`GET /search/artisans?latitude=6.5244&longitude=3.3792&sort_by=response_time&sort_order=asc`
(capture 10, status 200). Note `response_time_avg_minutes` inside each result:

```json
{
  "results": [
    {
      "id": "df631428-50f0-42d4-a868-59aaffb7a300",
      "full_name": "Demo Artisan",
      "profile_picture": null,
      "location_address": "12 Example Street, Lagos",
      "service_radius_km": 10.0,
      "hourly_rate_min": null,
      "hourly_rate_max": null,
      "years_of_experience": null,
      "specialization": "Plumbing",
      "is_verified": false,
      "availability_status": "available",
      "average_rating": 0.0,
      "total_ratings": 0,
      "total_jobs_completed": 0,
      "response_time_avg_minutes": 33,
      "acceptance_rate": 0.0,
      "distance_km": 0.0,
      "services": [],
      "category_name": null,
      "portfolio_sample": null
    },
    {
      "id": "1d7ba0d5-51e1-4b94-be57-f580ea2b544d",
      "full_name": "Newcomer Artisan",
      "profile_picture": null,
      "location_address": "12 Example Street, Lagos",
      "service_radius_km": 10.0,
      "hourly_rate_min": null,
      "hourly_rate_max": null,
      "years_of_experience": null,
      "specialization": "Plumbing",
      "is_verified": false,
      "availability_status": "available",
      "average_rating": 0.0,
      "total_ratings": 0,
      "total_jobs_completed": 0,
      "response_time_avg_minutes": null,
      "acceptance_rate": 0.0,
      "distance_km": 0.0,
      "services": [],
      "category_name": null,
      "portfolio_sample": null
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1,
  "search_location": {
    "latitude": 6.5244,
    "longitude": 3.3792
  },
  "filters_applied": {
    "radius_km": 10.0,
    "verified_only": false
  }
}
```

`sort_order=desc` (capture 11) returns the same order here: **artisans with `null` are always sorted
last, in both directions**, so a newcomer never outranks a proven fast responder. Fastest-first is
`sort_order=asc`.

### UX instructions

- Format for display: `1` → "about a minute", `2`–`59` → "N min", `60` and up → hours (e.g. 90 → "about 1.5 hours").
- Show it as "usually replies in …". It is an average of recent behaviour, not a promise.
- `null` → no label. Never "0 min".

---

## 2. Abusive-review filter (what changes for review creation)

### What it is, in the app's terms

When a customer submits a review, the backend scans the review text against a word list (English,
Nigerian Pidgin, Yoruba, Hausa, Igbo). If it matches, the review is **accepted normally for the
customer, but hidden from everyone else** until an admin looks at it. A hidden review also does not
count toward the artisan's average rating or review count. The word list is server-side only: do not
try to replicate the check on the device.

`POST /reviews` request and response are **unchanged in shape**. Clean review (capture 12):

Request: `POST /reviews`

```json
{
  "booking_id": 4,
  "rating": 5.0,
  "review_text": "Excellent work, finished on time and very professional.",
  "is_anonymous": false
}
```

Status 201:

```json
{
  "id": 1,
  "booking_id": 4,
  "customer_id": "e518bc7d-899e-4aae-9518-4e7bc32a80dc",
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "rating": 5.0,
  "review_text": "Excellent work, finished on time and very professional.",
  "is_anonymous": false,
  "is_flagged": false,
  "artisan_response": null,
  "artisan_responded_at": null,
  "created_at": "2026-11-18T22:07:07.005315Z",
  "updated_at": "2026-11-18T22:07:07.005315Z",
  "customer_name": "Customer One",
  "artisan_name": "Demo Artisan"
}
```

Review that trips the filter (capture 13). The customer still gets `201` and their own text back; the
only difference is `"is_flagged": true`:

Request: `POST /reviews`

```json
{
  "booking_id": 5,
  "rating": 1.0,
  "review_text": "This man na mumu, total idiot. Never again.",
  "is_anonymous": false
}
```

Status 201:

```json
{
  "id": 2,
  "booking_id": 5,
  "customer_id": "24c879e6-63d4-4fa6-b009-afe78335a4ae",
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "rating": 1.0,
  "review_text": "This man na mumu, total idiot. Never again.",
  "is_anonymous": false,
  "is_flagged": true,
  "artisan_response": null,
  "artisan_responded_at": null,
  "created_at": "2026-11-18T22:07:26.134379Z",
  "updated_at": "2026-11-18T22:07:26.134379Z",
  "customer_name": "Customer Two",
  "artisan_name": "Demo Artisan"
}
```

`flag_reason` / `flag_source` are **not** part of this response (or any non-admin response).

### What each person sees

| Who | Sees the hidden review? | How |
|---|---|---|
| The customer who wrote it | yes | `GET /reviews/booking/{booking_id}` returns it, `is_flagged: true` (captures 15, 47) |
| The artisan | **no** | `GET /reviews/booking/{booking_id}` answers **404** `{"detail": "Review not found for this booking"}` (capture 45), exactly like a booking with no review. `PATCH /reviews/{id}/respond` answers 404 `{"detail": "Review not found"}` (capture 46) and nothing is sent to the customer. They get no push when the review is hidden. |
| Everyone else | no | absent from `GET /reviews/artisan/{artisan_id}` and excluded from every count (captures 16, 17) |

So an artisan's app must treat a 404 on the booking-review call as "no review (yet)". Capture 48
shows the same call returning 200 for a visible review. If an admin later **restores** a hidden review,
the artisan then receives the normal "New review" push (`event: review_received`) and can read and
reply to it.

Capture 15, status 200 (customer reading their own hidden review):

```json
{
  "id": 2,
  "booking_id": 5,
  "customer_id": "24c879e6-63d4-4fa6-b009-afe78335a4ae",
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "rating": 1.0,
  "review_text": "This man na mumu, total idiot. Never again.",
  "is_anonymous": false,
  "is_flagged": true,
  "artisan_response": null,
  "artisan_responded_at": null,
  "created_at": "2026-11-18T22:07:26.134379Z",
  "updated_at": "2026-11-18T22:07:26.134379Z",
  "customer_name": "Customer Two",
  "artisan_name": "Demo Artisan"
}
```

### Public listing and aggregates exclude hidden reviews

Three reviews exist for this artisan (5★ clean, 1★ hidden, 3★ clean). `GET /reviews/artisan/{artisan_id}`
(capture 16, status 200) lists two; `total` and `average_rating` ignore the hidden one:

```json
{
  "reviews": [
    {
      "id": 3,
      "booking_id": 6,
      "customer_id": "6e254903-d37c-4255-bb49-4313a27f9d16",
      "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
      "rating": 3.0,
      "review_text": "Decent job, a bit slow but the sink is fixed.",
      "is_anonymous": false,
      "is_flagged": false,
      "artisan_response": null,
      "artisan_responded_at": null,
      "created_at": "2026-11-18T22:07:26.171264Z",
      "updated_at": "2026-11-18T22:07:26.171264Z",
      "customer_name": "Customer Three",
      "artisan_name": "Demo Artisan"
    },
    {
      "id": 1,
      "booking_id": 4,
      "customer_id": "e518bc7d-899e-4aae-9518-4e7bc32a80dc",
      "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
      "rating": 5.0,
      "review_text": "Excellent work, finished on time and very professional.",
      "is_anonymous": false,
      "is_flagged": false,
      "artisan_response": null,
      "artisan_responded_at": null,
      "created_at": "2026-11-18T22:07:07.005315Z",
      "updated_at": "2026-11-18T22:07:07.005315Z",
      "customer_name": "Customer One",
      "artisan_name": "Demo Artisan"
    }
  ],
  "total": 2,
  "average_rating": 4.0,
  "rating_distribution": {
    "1": 0,
    "2": 0,
    "3": 1,
    "4": 0,
    "5": 1
  }
}
```

`GET /reviews/artisan/{artisan_id}/stats` (capture 17):

```json
{
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "total_reviews": 2,
  "average_rating": 4.0,
  "rating_distribution": {
    "1": 0,
    "2": 0,
    "3": 1,
    "4": 0,
    "5": 1
  },
  "total_jobs_completed": 3
}
```

And the figures cached on the artisan profile (the ones search and profile screens use) agree with
them (capture 18, `average_rating` 4.0, `total_ratings` 2):

```json
{
  "average_rating": 4.0,
  "total_ratings": 2,
  "total_jobs_completed": 3,
  "response_time_avg_minutes": 33,
  "acceptance_rate": 0.0
}
```

### UX instructions

- After submitting, **show the normal "review submitted" state**, even if `is_flagged` is `true`.
  Do not tell the reviewer they were flagged or name the filter (that teaches people to dodge it).
  If you want a hint at all, a neutral "Your review is being checked and may take a little longer to
  appear" on the customer's own copy is acceptable.
- The artisan's screen for a booking's review must tolerate the 404 above (hidden or missing review look the same).
- Do not read `is_flagged` on public lists to decide anything: public endpoints only ever return `false`.
- Ratings can change after the fact: an admin can hide or restore a review later, which moves the
  artisan's average and count. Do not cache them for long.
- `total_jobs_completed` (visible in the stats bodies) is a separate pre-existing counter, not touched here.

---

## 3. Report a review

### What it is, in the app's terms

A "Report" action on a review. Any signed-in user can report a review **except its own author**. It
sends the review to the moderators' queue. **A report never hides a review by itself**, so the review
stays visible and keeps counting until an admin decides. One report per user per review, ever.

Reasons: `abusive`, `spam`, `fake`, `other`. `details` is optional free text, max 500 characters.

### `POST /reviews/{review_id}/report` (authenticated)

Success (capture 20):

Request: `POST /reviews/1/report`

```json
{
  "reason": "fake",
  "details": "I do not know this customer."
}
```

Status 201:

```json
{
  "review_id": 1,
  "reported": true
}
```

### Every error the app must handle

| Case | Capture | Status | Body |
|---|---|---|---|
| No token | 19 | 403 | `{"detail": "Not authenticated"}` (a **plain string** `detail`, and **403 not 401**) |
| Already reported by this user | 21 | 409 | `{"detail": {"code": "already_reported", "message": "You have already reported this review."}}` |
| Reporting your own review | 22 | 403 | `{"detail": {"code": "cannot_report_own_review", "message": "You cannot report your own review."}}` |
| Review does not exist | 23 | 404 | `{"detail": {"code": "review_not_found", "message": "Review not found"}}` |
| Per-user hourly cap reached | 26 | 429 | `{"detail": {"code": "report_rate_limited", "message": "You have reported too many reviews recently. Please try again later."}}` |

Invalid `reason` (capture 24, status 422) uses FastAPI's standard validation shape, which is
**different** from the `{"code","message"}` errors above (here `detail` is a list):

```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": [
        "body",
        "reason"
      ],
      "msg": "Input should be 'abusive', 'spam', 'fake' or 'other'",
      "input": "i dislike it",
      "ctx": {
        "expected": "'abusive', 'spam', 'fake' or 'other'"
      }
    }
  ]
}
```

Capture 26 ran with the cap lowered to 2 (default is 10 per user per hour). Once the user is under the
cap again (an hour after their oldest report) reporting works again.

A second, per-IP limit (default 30 per hour) also exists as a backstop. Its 429 body for this endpoint
was **NOT VERIFIED LIVE** (it is covered by an automated test, but its body is produced by the app-wide
rate-limit handler and was not captured for this route). Treat any `429` on this endpoint as "slow down".

### UX instructions

- Show "Report" on every review **except** the viewer's own (`review.customer_id == current user id`).
  The server also refuses it (403 `cannot_report_own_review`).
- There is **no field telling you whether the current user already reported a review** (NOT available
  yet, see follow-ups). So handle `409 already_reported` as a friendly "You've already reported this
  review", not as an error screen.
- On `201`, show "Thanks, our team will take a look". **Do not remove the review from the list**: it is
  still public until a moderator acts.
- On `429 report_rate_limited`, show the `message` text.

---

## 4. Admin moderation (admin app / web only)

All admin routes require an admin token. A non-admin gets 403, a missing token also 403.

| Case | Capture | Status | Body |
|---|---|---|---|
| No token | 28 | 403 | `{"detail": "Not authenticated"}` |
| Signed-in non-admin | 29 | 403 | `{"detail": "Admin access required"}` |

### `GET /admin/reviews`: the moderation queue

Query params: `queue` = `needs_attention` (default; hidden OR has open reports), `flagged` (hidden),
`reported` (has open user reports); `artisan_id` (optional UUID); `page`, `page_size`. A bad `queue`
value is a 422. Most-reported first, then newest.

Default queue (capture 30, status 200):

```json
{
  "items": [
    {
      "id": 3,
      "booking_id": 6,
      "rating": 3.0,
      "review_text": "Decent job, a bit slow but the sink is fixed.",
      "is_anonymous": false,
      "customer_id": "6e254903-d37c-4255-bb49-4313a27f9d16",
      "customer_name": "Customer Three",
      "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
      "artisan_name": "Demo Artisan",
      "is_flagged": false,
      "flag_source": null,
      "flag_reason": null,
      "flagged_at": null,
      "open_report_count": 1,
      "created_at": "2026-11-18T22:07:26.171264Z"
    },
    {
      "id": 2,
      "booking_id": 5,
      "rating": 1.0,
      "review_text": "This man na mumu, total idiot. Never again.",
      "is_anonymous": false,
      "customer_id": "24c879e6-63d4-4fa6-b009-afe78335a4ae",
      "customer_name": "Customer Two",
      "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
      "artisan_name": "Demo Artisan",
      "is_flagged": true,
      "flag_source": "auto",
      "flag_reason": "Automatic filter: abusive language (en, pcm)",
      "flagged_at": "2026-11-18T22:07:26.142629Z",
      "open_report_count": 1,
      "created_at": "2026-11-18T22:07:26.134379Z"
    },
    {
      "id": 1,
      "booking_id": 4,
      "rating": 5.0,
      "review_text": "Excellent work, finished on time and very professional.",
      "is_anonymous": false,
      "customer_id": "e518bc7d-899e-4aae-9518-4e7bc32a80dc",
      "customer_name": "Customer One",
      "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
      "artisan_name": "Demo Artisan",
      "is_flagged": false,
      "flag_source": null,
      "flag_reason": null,
      "flagged_at": null,
      "open_report_count": 1,
      "created_at": "2026-11-18T22:07:07.005315Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

`?queue=flagged` (capture 31) returns only the auto-hidden review; `?queue=reported` (capture 32) only
the reviews with open reports. Same item shape.

Item fields: `flag_source` is `"auto"` (word filter) or `"admin"`; `flag_reason` is a human-readable
string; `open_report_count` counts reports no admin has handled yet.

### `GET /admin/reviews/{review_id}`: detail with the individual reports

Capture 33, status 200. Note `reports` exists **only on this endpoint**, not in the list:

```json
{
  "id": 1,
  "booking_id": 4,
  "rating": 5.0,
  "review_text": "Excellent work, finished on time and very professional.",
  "is_anonymous": false,
  "customer_id": "e518bc7d-899e-4aae-9518-4e7bc32a80dc",
  "customer_name": "Customer One",
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "artisan_name": "Demo Artisan",
  "is_flagged": false,
  "flag_source": null,
  "flag_reason": null,
  "flagged_at": null,
  "open_report_count": 1,
  "created_at": "2026-11-18T22:07:07.005315Z",
  "reports": [
    {
      "id": 1,
      "reporter_id": "f1d46257-ef48-4b0b-b000-ce6b32ea1657",
      "reporter_name": "Other Customer",
      "reason": "fake",
      "details": "I do not know this customer.",
      "created_at": "2026-11-18T22:07:45.335404Z",
      "resolved_at": null
    }
  ]
}
```

### `POST /admin/reviews/{review_id}/flag`: hide a review

Body `{"note": "..."}`, `note` required, 3 to 500 characters (trimmed). Too short (capture 34, status 422, standard 422 shape):

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": [
        "body",
        "note"
      ],
      "msg": "String should have at least 3 characters",
      "input": "x",
      "ctx": {
        "min_length": 3
      }
    }
  ]
}
```

Success (capture 35):

Request: `POST /admin/reviews/1/flag`

```json
{
  "note": "Reporter is right: this person never used the service."
}
```

Status 200:

```json
{
  "id": 1,
  "booking_id": 4,
  "rating": 5.0,
  "review_text": "Excellent work, finished on time and very professional.",
  "is_anonymous": false,
  "customer_id": "e518bc7d-899e-4aae-9518-4e7bc32a80dc",
  "customer_name": "Customer One",
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "artisan_name": "Demo Artisan",
  "is_flagged": true,
  "flag_source": "admin",
  "flag_reason": "Reporter is right: this person never used the service.",
  "flagged_at": "2026-11-18T22:07:45.515833Z",
  "open_report_count": 0,
  "created_at": "2026-11-18T22:07:07.005315Z"
}
```

Effects, all in one transaction: the review disappears from public lists, the artisan's
`average_rating`/`total_ratings` are recalculated without it (capture 36 public list, capture 37
profile stats), open reports on it are marked handled (`open_report_count` back to 0), and an audit-log
row `review.flag` is written. Flagging an already-hidden review is allowed: it records the admin's
decision and closes its reports.

### `POST /admin/reviews/{review_id}/unflag`: restore a review

Same body. Restores a hidden review to public lists and to the artisan's rating, **or** dismisses open
reports on a review that was never hidden. Capture 38 (restore a review the admin had hidden), status 200:

```json
{
  "id": 1,
  "booking_id": 4,
  "rating": 5.0,
  "review_text": "Excellent work, finished on time and very professional.",
  "is_anonymous": false,
  "customer_id": "e518bc7d-899e-4aae-9518-4e7bc32a80dc",
  "customer_name": "Customer One",
  "artisan_id": "df631428-50f0-42d4-a868-59aaffb7a300",
  "artisan_name": "Demo Artisan",
  "is_flagged": false,
  "flag_source": null,
  "flag_reason": null,
  "flagged_at": null,
  "open_report_count": 0,
  "created_at": "2026-11-18T22:07:07.005315Z"
}
```

Public list after the restore (capture 39) shows both reviews again. Restoring an **auto-flagged**
review (capture 40, status 200) clears `flag_source`, `flag_reason` and `flagged_at`; the artisan's
figures then include it again (capture 41: `average_rating` 3.0, `total_ratings` 3).

Nothing to do (not hidden, no open reports): capture 42, status 409: `{"detail": {"code": "review_not_flagged", "message": "This review is not flagged and has no open reports."}}`.

Unknown review, on either endpoint (capture 43, status 404): `{"detail": {"code": "review_not_found", "message": "Review not found"}}`.

Every flag/unflag writes an `admin_audit_logs` row; the end state of the walk is in capture 49
(reviews, reports and audit log as stored).

### UX instructions (admin)

- Always collect a note; it is stored in the audit log.
- After flag/unflag, refresh the artisan's rating figures; they change.
- Moderators see the reviewer's real name even when the review is anonymous (`is_anonymous: true`).

---

## 5. Review states

| State | `is_flagged` | `flag_source` | Public? | Counts in rating? |
|---|---|---|---|---|
| Normal | false | null | yes | yes |
| Auto-hidden (word filter) | true | `auto` | no | no |
| Admin-hidden | true | `admin` | no | no |
| Reported, no decision yet | false | null | **yes** | yes |

Transitions: submit with a listed word → auto-hidden · admin `flag` → admin-hidden · admin `unflag` →
normal · user report → stays as it is, `open_report_count` goes up · admin `flag`/`unflag` → open
reports closed.

---

## 6. Verification table

| Behaviour | Status |
|---|---|
| `response_time_avg_minutes` null before first accept; set after accept; averages two accepts; unchanged by reject | verified live (01–07) |
| Field on stats, public profile, search results (and null shape for a newcomer) | verified live (01–11) |
| Search `response_time` sort puts null last in both directions | verified live (10, 11) |
| Field on `GET/PUT /profiles/artisans/me` and availability PATCH | NOT VERIFIED LIVE (same schema field) |
| Backfill of existing artisans | verified on a scratch DB with seeded history (not part of the HTTP walk; see SOP) |
| Clean review public and counted | verified live (12, 16–18) |
| Abusive review: 201 to reviewer, hidden, excluded from counts, visible to author | verified live (13, 15–18) |
| Artisan gets 404 on the booking-review read and on respond for a hidden review; author still reads it; visible review readable by the artisan | verified live (45–48) |
| Artisan not pushed about a hidden review; artisan pushed "New review" when an admin restores it | covered by automated tests only, NOT VERIFIED LIVE (push is disabled in the capture) |
| Report: success, duplicate, own review, 404, invalid reason, per-user cap | verified live (20–26) |
| Report by the reviewed artisan | verified live (27) |
| Report without a token | verified live (19) |
| Per-IP report limit 429 body | NOT VERIFIED LIVE (automated test only) |
| Admin queue (all three views), detail, flag, unflag, restore of auto-flagged, error cases | verified live (28–44) |
| Rating recalculation after flag / unflag | verified live (36, 37, 39, 41) |
| Audit log rows for flag / unflag | verified live (49) |
