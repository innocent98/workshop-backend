# FE integration guide: account deletion (`DELETE /api/v1/auth/me`)

> **STATUS: FINAL.** Bodies in section 5 were captured against the running app (scratch Postgres/PostGIS,
> Redis, fake dev data) in `docs/fe-captures/account-deletion/`. Google/Firebase token verification is
> **stubbed** in the capture server (no Firebase credentials), see section 6.

Apple App Store and Google Play require in-app account deletion. This is the endpoint behind the "Delete my
account" screen. It **soft-deletes and anonymises** the account (financial records stay for accounting).

## 1. Request

`DELETE /api/v1/auth/me` with `Authorization: Bearer <JWT>` and a JSON body (re-authentication):

| Account type | Body | Notes |
|---|---|---|
| Has a password (email sign-up, or Google linked to a password) | `{"password": "<current password>"}` | |
| Google-only (no password) | `{"google_token": "<fresh Firebase ID token>"}` | Re-run the Google sign-in in the app right before calling, to get a token minted in the **last 5 minutes** for the **same** Google account |

Some HTTP clients/proxies drop bodies on `DELETE`: Flutter `http.delete(url, headers:, body:)` and Dio
(`data:`) send it; if you ever see `password_required` for a body you did send, check the client.
Rate limit: 10 attempts / 15 min / IP (429).

## 2. Success: 200

```json
{ "success": true, "message": "Your account has been deleted." }
```
**Then the app must immediately clear its local session** (token, cached profile, push token) and go to the
signed-out/welcome screen. The token you used is revoked, and every other token for that account stops working
(the account is inactive). Logging in again returns 401 `Invalid email or password`.

What the backend did: the user is inactive and anonymised (name `Deleted User`, placeholder email/phone, no
password/Google link, no bio/photo/location); push devices, notifications, OTPs, services selection and
portfolio rows are removed (portfolio and profile images are deleted from storage in the background); artisan
profile details cleared and set offline (no longer in search); pending bookings are closed (customer's -> cancelled,
artisan's -> rejected, other side notified). Bookings, payments and withdrawals stay, linked to the anonymised
user. The same email/phone can be registered again.

## 3. Errors (`detail` is an object `{code, message}`, except 401/403 from auth, which are plain strings)

| HTTP | `detail.code` | Meaning / what the app does |
|---|---|---|
| 400 | `password_required` | no password sent for a password account: show the password field |
| 400 | `reauth_required` | Google-only account and no `google_token`: run Google sign-in again, retry |
| 403 | `invalid_password` | wrong password: inline error (does not log the user out) |
| 403 | `reauth_required` | Google token older than 5 minutes: re-run Google sign-in, retry |
| 403 | `invalid_reauth` | Google token invalid or for a different Google account |
| 409 | `admin_account` | admin accounts cannot be deleted from the app |
| 409 | `active_bookings` / `unfinished_withdrawal` / `wallet_balance` | **blocked**, see below |
| 401/403 | (string) | not authenticated / revoked token: standard handling |

### Blocked: 409
`detail.code` is the first blocker; **`detail.blockers` lists all of them** (show every one):
```json
{"detail": {"code": "active_bookings", "message": "...",
  "blockers": [{"code": "active_bookings", "count": 1, "message": "..."},
               {"code": "wallet_balance", "amount": "7200.00", "message": "..."}]}}
```
| Blocker | Cause | What the user must do |
|---|---|---|
| `active_bookings` (`count`) | bookings (as customer **or** artisan) in accepted, paid, in-progress or disputed state | finish/cancel them, or wait for the dispute to be resolved |
| `unfinished_withdrawal` (`count`) | a withdrawal is processing or needs review | wait for it to finish |
| `wallet_balance` (`amount`, string, Naira) | completed jobs whose money has not been withdrawn (withdrawable now **or** still inside the client's confirmation window) | withdraw the earnings first (wallet screen) |

## 4. UX instructions

* Confirm twice in the UI (destructive and permanent: the account cannot be restored). Say what is kept
  (transaction records, anonymised) and what is erased.
* Call the endpoint only after the password / Google re-auth step succeeds in the UI flow; do **not** pre-check
  by calling it with an empty body.
* On `409`, do not offer retry; list the blockers with the action for each and a link to the relevant screen.
* After a `200`, do not call any other authenticated endpoint (they will 401).

## 5. Captured examples

`<jwt redacted>` replaces tokens; emails are `@example.com` placeholders; ids are from the scratch DB.

### `01-login-artisan.json`
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
    "id": "d95eaaa4-92ae-4310-bdfc-1c6ab4f3f944",
    "full_name": "Demo Artisan",
    "email": "artisan@example.com",
    "phone_number": "+2348000000002",
    "user_type": "artisan",
    "profile_picture_url": null,
    "bio": null
  }
}
```

### `02-login-blocked.json`
`POST /auth/login` -> **200**

Request:
```json
{
  "email": "blocked@example.com",
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
    "id": "7e9e63ff-7b39-4faf-b6de-0086fbbeab13",
    "full_name": "Blocked Customer",
    "email": "blocked@example.com",
    "phone_number": "+2348000000003",
    "user_type": "client",
    "profile_picture_url": null,
    "bio": null
  }
}
```

### `03-login-leaving.json`
`POST /auth/login` -> **200**

Request:
```json
{
  "email": "leaving@example.com",
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
    "id": "e1d4d263-ff52-4915-90de-2ce92267ffca",
    "full_name": "Leaving Customer",
    "email": "leaving@example.com",
    "phone_number": "+2348000000004",
    "user_type": "client",
    "profile_picture_url": null,
    "bio": "About me"
  }
}
```

### `04-login-admin.json`
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
    "id": "be310c3f-adf9-48df-9674-c905f41dec83",
    "full_name": "Demo Admin",
    "email": "admin@example.com",
    "phone_number": "+2348000000005",
    "user_type": "client",
    "profile_picture_url": null,
    "bio": null
  }
}
```

