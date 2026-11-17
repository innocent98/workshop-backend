# SOP: Backend hygiene (scratch files, test credentials, Dojah placeholders)

**What shipped:** removed tracked scratch files and test credentials from the repo root, stopped the account
seeding script from carrying a hardcoded password, and made `GET /profiles/artisans/me/verification/config`
report `configured: false` when the Dojah settings are blank or still the `.env.example` placeholders.
**PR:** `chore/backend-hygiene` → `main` (see PR link in the lead's report).

## Why

The repository is temporarily public. Several tracked files carried test passwords, and the root was full
of one-off scripts. Separately, a server started from a copy of `.env.example` has non-empty Dojah values
(`your-dojah-secret-key`, …), so the config endpoint said `configured: true` and the app launched the widget
with junk keys instead of showing "verification unavailable".

## How (decisions and trade-offs)

| Area | Decision |
|---|---|
| Scratch files | `git rm` rather than move. They were not referenced by CI, `pytest.ini` (`testpaths = tests`), the README or the Makefile; the only references were from each other and the stray docs. |
| Seeding script | `scripts/create_test_accounts.py` never read `test_accounts.txt`, but it hardcoded the password. It now reads `TEST_ACCOUNT_PASSWORD`, or generates a random one for the run and prints it once. No password lives in git. |
| `.gitignore` | `test_accounts.txt` is ignored so a locally written credentials list cannot be committed again. |
| Placeholder detection | One helper, `credential_or_none()` in `app/integrations/dojah/client.py`: blank/whitespace, any exact `.env.example` DOJAH value, or a value starting with `your-`, `your_`, `changeme`, `change-me` or `<` (case-insensitive) counts as unset. Prefix matching was chosen over an exact-list-only check so a renamed placeholder in a future `.env.example` still reads as unset. |
| Where it applies | `is_configured()` (API key + NIN widget id both required), the public fields echoed by the config endpoint (`app_id`, `public_key`, `widget_id` are `null` when placeholder), and `get_dojah_client()` (a placeholder secret key yields no client, so confirm/webhook paths answer 503 `verification_unavailable` instead of calling Dojah with a junk key). |

## What's involved

- Removed: `test_accounts.txt`, `test.txt`, `test_all_endpoints.py`, `test_booking_flow.py`,
  `test_complete_system.py`, `test_payout_request.py`, `test_wallet_analysis.py`,
  `test_wallet_endpoints.py`, `QUICK_TEST_GUIDE.md` and `IMPLEMENTATION_SUMMARY.md` (both quoted the shared
  test password), `WALLET_COMPLETE.md`, `WALLET_IMPLEMENTATION_SUMMARY.md` (status write-ups, unreferenced).
- Edited: `.gitignore`, `scripts/create_test_accounts.py`, `app/integrations/dojah/client.py`,
  `app/services/artisan_verification.py`.
- Tests: `tests/admin/test_verification.py` (placeholder/blank parametrised cases, public fields not echoed,
  placeholder key yields no client).
- No migrations, no new config keys.

## Verification

- `poetry run black --check app tests`, `isort --check-only`, `flake8`: clean.
- `tests/admin/test_verification.py` and `tests/admin/test_dojah_client.py` run against a scratch PostGIS container.
- CI is the authority for the full suite.

## Operate / roll back

- **The old passwords remain in git history** (the shared password of the seeded `@test.com` accounts, and the one for
  `testuser001@example.com`; find them with `git log -p -- test_accounts.txt test.txt`). Deleting the files does not remove them from history or from forks/clones
  made while the repo was public. **Rotate them on any real server:** change or delete those users, and
  never run the seeding script against production. Rewriting history is deliberately not part of this PR.
- Seeding now: `TEST_ACCOUNT_PASSWORD='<choose one>' python scripts/create_test_accounts.py`
  (or run it bare and copy the printed password).
- Roll back: `git revert` the PR. No data or schema is involved.

## Follow-ups

- Decide whether to rewrite git history (or rotate and accept) before the repo goes public for good.
- Consider the same placeholder treatment for the Paystack, Cloudinary and SMTP settings, which also ship
  as `your-…` values in `.env.example`.
- `docs/VPS_TEMP_DEPLOY.md` still tells operators to run the seeding script; keep that to non-production hosts.
