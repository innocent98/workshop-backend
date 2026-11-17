# FE integration guide: artisan verification (+ admin API)

> **STATUS: FINAL.** Every body in section 6 was captured against the running app (scratch
> Postgres/PostGIS, fake dev data). Dojah is **stubbed at the HTTP transport** in the capture server
> (no keys), so Dojah round trips are **NOT VERIFIED LIVE**; see section 7. Files:
> [`docs/fe-captures/verification-admin/`](fe-captures/verification-admin/).

Base URL: `/api/v1`. Auth: `Authorization: Bearer <JWT>` from `/auth/login`.

## 1. What this is (FE terms)

Artisans prove their identity with **Dojah's hosted Identity widget** (NIN + selfie/liveness), which runs
inside the mobile app. **The backend never receives the NIN or the selfie.** The app only:

1. asks the backend for the widget config, 2. asks the backend to **start** a verification (gets a
`reference_id`), 3. launches the Dojah widget with that `reference_id`, 4. tells the backend it is
done (**confirm**), and 5. shows the resulting status. The backend asks Dojah for the authoritative
result server-side (and also receives Dojah's webhook), so a verification is never lost if the app dies.

Pass/fail rule: Dojah must report the NIN as verified **and** the selfie/liveness check as passed. A pass sets
the **verified badge** (`is_verified = true`, `verification_status = "verified"`). A fail sets `failed` with a
`failure_reason` and the artisan can retry (**5 starts per rolling 24h**). An admin can also verify or reject
manually (section 5).

Unverified artisans **can still use the app, take bookings and appear in search**. Only the badge and the
`verified_only` search filter depend on verification. Artisans verified before this release stay verified
(`verification_method: "legacy"`).

## 2. Artisan endpoints (artisan only; clients get 403 `Only artisans can access this endpoint`)

### 2.1 `GET /profiles/artisans/me/verification/config`
Values to initialise the Dojah widget. Plain JSON, no envelope:
```json
{ "configured": true, "app_id": "<dojah app id>", "public_key": "<dojah public key>",
  "widget_id": "<NIN widget id>", "environment": "sandbox" }
```
`configured: false` (and null ids) means the server has no Dojah credentials/widget yet: hide the flow.

### 2.2 `POST /profiles/artisans/me/verification/start`  (no body)
Mints a backend-owned `reference_id` and records a pending verification; counts as one attempt.
```json
{ "reference_id": "WC-NIN-<16 hex>", "widget_id": "<NIN widget id>", "email": "artisan@example.com",
  "attempts_remaining": 4 }
```
Launch Flutter: `DojahKyc.launch(widget_id, referenceId: reference_id, email: email)`
(per https://docs.dojah.io/api-reference/widget-sdks/flutter.md). Starting again supersedes an earlier
unfinished verification.

Errors (`{"detail": {"code", "message"}}`): 409 `already_verified`; 429 `attempts_exhausted`
(+ `retry_available_at` in `detail`); 503 `verification_unavailable` (server not configured).

### 2.3 `POST /profiles/artisans/me/verification/confirm`
Body `{"reference_id": "<from start>"}`. Call it when the widget reports finished/closed. The backend
fetches Dojah's result and returns the **status object** (2.4). Always returns promptly: if Dojah has not
finalised, you get `verification_status: "pending"`: show "verification in progress" and poll 2.4
every 5 s for up to 2 min (the webhook also resolves it server-side).
Errors: 404 `unknown_reference` (also for another user's reference), 422 body validation,
502 `provider_error` (Dojah unreachable: the verification stays pending, retry confirm or poll status),
503 `verification_unavailable`.

### 2.4 `GET /profiles/artisans/me/verification/status`
```json
{ "verification_status": "unverified", "is_verified": false, "verified_at": null,
  "verification_method": null, "failure_reason": null, "nin_last4": null, "reference_id": null,
  "attempts_used": 0, "attempts_remaining": 5, "max_attempts": 5, "window_hours": 24,
  "retry_available_at": null }
```
`verification_status`: `unverified | pending | verified | failed`. `verification_method`:
`dojah | admin | legacy | null`. `nin_last4` is only filled if Dojah returned the NIN (never the full
number). `retry_available_at` is non-null only when `attempts_remaining == 0`. While a recent verification
is pending this endpoint re-checks Dojah (bounded to a few seconds), so polling it is enough.

### 2.5 Webhook (Dojah -> backend, not for the app): `POST /verification/webhook`
Unauthenticated, HMAC-verified (`x-dojah-signature`). Returns `{"status": "ok"}`; 401 `invalid_signature`
for a bad/missing signature. The backend ignores the body except `reference_id` and re-fetches the result
from Dojah (the payload is not trusted).

## 3. Field-nesting traps

* `GET/PUT /profiles/artisans/me` also returns `verification_status` (additive; existing fields unchanged).
  `is_verified` stays the source of truth for the badge.
* The status object uses `failure_reason`; the **admin** response uses `verification_failure_reason`.
* Verification and admin errors use `detail` as an **object** `{code, message}`; most of the older API uses a
  plain **string**. Handle both.
* Public artisan profile / search results are unchanged (`is_verified` only).

## 4. UX consequences the FE must surface

* Tell the user the NIN and selfie go to Dojah, not to Workchop; we keep at most the last 4 NIN digits.
* Each **start** uses one of 5 attempts per 24h, whether or not the widget is completed. Do not auto-restart.
* After 5 starts the artisan is locked out until `retry_available_at`: offer "contact support" (an admin can
  verify manually).
* A result can arrive after the app closes (webhook): on app resume call 2.4 and update the badge.
* `failure_reason` is shown verbatim to the user.

## 5. Admin API (admin web / tooling; not for the mobile app)

All routes: `Authorization: Bearer <admin JWT>`; non-admin -> **403** `{"detail": "Admin access required"}`.
Admins log in via the normal `/auth/login`. Pagination: `page` (>=1), `page_size` (1-100, default 20);
response `{items, total, page, page_size, pages}`.

| Route | Notes |
|---|---|
| `GET /admin/users` | filters `user_type`, `is_active`, `is_admin`, `verification_status`, `q` (name/email/phone), `created_from`, `created_to` |
| `GET /admin/bookings` | filters `status`, `customer_id`, `artisan_id`, `q` (booking ref), `created_from`, `created_to` |
| `GET /admin/payments` | filters `status`, `q` (payment ref / customer email), `created_from`, `created_to` |
| `GET /admin/disputes` | unresolved disputes, oldest first |
| `POST /admin/bookings/{id}/resolve-dispute` | body `{"resolution": "release_to_artisan" \| "refund_customer", "note": "..."}` |
| `POST /admin/artisans/{user_id}/verify` | body `{"note": "optional"}` |
| `POST /admin/artisans/{user_id}/reject` | body `{"note": "required, shown to the artisan as failure_reason"}` |

Resolve-dispute behaviour:

* `release_to_artisan` is one step (200 with `booking_status: "completed"`).
* `refund_customer` is intent-first: the refund is recorded as `requested` **before** Paystack is called, and
  the booking stays `disputed` until Paystack has accepted the refund. 200 returns `refund_status`
  (`pending | processing | processed | needs-attention`), `refund_reference`, `booking_status: "cancelled"`,
  `payment_status: "refunded"`. Paystack refunds are asynchronous: `refund_status` advances later through
  Paystack's `refund.*` events (when they are wired) and a `failed` event re-opens the dispute.
* If Paystack times out or errors, the backend asks Paystack whether the refund exists (`GET /refund`): if so it
  is adopted. If it cannot tell, you get **502 `refund_unconfirmed`**: the refund stays `requested`, the booking
  stays `disputed`, and **`release_to_artisan` is refused (409 `refund_in_progress`)** so the artisan can never
  be paid money that may have been refunded. **Retry the same refund request**: it reconciles first.
* Repeating an accepted resolution returns 200 with `already_resolved: true` and never calls Paystack again.

Resolve-dispute errors (`detail.code`): 404 `booking_not_found`; 409 `not_disputed`, `already_resolved`
(the *other* resolution was already applied), `refund_in_progress` (a refund exists or is being reconciled; release
is refused), `payment_not_refundable` (funds already released / no payment); 502 `refund_unconfirmed` (outcome
unknown, retry), 502 `refund_failed` (Paystack rejected or reported the refund failed; nothing was refunded; you may
retry the refund, or release). UI instruction: on `refund_unconfirmed` show "refund pending confirmation, retry",
never "failed".

(Captured bodies: section 6.)


## 6. Captured examples

`<jwt redacted>` replaces tokens; emails are `@example.com` placeholders; ids are from the scratch DB.

### `01-login-admin.json`
`POST /auth/login` -> **200**

Request:
```json
{
  "email": "admin@example.com",
  "password": "<placeholder>"
}
```

Response:
```json
{
  "success": true,
  "message": "Login successful",
  "token": "<jwt redacted>",
  "user": {
    "id": "d926fed1-790a-4cac-bfed-1ffa63e4c80d",
    "full_name": "Demo Admin",
    "email": "admin@example.com",
    "phone_number": "+2348000000001",
    "user_type": "client",
    "profile_picture_url": null,
    "bio": null
  }
}
```

### `02-login-artisan.json`
`POST /auth/login` -> **200**

Request:
```json
{
  "email": "artisan@example.com",
  "password": "<placeholder>"
}
```

Response:
```json
{
  "success": true,
  "message": "Login successful",
  "token": "<jwt redacted>",
  "user": {
    "id": "1cc2349f-2424-4f61-b2ce-9251c5d1c125",
    "full_name": "Demo Artisan",
    "email": "artisan@example.com",
    "phone_number": "+2348000000002",
    "user_type": "artisan",
    "profile_picture_url": null,
    "bio": null
  }
}
```

### `03-login-client.json`
`POST /auth/login` -> **200**

Request:
```json
{
  "email": "client@example.com",
  "password": "<placeholder>"
}
```

Response:
```json
{
  "success": true,
  "message": "Login successful",
  "token": "<jwt redacted>",
  "user": {
    "id": "dc5cc74d-8d61-4b0c-a864-b38a796400a4",
    "full_name": "Demo Customer",
    "email": "client@example.com",
    "phone_number": "+2348000000004",
    "user_type": "client",
    "profile_picture_url": null,
    "bio": null
  }
}
```

### `04-verif-config.json`
`GET /profiles/artisans/me/verification/config` -> **200**

Response:
```json
{
  "configured": true,
  "app_id": "capture-app-id",
  "public_key": "capture-public-key",
  "widget_id": "capture-nin-widget",
  "environment": "sandbox"
}
```

### `05-verif-config-client-forbidden.json`
`GET /profiles/artisans/me/verification/config` -> **403**

Response:
```json
{
  "detail": "Only artisans can access this endpoint"
}
```

### `06-verif-status-initial.json`
`GET /profiles/artisans/me/verification/status` -> **200**

Response:
```json
{
  "verification_status": "unverified",
  "is_verified": false,
  "verified_at": null,
  "verification_method": null,
  "failure_reason": null,
  "nin_last4": null,
  "reference_id": null,
  "attempts_used": 0,
  "attempts_remaining": 5,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `07-verif-confirm-unknown-reference.json`
`POST /profiles/artisans/me/verification/confirm` -> **404**

Request:
```json
{
  "reference_id": "WC-NIN-doesnotexist"
}
```

Response:
```json
{
  "detail": {
    "code": "unknown_reference",
    "message": "No verification found for that reference"
  }
}
```

### `08-verif-start-1.json`
`POST /profiles/artisans/me/verification/start` -> **200**

Response:
```json
{
  "reference_id": "WC-NIN-1cf04fc37c1e8825",
  "widget_id": "capture-nin-widget",
  "email": "artisan@example.com",
  "attempts_remaining": 4
}
```

### `09-verif-status-pending.json`
`GET /profiles/artisans/me/verification/status` -> **200**  
_no Dojah answer scripted yet => Dojah 404 for the reference; status poll tolerates it_

Response:
```json
{
  "verification_status": "pending",
  "is_verified": false,
  "verified_at": null,
  "verification_method": null,
  "failure_reason": null,
  "nin_last4": null,
  "reference_id": "WC-NIN-1cf04fc37c1e8825",
  "attempts_used": 1,
  "attempts_remaining": 4,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `10-verif-confirm-selfie-failed.json`
`POST /profiles/artisans/me/verification/confirm` -> **200**  
_Dojah says Failed + selfie.status=false_

Request:
```json
{
  "reference_id": "WC-NIN-1cf04fc37c1e8825"
}
```

Response:
```json
{
  "verification_status": "failed",
  "is_verified": false,
  "verified_at": null,
  "verification_method": null,
  "failure_reason": "Your selfie did not match the photo on record for this NIN. Retake it in good light, facing the camera, with no hat or glasses.",
  "nin_last4": null,
  "reference_id": "WC-NIN-1cf04fc37c1e8825",
  "attempts_used": 1,
  "attempts_remaining": 4,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `11-verif-start-2.json`
`POST /profiles/artisans/me/verification/start` -> **200**

Response:
```json
{
  "reference_id": "WC-NIN-1025e2aefff8aaae",
  "widget_id": "capture-nin-widget",
  "email": "artisan@example.com",
  "attempts_remaining": 3
}
```

### `12-verif-confirm-nin-failed.json`
`POST /profiles/artisans/me/verification/confirm` -> **200**  
_Dojah says Failed + government_data.status=false_

Request:
```json
{
  "reference_id": "WC-NIN-1025e2aefff8aaae"
}
```

Response:
```json
{
  "verification_status": "failed",
  "is_verified": false,
  "verified_at": null,
  "verification_method": null,
  "failure_reason": "We could not verify this NIN. Check the number and try again.",
  "nin_last4": null,
  "reference_id": "WC-NIN-1025e2aefff8aaae",
  "attempts_used": 2,
  "attempts_remaining": 3,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `13-verif-start-3.json`
`POST /profiles/artisans/me/verification/start` -> **200**

Response:
```json
{
  "reference_id": "WC-NIN-d66496b951642494",
  "widget_id": "capture-nin-widget",
  "email": "artisan@example.com",
  "attempts_remaining": 2
}
```

### `14-verif-confirm-still-pending.json`
`POST /profiles/artisans/me/verification/confirm` -> **200**  
_Dojah says Ongoing_

Request:
```json
{
  "reference_id": "WC-NIN-d66496b951642494"
}
```

Response:
```json
{
  "verification_status": "pending",
  "is_verified": false,
  "verified_at": null,
  "verification_method": null,
  "failure_reason": null,
  "nin_last4": null,
  "reference_id": "WC-NIN-d66496b951642494",
  "attempts_used": 3,
  "attempts_remaining": 2,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `15-verif-confirm-provider-error.json`
`POST /profiles/artisans/me/verification/confirm` -> **502**  
_Dojah answers 503 (retried 3x then 502); verification stays pending_

Request:
```json
{
  "reference_id": "WC-NIN-d66496b951642494"
}
```

Response:
```json
{
  "detail": {
    "code": "provider_error",
    "message": "Could not reach the verification provider. Please try again shortly."
  }
}
```

### `16-verif-confirm-success.json`
`POST /profiles/artisans/me/verification/confirm` -> **200**  
_Dojah says Completed, NIN verified, selfie passed_

Request:
```json
{
  "reference_id": "WC-NIN-d66496b951642494"
}
```

Response:
```json
{
  "verification_status": "verified",
  "is_verified": true,
  "verified_at": "2026-11-17T13:18:16.153948Z",
  "verification_method": "dojah",
  "failure_reason": null,
  "nin_last4": "1117",
  "reference_id": "WC-NIN-d66496b951642494",
  "attempts_used": 3,
  "attempts_remaining": 2,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `17-verif-status-verified.json`
`GET /profiles/artisans/me/verification/status` -> **200**

Response:
```json
{
  "verification_status": "verified",
  "is_verified": true,
  "verified_at": "2026-11-17T13:18:16.153948Z",
  "verification_method": "dojah",
  "failure_reason": null,
  "nin_last4": "1117",
  "reference_id": "WC-NIN-d66496b951642494",
  "attempts_used": 3,
  "attempts_remaining": 2,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `18-verif-start-already-verified.json`
`POST /profiles/artisans/me/verification/start` -> **409**

Response:
```json
{
  "detail": {
    "code": "already_verified",
    "message": "Your account is already verified."
  }
}
```

### `19-artisan-profile-me.json`
`GET /profiles/artisans/me` -> **200**

Response:
```json
{
  "id": "1cc2349f-2424-4f61-b2ce-9251c5d1c125",
  "full_name": "Demo Artisan",
  "email": "artisan@example.com",
  "phone_number": "+2348000000002",
  "profile_picture_url": null,
  "bio": null,
  "user_type": "artisan",
  "location_address": null,
  "service_radius_km": 10.0,
  "hourly_rate_min": null,
  "hourly_rate_max": null,
  "years_of_experience": null,
  "specialization": null,
  "is_verified": true,
  "verified_at": "2026-11-17T13:18:16.153948Z",
  "verification_status": "verified",
  "availability_status": "available",
  "average_rating": 0.0,
  "total_ratings": 0,
  "total_jobs_completed": 0,
  "response_time_avg_minutes": null,
  "acceptance_rate": 0.0,
  "created_at": "2026-11-17T13:18:14.299166Z"
}
```

### `20-webhook-ok.json`
`POST /verification/webhook` -> **200**  
_header x-dojah-signature = HMAC-SHA256(raw body, DOJAH_WEBHOOK_SECRET) hex_

Request:
```json
{
  "reference_id": "WC-NIN-ba35e19900cdbe76",
  "verification_status": "Completed"
}
```

Response:
```json
{
  "status": "ok"
}
```

### `21-webhook-bad-signature.json`
`POST /verification/webhook` -> **401**

Request:
```json
{
  "reference_id": "WC-NIN-ba35e19900cdbe76",
  "verification_status": "Completed"
}
```

Response:
```json
{
  "detail": {
    "code": "invalid_signature",
    "message": "Bad or missing x-dojah-signature"
  }
}
```

### `22-verif-status-after-webhook.json`
`GET /profiles/artisans/me/verification/status` -> **200**

Response:
```json
{
  "verification_status": "verified",
  "is_verified": true,
  "verified_at": "2026-11-17T13:18:16.459264Z",
  "verification_method": "dojah",
  "failure_reason": null,
  "nin_last4": "1117",
  "reference_id": "WC-NIN-ba35e19900cdbe76",
  "attempts_used": 1,
  "attempts_remaining": 4,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": null
}
```

### `23-verif-start-5th.json`
`POST /profiles/artisans/me/verification/start` -> **200**  
_5th start: attempts_remaining 0_

Response:
```json
{
  "reference_id": "WC-NIN-666559b3e9052b48",
  "widget_id": "capture-nin-widget",
  "email": "artisan3@example.com",
  "attempts_remaining": 0
}
```

### `24-verif-start-attempts-exhausted.json`
`POST /profiles/artisans/me/verification/start` -> **429**

Response:
```json
{
  "detail": {
    "code": "attempts_exhausted",
    "message": "Too many verification attempts. Please try again later.",
    "retry_available_at": "2026-11-18T13:18:16.915885+00:00"
  }
}
```

### `25-admin-users-nonadmin-403.json`
`GET /admin/users` -> **403**

Response:
```json
{
  "detail": "Admin access required"
}
```

### `26-admin-users.json`
`GET /admin/users?page=1&page_size=3` -> **200**

Response:
```json
{
  "items": [
    {
      "id": "dc5cc74d-8d61-4b0c-a864-b38a796400a4",
      "full_name": "Demo Customer",
      "email": "client@example.com",
      "phone_number": "+2348000000004",
      "user_type": "client",
      "is_active": true,
      "is_admin": false,
      "is_email_verified": true,
      "created_at": "2026-11-17T13:18:15.078345Z",
      "is_verified": null,
      "verification_status": null
    },
    {
      "id": "ff166d8a-d62a-4d5f-84ce-32df24db15ac",
      "full_name": "Third Artisan",
      "email": "artisan3@example.com",
      "phone_number": "+2348000000005",
      "user_type": "artisan",
      "is_active": true,
      "is_admin": false,
      "is_email_verified": true,
      "created_at": "2026-11-17T13:18:14.824378Z",
      "is_verified": false,
      "verification_status": "pending"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 3,
  "pages": 2,
  "_trimmed": "items trimmed to 2 of 3 for this guide only"
}
```

### `27-admin-users-filter.json`
`GET /admin/users?user_type=artisan&verification_status=failed` -> **200**

Response:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

### `28-admin-users-page-size-101.json`
`GET /admin/users?page_size=101` -> **422**

Response:
```json
{
  "detail": [
    {
      "type": "less_than_equal",
      "loc": [
        "query",
        "page_size"
      ],
      "msg": "Input should be less than or equal to 100",
      "input": "101",
      "ctx": {
        "le": 100
      }
    }
  ]
}
```

### `29-admin-bookings.json`
`GET /admin/bookings?status=disputed` -> **200**

Response:
```json
{
  "items": [
    {
      "id": 4,
      "booking_reference": "BKG-DEMO04",
      "status": "disputed",
      "customer_id": "dc5cc74d-8d61-4b0c-a864-b38a796400a4",
      "customer_name": "Demo Customer",
      "artisan_id": "1cc2349f-2424-4f61-b2ce-9251c5d1c125",
      "artisan_name": "Demo Artisan",
      "agreed_amount": "8000.00",
      "budget_min": "5000.00",
      "budget_max": "10000.00",
      "job_date": "2026-11-18T13:18:15.106530Z",
      "payment_status": "success",
      "completion_disputed_at": "2026-11-17T10:18:15.106530Z",
      "completion_confirmed_by_client_at": null,
      "created_at": "2026-11-17T13:18:15.106148Z"
    },
    {
      "id": 2,
      "booking_reference": "BKG-DEMO02",
      "status": "disputed",
      "customer_id": "dc5cc74d-8d61-4b0c-a864-b38a796400a4",
      "customer_name": "Demo Customer",
      "artisan_id": "1cc2349f-2424-4f61-b2ce-9251c5d1c125",
      "artisan_name": "Demo Artisan",
      "agreed_amount": "8000.00",
      "budget_min": "5000.00",
      "budget_max": "10000.00",
      "job_date": "2026-11-18T13:18:15.096151Z",
      "payment_status": "success",
      "completion_disputed_at": "2026-11-17T10:18:15.096151Z",
      "completion_confirmed_by_client_at": null,
      "created_at": "2026-11-17T13:18:15.095964Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "pages": 1,
  "_trimmed": "items trimmed to 2 of 3 for this guide only"
}
```

### `30-admin-payments.json`
`GET /admin/payments?status=success&page_size=2` -> **200**

Response:
```json
{
  "items": [
    {
      "id": 4,
      "payment_reference": "PAY-DEMO04",
      "booking_id": 4,
      "booking_reference": "BKG-DEMO04",
      "status": "success",
      "amount": "8000.00",
      "platform_fee": "800.00",
      "artisan_amount": "7200.00",
      "currency": "NGN",
      "customer_email": "client@example.com",
      "paid_at": null,
      "released_at": null,
      "refunded_at": null,
      "created_at": "2026-11-17T13:18:15.106148Z"
    },
    {
      "id": 3,
      "payment_reference": "PAY-DEMO03",
      "booking_id": 3,
      "booking_reference": "BKG-DEMO03",
      "status": "success",
      "amount": "8000.00",
      "platform_fee": "800.00",
      "artisan_amount": "7200.00",
      "currency": "NGN",
      "customer_email": "client@example.com",
      "paid_at": null,
      "released_at": null,
      "refunded_at": null,
      "created_at": "2026-11-17T13:18:15.101778Z"
    }
  ],
  "total": 4,
  "page": 1,
  "page_size": 2,
  "pages": 2
}
```

### `31-admin-disputes.json`
`GET /admin/disputes` -> **200**

Response:
```json
{
  "items": [
    {
      "booking_id": 1,
      "booking_reference": "BKG-DEMO01",
      "customer_id": "dc5cc74d-8d61-4b0c-a864-b38a796400a4",
      "customer_name": "Demo Customer",
      "artisan_id": "1cc2349f-2424-4f61-b2ce-9251c5d1c125",
      "artisan_name": "Demo Artisan",
      "agreed_amount": "8000.00",
      "payment_status": "success",
      "disputed_at": "2026-11-17T10:18:15.082681Z",
      "dispute_reason": "Leak is still there",
      "completion_notes": "Sink replaced"
    },
    {
      "booking_id": 2,
      "booking_reference": "BKG-DEMO02",
      "customer_id": "dc5cc74d-8d61-4b0c-a864-b38a796400a4",
      "customer_name": "Demo Customer",
      "artisan_id": "1cc2349f-2424-4f61-b2ce-9251c5d1c125",
      "artisan_name": "Demo Artisan",
      "agreed_amount": "8000.00",
      "payment_status": "success",
      "disputed_at": "2026-11-17T10:18:15.096151Z",
      "dispute_reason": "Leak is still there",
      "completion_notes": "Sink replaced"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "pages": 1,
  "_trimmed": "items trimmed to 2 of 3 for this guide only"
}
```

### `32-resolve-release.json`
`POST /admin/bookings/1/resolve-dispute` -> **200**

Request:
```json
{
  "resolution": "release_to_artisan",
  "note": "Photos show the sink replaced"
}
```

Response:
```json
{
  "booking_id": 1,
  "booking_status": "completed",
  "resolution": "release_to_artisan",
  "note": "Photos show the sink replaced",
  "resolved_by": "d926fed1-790a-4cac-bfed-1ffa63e4c80d",
  "resolved_at": "2026-11-17T13:18:17.110254Z",
  "payment_status": "success",
  "refund_reference": null,
  "refund_status": null,
  "already_resolved": false
}
```

### `33-resolve-release-repeat.json`
`POST /admin/bookings/1/resolve-dispute` -> **200**  
_same resolution again: idempotent_

Request:
```json
{
  "resolution": "release_to_artisan",
  "note": "Photos show the sink replaced"
}
```

Response:
```json
{
  "booking_id": 1,
  "booking_status": "completed",
  "resolution": "release_to_artisan",
  "note": "Photos show the sink replaced",
  "resolved_by": "d926fed1-790a-4cac-bfed-1ffa63e4c80d",
  "resolved_at": "2026-11-17T13:18:17.110254Z",
  "payment_status": "success",
  "refund_reference": null,
  "refund_status": null,
  "already_resolved": true
}
```

### `34-resolve-conflict.json`
`POST /admin/bookings/1/resolve-dispute` -> **409**  
_different resolution after the fact_

Request:
```json
{
  "resolution": "refund_customer",
  "note": "xxx"
}
```

Response:
```json
{
  "detail": {
    "code": "already_resolved",
    "message": "This dispute was already resolved as 'release_to_artisan'."
  }
}
```

### `35-resolve-refund.json`
`POST /admin/bookings/2/resolve-dispute` -> **200**  
_Paystack POST /refund is STUBBED in capture_server.py (needs a real transaction): NOT VERIFIED LIVE against Paystack_

Request:
```json
{
  "resolution": "refund_customer",
  "note": "Artisan never showed up"
}
```

Response:
```json
{
  "booking_id": 2,
  "booking_status": "cancelled",
  "resolution": "refund_customer",
  "note": "Artisan never showed up",
  "resolved_by": "d926fed1-790a-4cac-bfed-1ffa63e4c80d",
  "resolved_at": "2026-11-17T13:18:17.154096Z",
  "payment_status": "refunded",
  "refund_reference": "3141592",
  "refund_status": "pending",
  "already_resolved": false
}
```

### `36-resolve-refund-unconfirmed.json`
`POST /admin/bookings/4/resolve-dispute` -> **502**  
_Paystack stub: request times out and the refund lookup finds nothing => outcome unknown_

Request:
```json
{
  "resolution": "refund_customer",
  "note": "Customer proved the job was never done"
}
```

Response:
```json
{
  "detail": {
    "code": "refund_unconfirmed",
    "message": "Paystack did not answer and no refund was found. The refund is recorded as requested, so the payment cannot be released; retry to reconcile."
  }
}
```

### `37-resolve-release-blocked-by-refund-intent.json`
`POST /admin/bookings/4/resolve-dispute` -> **409**  
_a refund intent exists, so paying the artisan is refused (double-spend guard)_

Request:
```json
{
  "resolution": "release_to_artisan",
  "note": "Changed my mind"
}
```

Response:
```json
{
  "detail": {
    "code": "refund_in_progress",
    "message": "A refund exists for this booking (confirmed, or its outcome is still being reconciled), so the payment cannot be released to the artisan."
  }
}
```

### `38-resolve-refund-retry.json`
`POST /admin/bookings/4/resolve-dispute` -> **200**  
_retry after the outage_

Request:
```json
{
  "resolution": "refund_customer",
  "note": "Customer proved the job was never done"
}
```

Response:
```json
{
  "booking_id": 4,
  "booking_status": "cancelled",
  "resolution": "refund_customer",
  "note": "Customer proved the job was never done",
  "resolved_by": "d926fed1-790a-4cac-bfed-1ffa63e4c80d",
  "resolved_at": "2026-11-17T13:18:17.178869Z",
  "payment_status": "refunded",
  "refund_reference": "3141592",
  "refund_status": "pending",
  "already_resolved": false
}
```

### `39-resolve-not-disputed.json`
`POST /admin/bookings/3/resolve-dispute` -> **409**  
_booking 3 is PAID, not disputed_

Response:
```json
{
  "detail": {
    "code": "not_disputed",
    "message": "Booking has no open dispute."
  }
}
```

### `40-resolve-bad-body.json`
`POST /admin/bookings/1/resolve-dispute` -> **422**

Response:
```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": [
        "body",
        "resolution"
      ],
      "msg": "Input should be 'release_to_artisan' or 'refund_customer'",
      "input": "nope",
      "ctx": {
        "expected": "'release_to_artisan' or 'refund_customer'"
      }
    },
    {
      "type": "string_too_short",
      "loc": [
        "body",
        "note"
      ],
      "msg": "String should have at least 3 characters",
      "input": "",
      "ctx": {
        "min_length": 3
      }
    }
  ]
}
```

### `41-admin-disputes-after.json`
`GET /admin/disputes` -> **200**

Response:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

### `42-admin-reject-artisan.json`
`POST /admin/artisans/ff166d8a-d62a-4d5f-84ce-32df24db15ac/reject` -> **200**

Request:
```json
{
  "note": "ID photo unreadable"
}
```

Response:
```json
{
  "user_id": "ff166d8a-d62a-4d5f-84ce-32df24db15ac",
  "is_verified": false,
  "verification_status": "failed",
  "verification_method": "admin",
  "verified_at": null,
  "verification_failure_reason": "ID photo unreadable"
}
```

### `43-admin-verify-artisan.json`
`POST /admin/artisans/ff166d8a-d62a-4d5f-84ce-32df24db15ac/verify` -> **200**

Request:
```json
{
  "note": "Verified in person"
}
```

Response:
```json
{
  "user_id": "ff166d8a-d62a-4d5f-84ce-32df24db15ac",
  "is_verified": true,
  "verification_status": "verified",
  "verification_method": "admin",
  "verified_at": "2026-11-17T13:18:17.239005Z",
  "verification_failure_reason": null
}
```

### `44-verif-status-after-admin-verify.json`
`GET /profiles/artisans/me/verification/status` -> **200**

Response:
```json
{
  "verification_status": "verified",
  "is_verified": true,
  "verified_at": "2026-11-17T13:18:17.239005Z",
  "verification_method": "admin",
  "failure_reason": null,
  "nin_last4": null,
  "reference_id": "WC-NIN-666559b3e9052b48",
  "attempts_used": 5,
  "attempts_remaining": 0,
  "max_attempts": 5,
  "window_hours": 24,
  "retry_available_at": "2026-11-18T13:18:16.915885Z"
}
```

## 7. Verification table

| Behaviour | Status |
|---|---|
| `config`, `start`, `confirm` (selfie failed / NIN failed / still pending / success / provider error 502), `status`, 409 already verified, 429 attempts exhausted, 403 for clients, 404 unknown reference | **verified live** against the running app, with Dojah answers **scripted at the HTTP transport layer** (`capture_server.py`) |
| Webhook: valid HMAC-SHA256 signature applies the result; bad signature 401 | **verified live** (signature computed the way Dojah documents it) |
| Real Dojah `GET /api/v1/kyc/verification` round trip (auth with the real key, real `entity` response, real widget `reference_id` hand-off, real webhook delivery and signature) | **NOT VERIFIED LIVE**: no Dojah keys here. Request/headers/statuses follow https://docs.dojah.io/api-reference/verifications/get-verification.md and the webhook page https://docs.dojah.io/api-reference/core-concepts/webhooks-signatures.md ; the nested `entity.data.government_data` / `selfie` parsing follows the owner's Timpbills integration (itself never used in production). Unit-tested only against mocked HTTP |
| Flutter widget hand-off `DojahKyc.launch(widgetId, referenceId:, email:)` | **NOT VERIFIED**: from https://docs.dojah.io/api-reference/widget-sdks/flutter.md (mobile owns this) |
| Whether the widget result includes the NIN (for `nin_last4`) | **NOT VERIFIED**: parsed if present, otherwise `nin_last4` stays null |
| Sandbox host `sandbox.dojah.io` for these calls | per https://docs.dojah.io/api-reference/get-started/environments.md ; **NOT VERIFIED LIVE** |
| `GET/PUT /profiles/artisans/me` now include `verification_status` | **verified live** |
| 5xx retry/backoff, 4xx not retried, timeouts, non-JSON body | tests only (mocked transport) |
| Admin lists: 403 for non-admin, filters, `page_size` cap (422 above 100) | **verified live** |
| Disputes list, release_to_artisan, idempotent repeat, conflicting resolution (409), not_disputed (409), validation (422) | **verified live** |
| refund_customer, refund unconfirmed (502) + release blocked (409 `refund_in_progress`) + retry | DB/state/notification and the reconcile logic **verified live**; the Paystack `POST /refund` and `GET /refund` calls are **stubbed** in `capture_server.py` (NOT VERIFIED LIVE against Paystack) |
| `refund_failed` 502, definite rejection rollback, reconciliation of "already reversed", refund.* event handling (`handle_refund_event`, no route wired yet; payload keys NOT VERIFIED against a live Paystack webhook) | tests only |
| Admin verify / reject artisan; an admin decision wins over a late Dojah result | verify/reject **verified live**; the precedence rule is tests only |
| First admin via `scripts/create_admin.py`, then normal `/auth/login` and an admin call | **verified live** (earlier run; the script has since gained the refuse-to-promote-existing-account rule, covered by tests) |
| Push/in-app notifications after a resolution or verification result | **not verified live** (FCM disabled); asserted in tests via a fake notifier |