### `05-delete-no-auth.json`
`DELETE /auth/me` -> **403**

Request:
```json
{
  "password": "<placeholder>"
}
```

Response:
```json
{
  "detail": "Not authenticated"
}
```

### `06-delete-password-required.json`
`DELETE /auth/me` -> **400**

Request:
```json
{}
```

Response:
```json
{
  "detail": {
    "code": "password_required",
    "message": "Enter your password to delete your account."
  }
}
```

### `07-delete-wrong-password.json`
`DELETE /auth/me` -> **403**

Request:
```json
{
  "password": "not-my-password"
}
```

Response:
```json
{
  "detail": {
    "code": "invalid_password",
    "message": "The password is incorrect."
  }
}
```

### `08-delete-blocked-active-booking.json`
`DELETE /auth/me` -> **409**  
_customer with an ACCEPTED booking_

Request:
```json
{
  "password": "Placeholder-pw-1"
}
```

Response:
```json
{
  "detail": {
    "code": "active_bookings",
    "message": "Your account cannot be deleted yet: Finish or cancel your accepted, paid, in-progress and disputed bookings.",
    "blockers": [
      {
        "code": "active_bookings",
        "count": 1,
        "message": "Finish or cancel your accepted, paid, in-progress and disputed bookings."
      }
    ]
  }
}
```

### `09-delete-blocked-artisan.json`
`DELETE /auth/me` -> **409**  
_artisan: active booking + completed job with earnings not yet withdrawn_

Request:
```json
{
  "password": "Placeholder-pw-1"
}
```

Response:
```json
{
  "detail": {
    "code": "active_bookings",
    "message": "Your account cannot be deleted yet: Finish or cancel your accepted, paid, in-progress and disputed bookings. Withdraw your earnings first (money awaiting confirmation counts too).",
    "blockers": [
      {
        "code": "active_bookings",
        "count": 1,
        "message": "Finish or cancel your accepted, paid, in-progress and disputed bookings."
      },
      {
        "code": "wallet_balance",
        "amount": "7200.00",
        "message": "Withdraw your earnings first (money awaiting confirmation counts too)."
      }
    ]
  }
}
```

### `10-delete-admin-refused.json`
`DELETE /auth/me` -> **409**

Request:
```json
{
  "password": "Placeholder-pw-1"
}
```

Response:
```json
{
  "detail": {
    "code": "admin_account",
    "message": "Admin accounts cannot be deleted from the app."
  }
}
```

### `11-delete-google-reauth-required.json`
`DELETE /auth/me` -> **400**  
_Google-only account, no token sent_

