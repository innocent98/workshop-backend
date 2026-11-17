# SOP: Escrow provider seam (Paystack today, Weysure later)

**What shipped:** a thin provider seam so that moving customer money is one swappable interface
(`EscrowProvider`) and artisan bank payouts are another (`PayoutProvider`). Paystack is the only
implementation of both. **No behaviour change for users:** same endpoints, status codes, messages,
settlement and ledger. **PR:** `refactor/escrow-provider-seam` → `main`.

## Why

The owner wants the escrow to stay simple so Weysure (their own escrow product, same custody model,
pre-launch, test keys only) can be introduced later without touching booking, wallet or dispute logic.
Before this change, Paystack calls and Paystack-shaped payloads were spread over `payments.py`,
`admin.py`, `withdrawal_service.py` and `wallet.py`.

## What stays Workchop's (not behind the seam)

Booking states, the artisan wallet and withdrawal ledger, the 24h auto-confirm, the dispute rules and the
admin release/refund *decision*, plus the settlement functions `apply_charge_success` /
`apply_charge_failed` (`app/services/payment_service.py`) and refund settlement
(`handle_refund_event`, `_run_refund` in `app/services/admin.py`). Only **money movement** is behind the seam.

## How

```
app/services/provider_errors.py   ProviderError(message, status_code), DuplicateReferenceError
app/services/escrow/base.py       EscrowProvider (ABC), event dataclasses, WebhookRejected
app/services/escrow/paystack.py   PaystackEscrowProvider (delegates to PaystackService at call time)
app/services/escrow/__init__.py   get_escrow_provider(): ESCROW_PROVIDER, default "paystack"; unknown name fails fast
app/services/payout/{base,paystack,__init__}.py   PayoutProvider + PaystackPayoutProvider; PAYOUT_PROVIDER
```

`EscrowProvider`:

| Method | Purpose | Paystack today |
|---|---|---|
| `initiate_hold(booking, amount, customer_email, reference)` → `HoldCheckout(authorization_url, reference, access_code, raw)` | start a hold; raises `DuplicateReferenceError` so the endpoint retries with a new reference | `POST /transaction/initialize` |
| `verify_and_parse_webhook(headers, body)` → event | authenticate + normalise; raises `WebhookRejected(401/400)` | `x-paystack-signature` HMAC-SHA512 |
| `fetch_status(reference)` → `HoldFunded` / `HoldFailed` / `HoldPending` | the `GET /payments/verify` endpoint | `GET /transaction/verify` (only `failed`/`reversed` are terminal) |
| `refund(hold_reference, amount=None, idempotency_key=None, *, notes)` | refund a hold; returns the provider's refund object | `POST /refund` (no idempotency key exists: a repeat is reconciled with `list_refunds`) |
| `list_refunds(hold_reference)` | reconcile an unknown refund outcome | `GET /refund?transaction=` |

Events: `HoldFunded`, `HoldFailed`, `HoldPending`, `RefundUpdated`, `PayoutSucceeded`, `PayoutFailed(reversed)`,
`Ignored`. Each carries `data`, the provider's raw object **in the shape the settlement code already reads**
(`reference`, `amount` in kobo, `currency`, `channel`, `status`, `id`). The endpoint (`payments.py`
`_handle_webhook_event`) only dispatches events to the existing settlement functions. Payout events ride on the
same webhook (Paystack sends `transfer.*` there), so they are part of the event set.

Decisions: **(1)** `data` stays Paystack-shaped instead of rewriting `apply_charge_*` to take a normalised
event: zero change on the money path, and a Weysure adapter maps *into* that shape. Revisit when a second
provider exists. **(2)** `PaystackError` now subclasses `ProviderError`, so provider-neutral callers
(`except ProviderError`) and existing tests that raise `PaystackError` both work. **(3)** No DB changes: the
`paystack_reference` / `paystack_access_code` / `paystack_response` columns hold the *provider's* values and
keep their names (a rename is a migration with no behaviour gain). **(4)** Rejected: speculative Weysure
code, a generic plugin loader, async interfaces.

## What's involved

