# FE integration guide: payments & wallet (withdrawals)

Audience: Flutter app. Backend change set: branch `fix/payments-payout-safety`. Every body below was copied
from a real response captured against the running app (`scripts/capture_payments_wallet.py`, raw files in
`docs/fe-integration-captures/payments-wallet/`). **The Paystack REST API was a local stand-in** (the app's real
`PaystackService` code ran against it), so nothing here has touched real Paystack. See the verification table.
All IDs, references, names and account numbers are placeholders.

## 0. Read this first (traps)

* **Money is a JSON string**, not a number: `"amount": "9000.00"`. Zero can appear as `"0"` (not `"0.00"`) in
  `/wallet/balance` (`total_earned`, `lifetime_earnings`, `pending_withdrawal`). Parse with a decimal type.
* **The amount you request is not always the amount you get.** A payout is made of whole completed jobs. The
  response `amount` is what is actually being transferred. **Show `amount`, never the number the user typed.**
* **Send an `Idempotency-Key` header on every payout request** (a fresh UUID per user intent, reused only if you
  retry that same tap). It makes double taps/timeouts safe: the repeat returns the same withdrawal with
  `idempotent_replay: true`.
* **`pending_release` means "withdrawable right now"** (unchanged name/meaning). `available_balance` is the same
  number under a clearer name. Money inside a withdrawal that is still processing is `pending_withdrawal` and is
  *not* in `pending_release`.
* A payout is only final when `withdrawals[].status` becomes `success` (bank transfer confirmed). `processing`
  can take minutes; `failed` / `reversed` mean the money is back in the available balance.
* `payouts[]` keeps its old per-payment shape and only lists money that really reached the bank.
  Processing/failed withdrawals are in the new `withdrawals[]` list.
* `POST /payments/{id}/release` now always returns 403. Do not call it.
* Error bodies are `{"detail": "<message>"}`; `detail` is safe to show to the user. Paystack errors are never
  passed through (the user sees a generic message).

## 1. Paying for a booking (customer)

Unchanged contract; the fixes are server-side (non-card channels no longer crash, wrong amounts are never
settled, a customer who simply has not paid yet is no longer marked failed).

`POST /api/v1/payments/initialize`  →  **201**  (capture: `01-initialize-payment.json`)

Request body:
```json
{
  "booking_id": 4
}
```
Response:
```json
{
  "id": 5,
  "payment_reference": "PAY-26321125320-416",
  "booking_id": 4,
  "authorization_url": "https://checkout.paystack.com/placeholder",
  "amount": "15000.00",
  "platform_fee": "1500.00",
  "artisan_amount": "13500.00",
  "status": "pending",
  "created_at": "2026-11-17T12:53:20.344740Z"
}
```

After the Paystack checkout, call verify (or just poll the booking). The webhook and verify share one code path,
so whichever arrives first wins and the other is a no-op:

`GET /api/v1/payments/verify/PAY-26321125320-416`  →  **200**  (capture: `04-verify-after-webhook.json`)

Response:
```json
{
  "payment_reference": "PAY-26321125320-416",
  "status": "success",
  "amount": "15000.00",
  "paid": true,
  "message": "Payment already verified"
}
```

* `paid: false` with message `Payment not completed yet` means the customer has not finished paying: keep polling
  (every 3 s for ~1 minute, then stop and let them retry). It does **not** mean failed.
* `paid: false` with `Payment amount could not be confirmed. Please contact support.` = amount/currency mismatch
  (extremely rare): show a support message, do not retry.
* The booking only moves `accepted → paid`; it never moves backwards.
* The two `paid: false` messages above are **NOT VERIFIED LIVE** (they need a real unpaid/abandoned Paystack
  transaction); they are covered by `tests/api/test_payments_webhook.py` and `tests/services/test_payment_service.py`.

## 2. Wallet reads (artisan only; customers get 403)

### GET /wallet/balance
`GET /api/v1/wallet/balance`  →  **200**  (capture: `07-wallet-balance-before.json`)

Response:
```json
{
  "total_earned": "0",
  "pending_release": "54000.00",
  "total_platform_fee": "7500.00",
  "total_jobs_completed": 3,
  "total_jobs_paid": 4,
  "lifetime_earnings": "0",
  "available_balance": "54000.00",
  "pending_withdrawal": "0",
  "min_payout": "5000.00"
}
```