Request:
```json
{}
```

Response:
```json
{
  "detail": {
    "code": "reauth_required",
    "message": "Sign in with Google again to delete your account."
  }
}
```

### `12-delete-google-stale-token.json`
`DELETE /auth/me` -> **403**  
_Firebase verification STUBBED (NOT VERIFIED LIVE against Firebase)_

Request:
```json
{
  "google_token": "stale"
}
```

Response:
```json
{
  "detail": {
    "code": "reauth_required",
    "message": "Sign in with Google again to delete your account."
  }
}
```

### `13-delete-google-wrong-account.json`
`DELETE /auth/me` -> **403**

Request:
```json
{
  "google_token": "other"
}
```

Response:
```json
{
  "detail": {
    "code": "invalid_reauth",
    "message": "That Google account does not match this account."
  }
}
```

### `14-delete-google-success.json`
`DELETE /auth/me` -> **200**  
_Firebase verification STUBBED (NOT VERIFIED LIVE against Firebase)_

Request:
```json
{
  "google_token": "fresh"
}
```

Response:
```json
{
  "success": true,
  "message": "Your account has been deleted."
}
```

### `15-delete-success.json`
`DELETE /auth/me` -> **200**  
_customer: pending booking auto-cancelled, completed+paid history kept_

Request:
```json
{
  "password": "Placeholder-pw-1"
}
```

Response:
```json
{
  "success": true,
  "message": "Your account has been deleted."
}
```

### `16-delete-repeat-same-token.json`
`DELETE /auth/me` -> **401**  
_the token was revoked by the first delete_

Request:
```json
{
  "password": "Placeholder-pw-1"
}
```

Response:
```json
{
  "detail": "Token has been revoked. Please login again."
}
```

### `17-me-after-delete.json`
`GET /profiles/customers/me` -> **401**  
_same (revoked) token_

Response:
```json
{
  "detail": "Token has been revoked. Please login again."
}
```

### `18-login-after-delete.json`
`POST /auth/login` -> **401**

Request:
```json
{
  "email": "leaving@example.com",
  "password": "<placeholder>"
}
```

Response:
```json
{
  "detail": "Invalid email or password"
}
```

### `19-db-state-after-delete.json`

direct DB read after the delete (not an API response)

```json
{
  "user": {
    "full_name": "Deleted User",
    "email": "deleted+e1d4d263ff52491590de2ce92267ffca@deleted.invalid",
    "phone_number": "del_e1d4d263ff52",
    "hashed_password": null,
    "bio": null,
    "location_address": null,
    "is_active": false,
    "deleted_at_set": true
  },
  "bookings_kept": [
    [
      "BKG-DEMO02",
      "cancelled",
      "8000.00"
    ],
    [
      "BKG-DEMO03",
      "completed",
      "8000.00"
    ]
  ],
  "payments_kept": [
    [
      "PAY-DEMO03",
      "released",
      "8000.00",
      "Deleted User",
      "deleted+e1d4d263ff52491590de2ce92267ffca@deleted.invalid"
    ]
  ],
  "push_devices": 0
}
```

## 6. Verification table

| Behaviour | Status |
|---|---|
| password required / wrong password / success (customer) / repeat with the revoked token / login after delete / revoked token on another endpoint | **verified live** |
| 409 blocked by an accepted booking; artisan blocked by an active booking + undrawn earnings; admin account refused | **verified live** |
| anonymisation (name, email, phone, password, bio, location), pending booking auto-cancelled, completed + paid history kept with scrubbed payment name/email, push devices removed | **verified live** (DB read in the last capture) and in tests |
| Google-only re-auth: missing / stale / wrong account / fresh token | live against the real endpoint, but Firebase ID-token verification is **stubbed** in the capture server: **NOT VERIFIED LIVE against Firebase**. The real `auth_time` claim of a Firebase ID token (seconds since epoch) is assumed from Firebase's documented token claims |
| `unfinished_withdrawal` blocker, `wallet_balance` for money still in the confirmation window, rejected pending booking for a deleted artisan, portfolio image removal from Cloudinary, every other token of the account dying | tests only |
| Other tokens of the same account (other devices) stop working | tests only (they are rejected because the account is inactive) |
