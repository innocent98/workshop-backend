# CI/CD Pipeline — Workchop API

## The idea: build once, test that image, ship that image

The image is built **one time**, on `develop`. That exact image is deployed to staging and tested. Production later redeploys the **same image**, identified by its digest, and never builds anything. What you tested is what you ship.

```
PR → develop                 push to develop                         push to main
     │                            │                                       │
     ▼                            ▼                                       ▼
 ┌────────┐             ┌──────────────────┐                      ┌────────────────┐
 │  CI    │             │ CD (staging)     │                      │ CD (production)│
 │ lint   │             │ 1 build + push   │                      │ 1 find the     │
 │ test   │  merge      │   image (GHCR)   │   fast-forward       │   verified     │
 │ semgrep│ ───────▶    │ 2 deploy staging │   main to develop    │   image        │
 │ image  │             │ 3 live E2E       │ ──────────────────▶  │ 2 deploy it    │
 │ scan   │             │ 4 mark verified  │                      │   (no build)   │
 └────────┘             └──────────────────┘                      └────────────────┘
                                 image  ghcr.io/<owner>/<repo>@sha256:…  (same bytes)
```

## Files

| File | Runs on | Does |
|---|---|---|
| `ci.yml` | PR to `develop`; push to `develop` | Lint, tests, Semgrep. On PRs also builds the image (not pushed) and scans it with Trivy. `CI gate` is the single check to require. |
| `cd-staging.yml` | push to `develop`; manual | Build and push the image, deploy to staging, run live E2E, then mark the image verified. |
| `cd-production.yml` | push to `main`; manual (rollback) | Find the verified image for this commit and deploy it. |
| `actions/deploy-stack` | called by both CD workflows | The shared deploy: decrypt env, ship, pull by digest, migrate, health check, roll back on failure. |
| `scripts/ghcr_digest.sh` | called by CD | Looks up an image's digest in GHCR. |

## How production knows an image was tested

After the live E2E passes, `cd-staging.yml` adds two tags to the tested image:

- `staging-verified-<full commit sha>` — "this commit passed staging". Used when `main` is pushed.
- `verified-sha256-<digest>` — "these exact bytes passed staging". Used for manual rollbacks.

`cd-production.yml` looks the tag up in the registry. No tag, no deploy. Only `cd-staging.yml` can add these tags, and only after E2E passes.

## Why `main` must be a fast-forward of `develop`

Production finds the image by the commit SHA. A fast-forward keeps the SHA unchanged; a squash or merge commit creates a new SHA that no image was built for. See `BRANCHING.md` for the exact commands and branch settings.

## Trust boundary: who can release

The "verified" tags are ordinary registry tags. The pipeline's safety rests on **who can run workflows with deploy secrets**, so:

- Set **Deployment branches** on both Environments (`GITHUB_ACTIONS_SETUP.md`, Step 2). This is the control that keeps other branches away from secrets.
- Treat repo write access as release power: anyone who can push workflow changes to `develop` can make an image look verified. Review changes to `.github/` like production code.
- If you need to defend against that, replace the tags with signed attestations (cosign or GitHub artifact attestations) that production checks against the `cd-staging.yml` identity. The template leaves that out to stay simple.

All actions are pinned to full commit SHAs. `.github/dependabot.yml` opens one weekly PR with the bumps; review it like any dependency update.

## CI cost controls

| Control | Effect |
|---|---|
| `main` is not a CI trigger | A commit arriving on `main` was already tested; it is not tested again. |
| Docs-only PRs skip lint, tests and the image scan | Semgrep still runs. |
| Draft PRs run nothing | Mark ready for review to run CI once. |
| Superseded PR runs are cancelled | Three quick pushes cost one run. |
| `CI gate` job | One check reports even when jobs are skipped, so branch protection stays simple. |

## Real HTTP tests

| Stage | What it runs | Real network? |
|---|---|---|
| CI `Tests` | `pytest tests/` (in-process `TestClient`) | No |
| CD `Live E2E` | `pytest tests/e2e -m e2e` against `$APP_URL` on the deployed staging stack | **Yes** |

Put server-dependent tests under `tests/e2e/` marked `@pytest.mark.e2e`, and skip them in `conftest.py` when `E2E_BASE_URL` is unset.