New (additive) fields: `available_balance`, `pending_withdrawal`, `min_payout`. All previous fields are present.
`total_earned` / `lifetime_earnings` only count money that **reached the bank** (`released`).

While a withdrawal is processing:

`GET /api/v1/wallet/balance`  →  **200**  (capture: `15-wallet-balance-processing.json`)

Response:
```json
{
  "total_earned": "0",
  "pending_release": "45000.00",
  "total_platform_fee": "7500.00",
  "total_jobs_completed": 3,
  "total_jobs_paid": 4,
  "lifetime_earnings": "0",
  "available_balance": "45000.00",
  "pending_withdrawal": "9000.00",
  "min_payout": "5000.00"
}
```

After `transfer.success` (`total_earned` grows, `pending_withdrawal` returns to 0):

`GET /api/v1/wallet/balance`  →  **200**  (capture: `19-wallet-balance-after-success.json`)

Response:
```json
{
  "total_earned": "9000.00",
  "pending_release": "45000.00",
  "total_platform_fee": "7500.00",
  "total_jobs_completed": 3,
  "total_jobs_paid": 4,
  "lifetime_earnings": "9000.00",
  "available_balance": "45000.00",
  "pending_withdrawal": "0",
  "min_payout": "5000.00"
}
```


### GET /wallet/earnings
Each item gained `withdrawal_id` and `withdrawal_status` (both `null` when the payment is in no withdrawal).
First two items shown:

`GET /api/v1/wallet/earnings`  →  **200**  (capture: `08-wallet-earnings.json`)

Response:
```json
{
  "earnings": [
    {
      "payment_id": 5,
      "payment_reference": "PAY-26321125320-416",
      "booking_id": 4,
      "booking_reference": "BK-CAP-LIVE",
      "amount": "13500.00",
      "gross_amount": "15000.00",
      "platform_fee": "1500.00",
      "status": "success",
      "customer_name": "Placeholder Client",
      "service_name": "Placeholder Plumbing",
      "job_date": "2026-11-18T12:53:20.157694Z",
      "paid_at": "2026-11-17T12:53:20.381603Z",
      "released_at": null,
      "created_at": "2026-11-17T12:53:20.344740Z",
      "withdrawal_id": null,
      "withdrawal_status": null
    },
    {
      "payment_id": 1,
      "payment_reference": "PAY-CAP-1",
      "booking_id": 1,
      "booking_reference": "BK-CAP-3",
      "amount": "9000.00",
      "gross_amount": "10000.00",
      "platform_fee": "1000.00",
      "status": "success",
      "customer_name": "Placeholder Client",
      "service_name": "Placeholder Plumbing",
      "job_date": "2026-11-18T12:53:20.157694Z",
      "paid_at": "2026-11-14T12:53:20.157694Z",
      "released_at": null,
      "created_at": "2026-11-17T12:53:20.204142Z",
      "withdrawal_id": null,
      "withdrawal_status": null
    },
    {
      "...": "remaining items omitted"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "summary": {
    "total_amount": "67500.00",
    "count": 5
  }
}
```


### GET /wallet/payouts
`payouts[]` = released payments (old shape + `withdrawal_id`); `withdrawals[]` = every withdrawal, newest first.

`GET /api/v1/wallet/payouts`  →  **200**  (capture: `16-wallet-payouts-processing.json`)

Response:
```json
{
  "payouts": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "withdrawals": [
    {
      "id": 1,
      "reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
      "amount": "9000.00",
      "currency": "NGN",
      "status": "processing",
      "bank_code": "057",
      "account_number_last4": "0000",
      "account_name": "JANE PLACEHOLDER",
      "created_at": "2026-11-17T12:53:20.526255Z",
      "completed_at": null
    }
  ]
}
```

After success the payout appears per payment (`payout_reference` is `<withdrawal reference>:<payment id>`):

`GET /api/v1/wallet/payouts`  →  **200**  (capture: `20-wallet-payouts-after-success.json`)