Changed call sites: `app/api/v1/endpoints/payments.py` (initialize, verify, webhook),
`app/services/admin.py` (`_run_refund`, refund reconciliation), `app/services/withdrawal_service.py`,
`app/api/v1/endpoints/wallet.py`, settings `ESCROW_PROVIDER` / `PAYOUT_PROVIDER` in `app/core/config.py`.
`PaystackService` (`app/services/paystack.py`) is unchanged apart from the error base class.

## Verification

- Existing tests unchanged and green: `test_payments_webhook`, `test_refund_safety`, `test_admin_api`,
  `test_withdrawal_service`, `test_wallet`, and the refund tests in `test_account_deletion`
  (they patch `PaystackService.*`, which the providers call at call time).
- New `tests/services/test_escrow_provider.py`: webhook signature (missing / wrong / no secret / case-insensitive
  header / malformed body), event normalisation, the provider's event driving `apply_charge_success` (settles,
  replay idempotent, wrong amount or currency not settled), `fetch_status` terminal vs pending, `initiate_hold`
  request and duplicate-reference mapping, refund delegation, payout delegation, registry default and fail-fast.
- Intentional differences (all edge cases that were already bugs): a signed webhook whose JSON is not an object
  (e.g. `[1]`) now answers 400 instead of 500.

## Operate / roll back

Nothing to deploy beyond the code. `ESCROW_PROVIDER` and `PAYOUT_PROVIDER` default to `paystack`; leave them
unset. Roll back by reverting the PR (no migration).

## Adding `WeysureEscrowProvider` (not built; facts from `Weysure-API/DEVELOPER_API_GUIDE.md`)

Add `app/services/escrow/weysure.py` implementing `EscrowProvider`, register it under `"weysure"` in
`app/services/escrow/__init__.py`, set `ESCROW_PROVIDER=weysure` (Weysure is pre-launch with test keys only:
sandbox first). Weysure: REST under `/api/v1/public` with `X-API-Key`; escrow create / get / release / refund /
split / hold; HMAC `X-Weysure-Signature` webhooks (`escrow.payment_successful`, `released`, `refunded`,
`payout_*`). Mismatches the adapter must handle:

| Weysure behaviour | What the adapter / Workchop does |
|---|---|
| Escrow amount is fixed at creation; renegotiation = a new escrow | `initiate_hold` creates one escrow per agreed amount. A changed `agreed_amount` before payment = create a new escrow and archive the old reference (`archive_payment_reference` already supports re-initialising). |
| One Paystack payment per escrow | One hold per payment attempt; a second payment for the same escrow is the existing `needs_refund` duplicate-charge path. |
| Release pays ONE developer bank account | Workchop's wallet ledger stays the source of truth for artisan balances and withdrawals: **do not** call Weysure release per booking to the artisan. The hold is released to the platform account and artisan payouts remain `PayoutProvider` transfers. Do not use `split`. |
| Auto-release (default 30 days, flagged off) | Keep it off. Workchop's 24h auto-confirm and dispute rules decide release; Weysure must never release on its own. Treat an unexpected `escrow.released` as `Ignored` and alert. |
| Customer pays ~2% + card fee on top | The hold amount Weysure charges is higher than `agreed_amount`: map `escrow.payment_successful` into `data` with `amount` = the escrow amount (excluding the on-top fee) and decide product-side who shows/absorbs the fee. `charge_matches_payment` must compare the escrow amount, never the fee-inclusive total. |
| Webhook signature `X-Weysure-Signature` | Implement in `verify_and_parse_webhook`; reject with `WebhookRejected(401)`. A second route (or provider-prefixed path) is needed because the webhook URL is per provider. |
| Events `payment_successful` / `refunded` / `payout_*` | Map to `HoldFunded` / `RefundUpdated` / ignore (our payouts stay on Paystack). Build the `data` dict the settlement code reads. |
| Refund | Map `refund` to Weysure's refund endpoint; use `idempotency_key` if Weysure supports one, else reconcile via `get`. |
| Pre-launch, test keys only | Do not enable in production until Weysure launches; keep `paystack` the default. |

## Follow-ups

- Rename `paystack_*` payment columns to provider-neutral names only when a second provider is wired.
- A per-provider webhook route when Weysure is added (signature header and URL differ).
- Decide whether `apply_charge_*` should take the normalised event once two providers exist.