| Situation | Behavior |
|---|---|
| No `tests/e2e/` directory | Logged and skipped; the image is still marked verified. |
| `tests/e2e/` exists, no tests collected | pytest exit 5 is treated as success. |
| An E2E test fails | The job fails; the image is **not** verified and cannot reach production. |

## Deploy mechanics (`deploy-stack`)

1. Check every secret is set. 2. Decrypt `.env.<env>.enc` on the runner. 3. Ship `.env` and `docker-compose.prod.yml` to `$DEPLOY_PATH`. 4. On the VPS: record the running image, log in to GHCR with the run's own short-lived token, pull the image **by digest**, pin `API_IMAGE` in `.env`. 5. Production only: snapshot the database if one is running. Run `alembic upgrade head` (Workchop has no `scripts/seed_data.py`, so the optional seed hook is a no-op; the service catalogue is seeded by hand once, see the owner checklist, step 10). 6. `docker compose up -d`, then poll `/api/v1/health`. If any step fails, the previous image is restored.

Production also installs the daily backup cron (`scripts/backup_cron.sh`).

No registry password is stored anywhere: the token is created for each run and expires when it ends.

## Optional: companion frontend E2E

If a frontend repo has its own E2E suite, add a job to `cd-staging.yml` after `staging-deploy` that dispatches the frontend workflow against `$APP_URL` and polls for its result, and add it to the `needs:` of `mark-verified`. It is left out to keep the template simple.

## Workchop customizations of the template

Everything below differs from the stock template; see `docs/sop/deploy-pipeline.md` for the reasoning.

| Area | Workchop |
|---|---|
| Lint | `black --check app tests`, `isort --check-only app tests`, `flake8 app tests` (line length 100). Not ruff. |
| Job names | `lint` and `test` keep their old names (branch protection). The template's `Classify changes`, `Security (Semgrep)`, image check and **`CI gate`** are added. |
| Test job | PostGIS service, `alembic heads` single-head check, `alembic upgrade head`, `pytest -m "not e2e"`, then the e2e smoke suite against a locally booted server. |
| PR triggers | PRs into `main` **and** `develop` (until `develop` exists, and for hotfixes). Pushes: `develop` only. |
| Live E2E | `tests/e2e` (marker `e2e`): both health routes, the services list (a real DB query), an anonymous request to a protected route, a login with an unknown account, and both webhook paths rejecting unsigned requests. Read-only: no users, bookings or payments are created and no provider key is needed. |
| Rate-limit reset | The staging E2E step clears slowapi's `LIMITER*` keys (the template cleared `http_*`). |
| Pre-migration snapshot | Production runs `scripts/backup_cron.sh` before `alembic upgrade head` when a database exists. |
| Image prune | Scoped to images carrying this repo's `org.opencontainers.image.source` label; the VPS is shared, a bare `prune -a` would delete other projects' unused images. |
| Trivy | Blocking (`exit-code: '1'`, `ignore-unfixed: true`) in `image-check`: any fixable HIGH/CRITICAL in the built image fails the PR. Unfixed findings are not reported; accepted ones are recorded in `docs/sop/dependency-security-bump.md`. |
| Poetry | Pinned to 2.2.1, the version that generated `poetry.lock`. |
| "Verified" needs CI | `mark-verified` waits (up to 30 min) for the `CI gate` check run on the same commit and refuses to tag the image if it is red or missing. Without this, a commit with failing tests could be deployed to staging, pass the 7 read-only smoke checks, be stamped verified and be fast-forwarded to production. |
| Health gate | After the API answers, the deploy also waits for `celery_worker` and `celery_beat` to be `healthy` with no restarts (they run payouts, reconcile and auto-confirm). Otherwise: automatic rollback. |
| Rollback scope | Automatic rollback restores the previous image on `api`, `celery_worker` **and** `celery_beat`. |
| Manual rollback | `image_tag` dispatches pass `run_migrations: false`: no snapshot, no `alembic upgrade head` (the older image does not know the newer revision). Migrations are forward-only; see `ROLLBACK.md`. |
| Two hosts, two keys | Staging and production are separate VPSs with separate SSH keys by default (the `deploy` user is root-equivalent through Docker; a shared host lets whoever controls `develop` reach production). Single-VPS is an accepted-risk option documented in the owner checklist. |
| Encryption keys | One key per environment, no shared fallback in `scripts/env.sh`. |
