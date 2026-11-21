# GitHub Actions Setup — Workchop API

The pipeline is three workflows and one shared action in `.github/`:

| File | Trigger | What it does |
|---|---|---|
| `workflows/ci.yml` | PR to `develop`, push to `develop` | Lint, tests, Semgrep; on PRs also builds and scans the image (not pushed). |
| `workflows/cd-staging.yml` | push to `develop`, manual | Build once, push to GHCR, deploy staging, live E2E, mark the image verified. |
| `workflows/cd-production.yml` | push to `main`, manual (rollback) | Deploy the verified image. Never builds. |
| `actions/deploy-stack` | called by both CD workflows | Decrypt env, ship, pull by digest, migrate, health check, auto-rollback. |

How they fit together: `CICD_PIPELINE.md`. How to release: `BRANCHING.md`.

## One-time setup (about 15 minutes)

### Step 1. SSH keypair for GitHub Actions → VPS

```bash
ssh-keygen -t ed25519 -f ~/.ssh/workchop_deploy -C "gha-workchop"
ssh-copy-id -i ~/.ssh/workchop_deploy.pub <user>@<vps-host>
ssh -i ~/.ssh/workchop_deploy <user>@<vps-host> 'echo ok'
```

No passphrase is simplest. If you set one, add it as `VPS_SSH_PASSPHRASE`.

### Step 2. Create the GitHub Environments

**Settings → Environments** → create `staging` and `production`, then set **Deployment branches** on each. This is required, not optional:

| Environment | Deployment branches | Why |
|---|---|---|
| `staging` | Selected branches → `develop` | Only workflows running on `develop` can read staging secrets. |
| `production` | Selected branches → `main` | Only workflows running on `main` can read production secrets. |

Without this, anyone with write access could push a branch containing a modified workflow and run it with the environment's secrets. The `github.ref` checks inside the workflows only stop accidental manual runs; a branch can edit its own copy of the file, so the Environment rule is the real control.

On `production`, also add **Required reviewers** for a manual approval before each deploy.

### Step 3. Environment secrets and variables

Add to **both** environments (values differ):

| Secret | Staging | Production |
|---|---|---|
| `VPS_HOST` | `vps.example.com` | same host, or another |
| `VPS_USERNAME` | `deploy` (in the `docker` group) | same |
| `VPS_SSH_KEY` | contents of `~/.ssh/workchop_deploy` (the private key) | same |
| `VPS_SSH_PASSPHRASE` | only if the key has one | same |
| `DEPLOY_PATH` | `/opt/workchop-staging` | `/opt/workchop` |
| `ENV_ENCRYPTION_KEY` | passphrase for `.env.staging.enc` | passphrase for `.env.production.enc` |

| Variable (not secret) | Staging | Production |
|---|---|---|
| `APP_URL` | `https://staging-api.workchop.app` | `https://api.workchop.app` (**origin only**, no `/api/v1`) |
| `VPS_PORT` | `22` (optional) | same |

`APP_URL` is a variable because GitHub shows it on the Environment page and the E2E suite targets it. The API's local port for health checks comes from `API_PORT` inside your `.env` (default `8000`).

> Same VPS for both? Give each stack its own `DEPLOY_PATH`, `COMPOSE_PROJECT_NAME` and `API_PORT` (for example staging `8001`, production `8000`) in its `.env`.

### Step 4. Repo-level secrets

**Settings → Secrets and variables → Actions**:

| Secret | Why |
|---|---|
| *(none required for Workchop)* | The template wants `CI_SECRET_KEY`; Workchop's CI keeps its existing synthetic inline test values (`SECRET_KEY: test-secret-key-for-ci`), so nothing has to be created. Add `CI_<SERVICE>_*` secrets here only if a future test needs a throwaway third-party key. Never real keys. |

Never put token-looking values inline in workflow YAML; always `${{ secrets.X }}`.

There is **no registry secret to create**. The VPS pulls the image from GHCR using the workflow run's own short-lived `GITHUB_TOKEN`.

### Step 5. Branch settings

See the table in `BRANCHING.md`. The two that matter: `main` requires **linear history**, `develop` requires a PR and the **CI gate** check.

### Step 6. Bootstrap the VPS

```bash
sudo mkdir -p /opt/workchop /opt/workchop-staging
sudo chown "$USER:$USER" /opt/workchop /opt/workchop-staging
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"      # log out and in afterwards
docker compose version                # must print v2
```

The environment file is **encrypted in the repo** (`.env.staging.enc`, `.env.production.enc`) and decrypted on the runner at deploy time. A deploy fails if the `.enc` file or key is missing; there is no "use whatever `.env` is on the server" mode. See `ENV_ENCRYPTION.md`.

### Step 7. What your project must provide

- `Dockerfile` that copies `alembic/` and `alembic.ini` into the image (the VPS gets the image, not the source).
- `docker-compose.prod.yml` whose API service uses `image: ${API_IMAGE}` and is named `api`.
- A health endpoint at `/api/v1/health`.

### Step 8. First release

1. Merge a PR into `develop`. **CD (staging)** builds, deploys, tests and marks the image verified.
2. Fast-forward `main` to `develop` (`git push origin origin/develop:main`). **CD (production)** deploys that image.

## Verifying a deploy on the VPS

```bash
cd /opt/workchop            # or /opt/workchop-staging
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 api
curl -sS http://localhost:8000/api/v1/health
grep '^API_IMAGE=' .env             # shows the exact digest running
```

## Rollback

Automatic on a failed deploy; manual by redeploying an earlier verified tag. See `ROLLBACK.md`.

## Troubleshooting

| Symptom | Check |
|---|---|
| `Empty deploy input(s): …` | The named secret is unset in that GitHub Environment. |
| `Permission denied (publickey)` | The key is not on the VPS: rerun `ssh-copy-id`. |
| `denied` / `unauthorized` pulling the image | The job must have `permissions: packages: read` (the workflows set it). If the package is owned by another repo, link it to this repo under the package's settings. |
| Production: "No image for this commit" | `main` was not a fast-forward of `develop`. See `BRANCHING.md`. |
| Production: "Not verified on staging" | The staging run for that commit failed, was cancelled, or is still running. |
| `No such file or directory: /opt/…` | VPS bootstrap skipped: run Step 6. |
| Health check never returns 200 | `docker compose logs --tail=200 api` on the VPS. Most common cause: a missing env var. |
| `Could not decrypt .env.<env>.enc` | Wrong `ENV_ENCRYPTION_KEY` for that environment. |

## Where each secret is used

| Secret / variable | Used in |
|---|---|
| `VPS_*`, `DEPLOY_PATH`, `ENV_ENCRYPTION_KEY` | `actions/deploy-stack` (called by both CD workflows) |
| `APP_URL` | `cd-staging.yml` E2E target; shown as the Environment URL |
| `CI_*` | `ci.yml` test job |
| `GITHUB_TOKEN` (automatic) | GHCR push in `cd-staging.yml`; GHCR pull on the VPS |

## Workchop notes

- Step-by-step with the exact `gh` commands and everything only the owner can supply: [OWNER-SETUP-CHECKLIST.md](OWNER-SETUP-CHECKLIST.md).
- Pushing to `main` (including merging the PR that introduced the pipeline) runs **CD (production)**, which stops at "No image for this commit" if that commit was not verified on staging. That is expected once; it never reaches the environment secrets.
- First release when `develop` and `main` point at the same commit: `git push origin origin/develop:main` is a no-op, so start production with `gh workflow run "CD (production)" --ref main -f image_tag=sha-<first 7 of the commit>`.
