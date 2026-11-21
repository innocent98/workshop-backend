# SOP: Deploy pipeline (build once on `develop`, verify on staging, promote the same image to production)

**What shipped:** Adebayo's `backend-devops-template` installed into the backend and tailored to Workchop: CI
(lint/test/migration check + Semgrep + image build and Trivy), CD to staging (build once, deploy, live smoke E2E,
mark verified), CD to production (redeploy the verified digest, never rebuild), a production compose file with
worker **and** beat, nginx/TLS configs, encrypted-env workflow, backups/restore adapted for PostGIS, and the
owner setup checklist. **PR:** `ci/deploy-pipeline` → `main` (number in the PR; filled in on merge).
Nothing has run against a real VPS yet: the first staging deploy is the real test.

## Why

Until now there was no repeatable deploy: a 3-day temporary compose (`docker-compose.vps-temp.yml`) started by hand,
CI that stopped at tests, no image registry, no staging gate, no backups, no TLS config. The owner's priority is
launch, so the pipeline had to land as one reviewable unit with an explicit list of what only the owner can supply
(`docs/deployment/OWNER-SETUP-CHECKLIST.md`).

## How (model and key decisions)

| Decision | Choice | Alternative rejected |
|---|---|---|
| Release model | `develop` builds the image once → staging → live E2E → tag `staging-verified-<sha>`; fast-forward `main` to `develop` deploys that digest | Rebuilding on `main` (what you test is not what you ship) |
| Lint | the repo's own `black`, `isort`, `flake8` (line length 100) | the template's ruff + black (would disagree with `.flake8`/isort config and fail CI on existing code) |
| Job names | `lint`, `test` unchanged; added `Classify changes`, `Security (Semgrep)`, image check, `CI gate` | renaming to the template's `Lint`/`Tests` (breaks branch protection) |
| Docs-only PRs | path classification + always-running `CI gate`; concurrency cancels superseded PR runs (never pushes to `develop`) | workflow-level `paths-ignore` (leaves required checks pending) |
| Template CI `postgres:15-alpine` | kept the existing `postgis/postgis:15-3.4` service and the `alembic heads` single-head check | plain postgres (the models use Geography) |
| Test secrets | kept the inline synthetic CI values; no `CI_SECRET_KEY` secret to create | template's `secrets.CI_SECRET_KEY` (extra owner step, no benefit) |
| Poetry | pinned `2.2.1`, the version that wrote `poetry.lock` | template default `1.8.4` |
| Migrations | only in the deploy action; `SKIP_MIGRATIONS=true` on every service in the prod compose | migrating on container start (races between api/worker/beat, migrates on every crash-loop restart) |
| DB/Redis URLs | built in the compose file from `POSTGRES_*` | duplicating the password in `DATABASE_URL` (drift) |
| Redis policy | `noeviction`, 256 MB | dev stack's `allkeys-lru`: Redis is also the Celery broker, eviction would silently drop queued withdrawals and revoked tokens |
| Proxy headers | nginx **overwrites** `X-Forwarded-For`; uvicorn trusts it (`FORWARDED_ALLOW_IPS=*`, port bound to localhost) | default uvicorn (all users share the Docker gateway IP → one rate-limit bucket) or appending (spoofable → login limits dodged) |
| Pre-migration snapshot | production deploy runs `backup_cron.sh` before `alembic upgrade head` when a DB exists; a failure aborts | relying on the 02:00 cron (up to 24 h stale) |
| Image prune | scoped to this repo's `org.opencontainers.image.source` label | template's bare `prune -af` (the VPS is shared; it would delete other projects' unused images) |
| Live E2E | read-only smoke: health ×2, services list, protected route anonymous, unknown-account login, both webhooks reject unsigned requests | register → login (login requires the e-mail OTP; registration would leave junk rows on every deploy) |
| Env files | `.env.<env>.enc` committed (AES-256, `scripts/env.sh`, **one key per environment**: staging deploys from the looser `develop` branch, so a shared key would let staging decrypt production); `.env.*.example` list every variable; no plaintext ever | server-side hand-edited `.env` (unauditable) |

## What's involved

| Area | Files |
|---|---|
| Workflows | `.github/workflows/ci.yml` (merged), `cd-staging.yml`, `cd-production.yml`, `.github/actions/deploy-stack/action.yml`, `.github/dependabot.yml` |
| Stack | `docker-compose.prod.yml` (api, worker, beat, db, redis), `Dockerfile` (`GIT_SHA` build arg + source label; it already baked in `alembic/`, `alembic.ini`, `scripts/`), `.dockerignore`, `.gitignore` (un-ignores `.enc`/`.example`) |
| Env | `.env.staging.example`, `.env.production.example` (every `Settings` field is present; checked programmatically) |
| Edge | `deploy/nginx/{workchop-proxy,websocket-upgrade}.conf`, `api.workchop.app.conf`, `staging-api.workchop.app.conf` |
| Ops scripts | `scripts/{env,backup_cron,backup_db,backup_status,restore_db,ghcr_digest,security-scan}.sh` (`restore_db.sh` adapted, `umask 077` + `chmod 700 backups/` on all three backup scripts, `env.sh` per-env keys, see `docs/deployment/BACKUPS_GUIDE.md`) |
| Tests | `tests/e2e/` (marker `e2e` registered in `pytest.ini`; fixtures shadow the DB-truncating autouse fixtures) |
| Docs | `docs/deployment/*` (template guides tailored; `OWNER-SETUP-CHECKLIST.md`), this SOP, `docs/VPS_TEMP_DEPLOY.md` + `docker-compose.vps-temp.yml` marked deprecated (not deleted: the temp stack may still be running) |

Endpoints the pipeline depends on (read from the code): health `GET /api/v1/health` (and `GET /health`),
Paystack `POST /api/v1/payments/webhook`, Dojah `POST /api/v1/verification/webhook`.

## Verification

| Check | Result |
|---|---|
| `black`/`isort`/`flake8` on `app tests` (exact CI commands, pinned versions) | clean |
| `actionlint` on all workflows | clean |
| `bash -n` + `shellcheck` on all scripts | clean (one pre-existing SC2034 note in the template's `env.sh`) |
| `docker compose -f docker-compose.prod.yml config` with a scratch env | valid |
| `scripts/security-scan.sh` (Semgrep, same rulesets as CI) | 0 findings |
| CI on the pushed head (lint, test + smoke suite against a local server, Semgrep, image build + Trivy, CI gate) | see the PR |
| **Not run here:** real VPS deploy, nginx `-t`, certbot, GHCR push/pull, live staging E2E, Paystack/Dojah/Cloudinary/SMTP/FCM round trips, backup/restore on a real PostGIS volume | owner checklist steps 8 to 12 are the first real run |

## Operate / roll back

- Release: merge to `develop` → wait for the green **CD (staging)** run → `git fetch origin && git push origin origin/develop:main` → approve **CD (production)**.
- Automatic rollback: a failed health check restores the previous image (code only; the schema stays at the new head).
- Manual rollback: Actions → CD (production) → Run workflow, `image_tag=<an earlier verified sha-xxxxxxx>` (`docs/deployment/ROLLBACK.md`). If a bad migration corrupted data: restore the pre-migration snapshot (`restore_db.sh`) and deploy the previous image.
- Expected one-off noise: merging the pipeline PR to `main` triggers **CD (production)**, which fails with "No image for this commit" before reaching any secret.
- First release when `develop == main`: the fast-forward is a no-op, so run `gh workflow run "CD (production)" --ref main -f image_tag=sha-<7>`.

## Follow-ups

- Owner supplies VPS, DNS, secrets, provider keys, env encryption: `docs/deployment/OWNER-SETUP-CHECKLIST.md`.
- **Paystack webhook secret footgun (code, not changed here):** `PAYSTACK_WEBHOOK_SECRET` is a separate setting that must equal the secret key and makes every webhook fail closed when empty; falling back to `PAYSTACK_SECRET_KEY` in `verify_webhook_signature` would remove the trap.
- `celery_beat` schedule is not persisted across container recreation (`/tmp/celerybeat-schedule`); the three hourly tasks are idempotent, so they simply run at start. A named volume would need a writable path for uid 1000.
- `result_backend_transport_options={"master_name": "mymaster"}` in `app/celery_app.py` is a Sentinel option on a plain Redis URL; harmless today, worth a clean-up.
- Offsite backups (B2/rclone) are documented but off by default; enable before launch.
- Monitoring/error tracking (Sentry) and uptime alerts are not part of this PR.
- Template gaps found while installing are listed in the PR description for the template owner.