Response:
```json
{
  "payouts": [
    {
      "payment_id": 1,
      "payment_reference": "PAY-CAP-1",
      "payout_reference": "wdr_719f912790044ddcbcd0e2baf0c531c4:1",
      "amount": "9000.00",
      "gross_amount": "10000.00",
      "platform_fee": "1000.00",
      "released_at": "2026-11-17T12:53:20.598846Z",
      "booking_reference": "BK-CAP-3",
      "customer_name": "Placeholder Client",
      "withdrawal_id": 1
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "withdrawals": [
    {
      "id": 1,
      "reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
      "amount": "9000.00",
      "currency": "NGN",
      "status": "success",
      "bank_code": "057",
      "account_number_last4": "0000",
      "account_name": "JANE PLACEHOLDER",
      "created_at": "2026-11-17T12:53:20.526255Z",
      "completed_at": "2026-11-17T12:53:20.598846Z"
    }
  ]
}
```

After a failed transfer (second withdrawal) the failed row stays visible, money is back in the balance:

`GET /api/v1/wallet/payouts`  →  **200**  (capture: `25-wallet-payouts-after-failed.json`)

Response:
```json
{
  "payouts": [
    {
      "payment_id": 1,
      "payment_reference": "PAY-CAP-1",
      "payout_reference": "wdr_719f912790044ddcbcd0e2baf0c531c4:1",
      "amount": "9000.00",
      "gross_amount": "10000.00",
      "platform_fee": "1000.00",
      "released_at": "2026-11-17T12:53:20.598846Z",
      "booking_reference": "BK-CAP-3",
      "customer_name": "Placeholder Client",
      "withdrawal_id": 1
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "withdrawals": [
    {
      "id": 2,
      "reference": "wdr_4d1ff74248904ae5853f06710e266f69",
      "amount": "18000.00",
      "currency": "NGN",
      "status": "failed",
      "bank_code": "057",
      "account_number_last4": "0000",
      "account_name": "JANE PLACEHOLDER",
      "created_at": "2026-11-17T12:53:20.650068Z",
      "completed_at": "2026-11-17T12:53:20.669413Z"
    },
    {
      "id": 1,
      "reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
      "amount": "9000.00",
      "currency": "NGN",
      "status": "success",
      "bank_code": "057",
      "account_number_last4": "0000",
      "account_name": "JANE PLACEHOLDER",
      "created_at": "2026-11-17T12:53:20.526255Z",
      "completed_at": "2026-11-17T12:53:20.598846Z"
    }
  ]
}
```


### GET /wallet/stats
`GET /api/v1/wallet/stats`  →  **200**  (capture: `21-wallet-stats-after.json`)

Response:
```json
{
  "total_earnings": "67500.00",
  "average_job_value": "16875.00",
  "highest_earning": "27000.00",
  "lowest_earning": "9000.00",
  "total_transactions": 4,
  "available_balance": "45000.00",
  "pending_withdrawal": "0"
}
```


## 3. Requesting a withdrawal: POST /wallet/payout/request

Rules: minimum `MIN_PAYOUT_NGN` (currently ₦5,000, also in `/wallet/balance` as `min_payout`) applies to the
requested amount; whole jobs only, oldest first; one bank transfer per withdrawal; payments stay "success" until
the bank transfer is confirmed.

`POST /api/v1/wallet/payout/request`  →  **200**  (capture: `10-payout-request.json`)

Request body:
```json
{
  "amount": "20000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "account_name": "Jane Placeholder"
}
```
Extra header: `Idempotency-Key: capture-key-0001`
Response:
```json
{
  "success": true,
  "message": "Withdrawal of ₦9,000.00 initiated successfully",
  "payout_reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
  "amount": "9000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "status": "processing",
  "withdrawal_id": 1,
  "requested_amount": "20000.00",
  "payments_count": 1,
  "idempotent_replay": false
}
```
> requested 20000, only the 9000 payment fits as a whole payment: the response states the ACTUAL amount

Requested 20,000 but only one whole job (9,000) fits: **`amount` is the real transfer**, `requested_amount` echoes
the input. Show the user `amount`.

Double tap / retry with the same `Idempotency-Key`:

`POST /api/v1/wallet/payout/request`  →  **200**  (capture: `11-payout-request-replay.json`)

Request body:
```json
{
  "amount": "20000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "account_name": "Jane Placeholder"
}
```
Extra header: `Idempotency-Key: capture-key-0001`
Response:
```json
{
  "success": true,
  "message": "Withdrawal of ₦9,000.00 initiated successfully",
  "payout_reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
  "amount": "9000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "status": "processing",
  "withdrawal_id": 1,
  "requested_amount": "20000.00",
  "payments_count": 1,
  "idempotent_replay": true
}
```
> same Idempotency-Key (double tap): same withdrawal, no second transfer

Errors (all `{"detail": ...}`, all safe to display):

`POST /api/v1/wallet/payout/request`  →  **400**  (capture: `12-payout-request-no-fit.json`)

Request body:
```json
{
  "amount": "5000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "account_name": "Jane Placeholder"
}
```
Response:
```json
{
  "detail": "No completed jobs fit within ₦5,000.00. Payouts are made per whole job, so the nearest withdrawable amount is ₦18,000.00."
}
```

`POST /api/v1/wallet/payout/request`  →  **400**  (capture: `13-payout-request-below-minimum.json`)

Request body:
```json
{
  "amount": "1000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "account_name": "Jane Placeholder"
}
```
Response:
```json
{
  "detail": "Minimum payout amount is ₦5,000.00"
}
```

`POST /api/v1/wallet/payout/request`  →  **403**  (capture: `14-payout-request-as-client.json`)

Request body:
```json
{
  "amount": "20000.00",
  "account_number": "0000000000",
  "bank_code": "057",
  "account_name": "Jane Placeholder"
}
```
Response:
```json
{
  "detail": "Only artisans can request payouts"
}
```

Other statuses the endpoint can return (**NOT VERIFIED LIVE against the running app**; covered by unit tests
`tests/services/test_withdrawal_service.py`): `400` `We could not verify that bank account. Please check the
account number and bank.` · `409` `This Idempotency-Key was already used for a different withdrawal request.` ·
`502` `We could not start your withdrawal right now. Please try again later.` (Paystack rejected the transfer; money
is back in the balance) · `400` `You have no withdrawable balance right now.`

State machine (`status`): `processing` → `success` | `failed` | `reversed`. FE behaviour:
* `processing`: show "Withdrawal in progress"; refresh `/wallet/payouts` on screen open/pull-to-refresh (suggested
  every 30 s while the screen is visible; push notifications `withdrawal_success` / `withdrawal_failed` /
  `withdrawal_reversed` also arrive with `data.event`).
* `failed` / `reversed`: tell the user the money is back in their available balance and let them retry.
* `success`: money is in the bank.
* A request can come back `processing` even after a network timeout on the provider side; do not create a second
  request with a new key, re-send the same key or refresh the list.

## 4. Webhooks (backend only, FYI for QA)

Paystack calls `POST /api/v1/payments/webhook`. Captured responses:

`POST /api/v1/payments/webhook`  →  **200**  (capture: `02-webhook-charge-success-mobile-money.json`)

Request body:
```json
{
  "event": "charge.success",
  "data": {
    "reference": "PAY-26321125320-416",
    "status": "success",
    "amount": 1500000,
    "currency": "NGN",
    "channel": "mobile_money"
  }
}
```
Response:
```json
{
  "status": "success",
  "message": "Payment processed"
}
```
> channel 'mobile_money' used to crash the old webhook (not in the PaymentMethod enum)

`POST /api/v1/payments/webhook`  →  **200**  (capture: `03-webhook-charge-success-redelivery.json`)

Request body:
```json
{
  "event": "charge.success",
  "data": {
    "reference": "PAY-26321125320-416",
    "status": "success",
    "amount": 1500000,
    "currency": "NGN",
    "channel": "mobile_money"
  }
}
```
Response:
```json
{
  "status": "success",
  "message": "Payment already processed"
}
```
> Paystack retry: idempotent no-op

`POST /api/v1/payments/webhook`  →  **200**  (capture: `05-webhook-charge-success-amount-mismatch.json`)

Request body:
```json
{
  "event": "charge.success",
  "data": {
    "reference": "PAY-CAP-MISMATCH",
    "status": "success",
    "amount": 100,
    "currency": "NGN",
    "channel": "card"
  }
}
```
Response:
```json
{
  "status": "ignored",
  "message": "Amount or currency mismatch"
}
```
> amount differs from the stored payment: NOT settled (payment stays pending)

`POST /api/v1/payments/webhook`  →  **401**  (capture: `06-webhook-bad-signature.json`)

Request body:
```json
{
  "event": "charge.success",
  "data": {
    "reference": "PAY-26321125320-416",
    "status": "success",
    "amount": 1500000,
    "currency": "NGN",
    "channel": "mobile_money"
  }
}
```
Response:
```json
{
  "detail": "Invalid webhook signature"
}
```

`POST /api/v1/payments/webhook`  →  **200**  (capture: `17-webhook-transfer-success.json`)

Request body:
```json
{
  "event": "transfer.success",
  "data": {
    "reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
    "transfer_code": "TRF_placeholder1",
    "amount": 900000,
    "status": "success"
  }
}
```
Response:
```json
{
  "status": "success",
  "message": "Transfer processed"
}
```

`POST /api/v1/payments/webhook`  →  **200**  (capture: `18-webhook-transfer-success-redelivery.json`)

Request body:
```json
{
  "event": "transfer.success",
  "data": {
    "reference": "wdr_719f912790044ddcbcd0e2baf0c531c4",
    "transfer_code": "TRF_placeholder1",
    "amount": 900000,
    "status": "success"
  }
}
```
Response:
```json
{
  "status": "success",
  "message": "Transfer already_processed"
}
```

`POST /api/v1/payments/webhook`  →  **200**  (capture: `23-webhook-transfer-failed.json`)

Request body:
```json
{
  "event": "transfer.failed",
  "data": {
    "reference": "wdr_4d1ff74248904ae5853f06710e266f69",
    "transfer_code": "TRF_placeholder2",
    "amount": 1800000,
    "reason": "Recipient bank unavailable"
  }
}
```
Response:
```json
{
  "status": "success",
  "message": "Transfer processed"
}
```


## 5. Disabled endpoint

`POST /api/v1/payments/1/release`  →  **403**  (capture: `26-release-payment-disabled.json`)

Request body:
```json
{}
```
Response:
```json
{
  "detail": "Manual payment release is disabled. Withdraw your balance from the wallet instead."
}
```


## 6. UX consequences to surface

* Never display the typed payout amount after submit; display the response `amount` (it may be lower).
* If `amount < requested_amount`, tell the user why ("payouts are made per completed job").
* A withdrawal that fails is not lost money: say so explicitly, the balance returns by itself.
* Jobs the customer never confirmed are now confirmed automatically once their dispute window ends (hourly job;
  artisan and customer get a `completion_auto_confirmed` notification). Earnings become withdrawable at that point.
* Reviews now send push notifications (`review_received` to the artisan, `review_response` to the customer).

## 7. Verification table

| Behaviour | Status |
|---|---|
| `/payments/initialize`, `/payments/verify`, `charge.success` webhook (non-enum channel, redelivery, amount mismatch, bad signature) | Verified live against the running app (Paystack REST = local stand-in) |
| `/wallet/balance|earnings|payouts|stats` before/during/after a withdrawal | Verified live (same setup) |
| `POST /wallet/payout/request`: actual<requested, idempotent replay, no-fit, below-minimum, client 403 | Verified live (same setup) |
| `transfer.success`, `transfer.failed` webhooks incl. redelivery and balance effects | Verified live (webhook signed by the capture script with a placeholder secret) |
| `POST /payments/{id}/release` → 403 | Verified live |
| Real Paystack round trips (initialize, transfer, bank resolve), real webhook payload shapes/signatures | NOT VERIFIED LIVE: needs a real Paystack account; shapes follow Paystack docs, bodies the app returns are what is captured |
| `transfer.reversed` (also after success), ambiguous timeout/5xx, transfer `otp` status | NOT VERIFIED LIVE: covered by unit/integration tests only |
| Idempotent double tap under true concurrency (two DB sessions) | Verified by automated test (`tests/services/test_withdrawal_service.py`), not via HTTP |
| Hourly auto-confirm task and its notifications | NOT VERIFIED LIVE (Celery beat not run); verified by automated tests |
| Review notifications, push delivery (FCM) | NOT VERIFIED LIVE: notification enqueue only; no FCM device |
