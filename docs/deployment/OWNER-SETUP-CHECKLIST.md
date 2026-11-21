# Owner setup checklist: what only you can supply

Everything in the repo is ready (CI, CD, production compose, nginx, backups). The items below need
**your** accounts, keys or hands. They are ordered so you can **get staging running first with
test keys**, then do the production-only items.

Legend: **[S]** needed for staging · **[P]** production only · **[S+P]** do once per environment.
`REPO=innocent98/workshop-backend` is used in every command; replace nothing else unless a value is in `<angle brackets>`.

> **Never paste a secret into chat, a PR, an issue or a commit.** Set secrets straight into GitHub
> (`gh secret set`) or into the local plaintext env file. When this list says "send back", it means
> non-secret facts only (an IP address, a hostname, "done").

Verified vs not: the compose file passes `docker compose config`, the workflows pass `actionlint`, the
scripts pass `bash -n`/`shellcheck`, and lint + Semgrep run clean on this branch. **Nothing in this
list has been executed against a real VPS, GitHub Environment, Paystack, Dojah, Cloudinary, SMTP or
Firebase account**: the first staging deploy is the real test. Provider dashboard paths are given
from memory of those dashboards and can drift; the exact URLs/values come from the code.

---

## 0. Before anything: GitHub Actions must be able to run

- [ ] **[S+P] Actions need a public repo or fixed billing.** The repo is public right now only because billing blocked Actions.
  - Check: `gh api repos/innocent98/workshop-backend --jq .visibility` (currently `public`).
  - If you want it private again: first fix billing (GitHub → Settings → Billing and plans), then `gh repo edit innocent98/workshop-backend --visibility private --accept-visibility-change-consequences`.
  - Heads-up: `.env.staging.enc` / `.env.production.enc` get committed (step 7). They are AES-256 with a random 256-bit key, so a public repo is acceptable, but then **the `ENV_ENCRYPTION_KEY` is the only thing protecting every secret**. Keep it in your password manager and the GitHub Environment secrets only. Prefer to go private before committing the real `.enc` files.
- [ ] **[S+P] Merge this PR** (the lead merges after your "merge #N"). Expect **one red "CD (production)" run on that merge**: pushing to `main` triggers it, it finds no verified image for the commit and stops *before* touching any environment or secret. This is expected exactly once; after `develop` exists, `main` only moves by fast-forward from a verified `develop`.

## 1. VPS **[S]**

**Default path: TWO hosts**: a production VPS and a small separate staging VPS, each with its own `deploy` user and its own SSH key (step 3). Why: the `deploy` user must be in the `docker` group, which is root-equivalent on that machine. Staging deploys from `develop`, a branch with looser controls than `main`. If staging and production share one host, anyone who can push to `develop` (or edit `cd-staging.yml`) gets the staging SSH key and can read production's plaintext `.env` (Paystack live secret, database password, JWT key) or open a shell in the production database. Two hosts remove that path; the per-environment encryption keys only matter once they do. Wherever a command below says `<VPS IP>`, use the host of the environment you are working on (`<STAGING IP>` or `<PROD IP>`).

> **Single-VPS option (accepted risk: read this).** If you share one host for now, you are accepting that *anyone who can change what runs on `develop` can take over production*. Only do it with all of: (1) `develop` protected exactly like `main` plus review (the stricter command in step 4), no collaborators with write access, `enforce_admins: true`; (2) the `production` Environment keeps a **required reviewer** (step 5) and your own 2FA on GitHub; (3) separate OS users per environment **as hygiene, not isolation**: on one Docker daemon a `docker`-group user is root, so this does not stop the attack above. Commands: `adduser --disabled-password --gecos "" deploy-staging && adduser --disabled-password --gecos "" deploy-prod`, give each its own `~/.ssh/authorized_keys` with its own key, `chown -R deploy-staging /opt/workchop-staging`, `chown -R deploy-prod /opt/workchop`, add both to the `docker` group, and set `VPS_USERNAME` to `deploy-staging` / `deploy-prod` per Environment. For real isolation on one host you would need rootless Docker per user (`dockerd-rootless-setuptool.sh install` as each user; untested with this stack). Plan to move staging to its own small VPS before real users arrive.

- [ ] Create the VPS: any provider (Hetzner, DigitalOcean, Contabo, Vultr…), **Ubuntu 24.04 LTS** (22.04 also fine), IPv4.
  - Size: **production 2 vCPU / 4 GB RAM / 40 GB disk** minimum (container memory limits add up to about 3.1 GB). **Staging: 2 vCPU / 2-4 GB** is enough for smoke tests. (Single-VPS option: **8 GB** for both.) Pick a region near Nigeria/West Africa if offered (Frankfurt/London are fine).
  - Send back: **the production IP and the staging IP** and the provider name.
- [ ] Repeat the host steps below on **each** VPS (staging host: only `/opt/workchop-staging`; production host: only `/opt/workchop`).
- [ ] Log in as root once and create the deploy user (the same user GitHub Actions uses):
  ```bash
  adduser --disabled-password --gecos "" deploy
  usermod -aG sudo deploy
  echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deploy && chmod 440 /etc/sudoers.d/deploy   # needed for nginx/certbot steps; you may tighten later
  mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh && chown deploy:deploy /home/deploy/.ssh
  ```
- [ ] Install Docker Engine + Compose v2, add `deploy` to the `docker` group:
  ```bash
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker deploy
  docker compose version        # must print v2.x
  ```
- [ ] Firewall: only SSH, HTTP, HTTPS. (The compose file binds the API to `127.0.0.1` and publishes **no** database/Redis ports, because Docker-published ports bypass `ufw`.)
  ```bash
  apt-get update && apt-get install -y ufw
  ufw default deny incoming && ufw default allow outgoing
  ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
  ufw --force enable && ufw status verbose
  ```
- [ ] Swap (so a build-time or memory spike does not OOM-kill the database): 
  ```bash
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab && echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf && sysctl -p /etc/sysctl.d/99-swap.conf
  ```
- [ ] Optional hardening: `apt-get install -y unattended-upgrades fail2ban`; after SSH key login works (step 3), set `PasswordAuthentication no` in `/etc/ssh/sshd_config` and `systemctl reload ssh`.
- [ ] Create the deployment directory (owned by `deploy`) and its FCM secrets directory:
  ```bash
  # production host
  sudo mkdir -p /opt/workchop/secrets && sudo chown -R deploy:deploy /opt/workchop
  # staging host
  sudo mkdir -p /opt/workchop-staging/secrets && sudo chown -R deploy:deploy /opt/workchop-staging
  ```
- [ ] Install nginx + certbot:
  ```bash
  sudo apt-get install -y nginx certbot python3-certbot-nginx
  ```
- [ ] **Shared VPS with your other projects?** Do not touch their containers. Pick `API_PORT` values that are free (`ss -ltn | grep -E ':(8000|8001)\b'` must print nothing) and edit `API_PORT` in the env files + the `server 127.0.0.1:<port>` line in the nginx files if 8000/8001 are taken.

## 2. DNS **[S: staging-api] [P: api]**

- [ ] At your DNS provider for `workchop.app` (or the domain you actually own; if it differs, change it in the two files under `deploy/nginx/` and in `.env.*.example` before you encrypt), create **A records** pointing at the VPS IPv4:
  | Host | Type | Value | TTL |
  |---|---|---|---|
  | `staging-api` | A | `<STAGING IP>` | 300 |
  | `api` | A | `<PROD IP>` | 300 |
- [ ] Check: `dig +short staging-api.workchop.app` and `dig +short api.workchop.app` both return the VPS IP before running certbot (step 8).
- [ ] Send back: "DNS done" (and the real domain if it is not `workchop.app`).

## 3. SSH deploy key **[S+P]**

- [ ] On **your Mac**, **one key per environment** (a staging key must never open production):
  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/workchop_deploy_staging -C "gha-workchop-staging" -N ""
  ssh-keygen -t ed25519 -f ~/.ssh/workchop_deploy_prod    -C "gha-workchop-prod"    -N ""
  ssh-copy-id -i ~/.ssh/workchop_deploy_staging.pub deploy@<STAGING IP>      # staging key -> staging host ONLY
  ssh-copy-id -i ~/.ssh/workchop_deploy_prod.pub    deploy@<PROD IP>         # prod key    -> production host ONLY
  ssh -i ~/.ssh/workchop_deploy_staging deploy@<STAGING IP> 'docker ps && echo ok'   # must print the table and "ok"
  ssh -i ~/.ssh/workchop_deploy_prod    deploy@<PROD IP>    'docker ps && echo ok'
  ```
  (No passphrase is simplest. If you set one, also create the optional `VPS_SSH_PASSPHRASE` secret in step 6.) Single-VPS option: still use two keys and two users as described in step 1.
- [ ] Optional but wise: accept the host key once so the first manual SSH is not blind: `ssh-keyscan <VPS IP>` and compare the fingerprint with your provider's console.

## 4. Branches and protection **[S+P]** (run once, from any clone, after this PR is merged)

I did **not** create `develop` or change any protection; these are the exact commands.

- [ ] Create `develop` from `main`:
  ```bash
  gh api repos/innocent98/workshop-backend/git/refs -f ref=refs/heads/develop -f sha="$(gh api repos/innocent98/workshop-backend/git/ref/heads/main --jq .object.sha)"
  ```
  This push triggers **CD (staging)** immediately, so do steps 5 to 8 **first** (otherwise that first run fails at "Empty deploy input(s)", which is harmless but noisy: re-run it from the Actions tab once the setup is done).
- [ ] `main`: linear history (this is what forces the fast-forward promotion), no force pushes, no deletion:
  ```bash
  gh api -X PUT repos/innocent98/workshop-backend/branches/main/protection --input - <<'JSON'
  {"required_status_checks":null,"enforce_admins":false,"required_pull_request_reviews":null,"restrictions":null,
   "required_linear_history":true,"allow_force_pushes":false,"allow_deletions":false}
  JSON
  ```
  If `main` already has protection requiring `lint`/`test`, keep those two names: the jobs still have exactly those names.
- [ ] `develop`: PR required + the **`CI gate`** check required (one check that always reports, even on docs-only PRs). The same gate is also what the staging workflow waits for before it marks an image verified:
  ```bash
  gh api -X PUT repos/innocent98/workshop-backend/branches/develop/protection --input - <<'JSON'
  {"required_status_checks":{"strict":false,"contexts":["CI gate"]},"enforce_admins":false,
   "required_pull_request_reviews":{"required_approving_review_count":0},"restrictions":null,
   "required_linear_history":false,"allow_force_pushes":false,"allow_deletions":false}
  JSON
  ```
- [ ] **Single-VPS option only:** protect `develop` as strictly as `main` plus review, so nobody (you included) pushes unreviewed workflow or compose changes straight to the branch that holds the staging SSH key:
  ```bash
  gh api -X PUT repos/innocent98/workshop-backend/branches/develop/protection --input - <<'JSON'
  {"required_status_checks":{"strict":true,"contexts":["CI gate"]},"enforce_admins":true,
   "required_pull_request_reviews":{"required_approving_review_count":1,"require_code_owner_reviews":false},"restrictions":null,
   "required_linear_history":true,"allow_force_pushes":false,"allow_deletions":false}
  JSON
  ```
  (With `enforce_admins: true` and one required approval a solo owner cannot merge their own PR; add a second trusted reviewer, or accept the default `develop` protection above and treat the risk as accepted. Either way: no collaborators with write access.)
- [ ] Repo setting: Settings → General → Pull Requests: allow **squash merging** (PRs into `develop`). Never use the Merge button for `develop` → `main`; release with `git push origin origin/develop:main` (see `docs/deployment/BRANCHING.md`).

## 5. GitHub Environments **[S now, P later]**

Environment **Deployment branches** are the real security control (they stop a branch carrying an edited workflow from reading the VPS secrets). Required.

- [ ] **[S]** `staging` → only `develop`:
  ```bash
  gh api -X PUT repos/innocent98/workshop-backend/environments/staging --input - <<'JSON'
  {"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
  JSON
  gh api -X POST repos/innocent98/workshop-backend/environments/staging/deployment-branch-policies -f name=develop -f type=branch
  ```
- [ ] **[P]** `production` → only `main`, with you as required reviewer (a manual approval click before every production deploy):
  ```bash
  ME=$(gh api user --jq .id)
  gh api -X PUT repos/innocent98/workshop-backend/environments/production --input - <<JSON
  {"reviewers":[{"type":"User","id":$ME}],"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
  JSON
  gh api -X POST repos/innocent98/workshop-backend/environments/production/deployment-branch-policies -f name=main -f type=branch
  ```

## 6. GitHub secrets and variables **[S+P]**

Names are exactly what the workflows read (`grep -rhoE "(secrets|vars)\.[A-Za-z_]+" .github` → `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`, `VPS_SSH_PASSPHRASE`, `DEPLOY_PATH`, `ENV_ENCRYPTION_KEY`, `APP_URL`, `VPS_PORT`, plus the automatic `GITHUB_TOKEN`). There are **no repo-level secrets to create**: CI uses synthetic test values inline (no `CI_SECRET_KEY`), and the VPS pulls from GHCR with each run's own short-lived token.

- [ ] Generate **one encryption key per environment** (staging deploys from `develop`, which has looser controls than `main`; separate keys mean a staging compromise cannot decrypt production):
  ```bash
  ./scripts/env.sh generate-key           # run it twice; each prints a 64-hex key
  umask 077; echo '<staging key>'    > .env.staging.key       # local, gitignored; also save both in your password manager
  umask 077; echo '<production key>' > .env.production.key
  ```
- [ ] **[S]** staging secrets and variables:
  ```bash
  R=innocent98/workshop-backend
  gh secret set VPS_HOST            --repo $R --env staging --body '<STAGING IP or staging-api hostname>'
  gh secret set VPS_USERNAME        --repo $R --env staging --body 'deploy'      # 'deploy-staging' on the single-VPS option
  gh secret set VPS_SSH_KEY         --repo $R --env staging < ~/.ssh/workchop_deploy_staging
  gh secret set DEPLOY_PATH         --repo $R --env staging --body '/opt/workchop-staging'
  gh secret set ENV_ENCRYPTION_KEY  --repo $R --env staging --body "$(cat .env.staging.key)"
  gh variable set APP_URL           --repo $R --env staging --body 'https://staging-api.workchop.app'
  # optional: gh secret set VPS_SSH_PASSPHRASE ... ; gh variable set VPS_PORT --body 22
  ```
  `APP_URL` is the **origin only** (no `/api/v1`): the E2E suite appends paths itself.
- [ ] **[P]** production, same names, production values:
  ```bash
  gh secret set VPS_HOST            --repo $R --env production --body '<PROD IP or api hostname>'
  gh secret set VPS_USERNAME        --repo $R --env production --body 'deploy'   # 'deploy-prod' on the single-VPS option
  gh secret set VPS_SSH_KEY         --repo $R --env production < ~/.ssh/workchop_deploy_prod
  gh secret set DEPLOY_PATH         --repo $R --env production --body '/opt/workchop'
  gh secret set ENV_ENCRYPTION_KEY  --repo $R --env production --body "$(cat .env.production.key)"
  gh variable set APP_URL           --repo $R --env production --body 'https://api.workchop.app'
  ```
- [ ] Check: `gh secret list --env staging --repo $R` shows the five secrets; `gh variable list --env staging --repo $R` shows `APP_URL`.

## 7. Environment files: values, encryption, commit **[S now (test keys), P later (live keys)]**

`.env.staging.example` and `.env.production.example` list **every** variable the app reads, with fake placeholders. You produce the real files; I never see them.

- [ ] **[S]** Build the staging file:
  ```bash
  cp .env.staging.example .env.staging
  $EDITOR .env.staging       # fill every REPLACE_* value (see the table below), keep everything else
  ```
  Generate the random ones: `openssl rand -hex 32` (`SECRET_KEY`), `openssl rand -hex 24` (`POSTGRES_PASSWORD`). **Hex only** for passwords: the compose file builds the database URL from them, so no URL-escaping is needed.
- [ ] **[S]** Encrypt, verify, commit **only the `.enc`**, delete the plaintext:
  ```bash
  ./scripts/env.sh encrypt staging && ./scripts/env.sh verify staging
  git checkout -b chore/staging-env && git add .env.staging.enc && git commit -m "chore: staging environment (encrypted)"
  rm .env.staging
  ```
  (Then open a PR into `develop`; before `develop` exists, put it in a PR to `main`.) `git status` must never show `.env.staging`, `.env.production` or `.env.<env>.key` (they are gitignored). `env.sh` has **no shared-key fallback**: it reads `ENV_ENCRYPTION_KEY_STAGING`/`_PRODUCTION` or `.env.<env>.key` and prints which one it used; a stray `ENV_ENCRYPTION_KEY` in your shell is ignored on purpose.
- [ ] **[P]** Same for production later: `cp .env.production.example .env.production`, fill with **live** values, `./scripts/env.sh encrypt production`, `verify`, commit `.env.production.enc`, `rm .env.production`.

| Variable(s) | Staging | Production | Where you get it |
|---|---|---|---|
| `SECRET_KEY` | new random | **another** new random | `openssl rand -hex 32`. Never reuse a dev value or the one in `.env.example` (it is public in git history). |
| `POSTGRES_PASSWORD` | new random | another | `openssl rand -hex 24` |
| `COMPOSE_PROJECT_NAME`, `API_PORT` | `workchop-staging`, `8001` | `workchop`, `8000` | leave as is unless the ports are taken |
| `SERVER_HOST`, `BACKEND_CORS_ORIGINS` | staging URL, your web origins | prod URL, your web origins | the mobile app does not need CORS; use `'[]'` if there is no web client (must stay valid JSON in single quotes) |
| `FIRST_SUPERUSER_EMAIL`, `FIRST_SUPERUSER_PASSWORD` | a real mailbox you control, strong password | different real admin, strong password | used once by `scripts/create_admin.py` (step 10); the placeholder `admin@example.com` / `changethis` must not ship |
| `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` | **test** keys | **live** keys | Paystack dashboard → Settings → API Keys & Webhooks |
| **`PAYSTACK_WEBHOOK_SECRET`** | **the same value as `PAYSTACK_SECRET_KEY`** | **the same value as the live secret key** | Paystack signs webhooks with your secret key (no separate webhook secret exists). The app **rejects every webhook when this is empty** (`app/services/paystack.py:170`). |
| `DOJAH_ENVIRONMENT` | `sandbox` | `production` | picks `sandbox.dojah.io` vs `api.dojah.io` (a sandbox key does not work on production and vice versa) |
| `DOJAH_API_KEY`, `DOJAH_APP_ID`, `DOJAH_PUBLIC_KEY`, `DOJAH_NIN_WIDGET_ID`, `DOJAH_WEBHOOK_SECRET` | sandbox values | production values | see step 11 |
| `CLOUDINARY_CLOUD_NAME`, `_API_KEY`, `_API_SECRET`, `CLOUDINARY_FOLDER` | folder `workchop-staging` | folder `workchop` | Cloudinary console → Dashboard → API Keys |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAILS_FROM_EMAIL`, `EMAILS_FROM_NAME` | real SMTP | real SMTP | **required**: without SMTP the registration OTP e-mail is only logged and nobody can sign up. `SMTP_TLS=true` = STARTTLS (port 587); `false` = implicit TLS (port 465). Use a provider with SPF/DKIM on your domain (Zoho Mail, Brevo, Resend SMTP, SendGrid…). |
| `FCM_ENABLED` | `false` is fine | `true` | needs the service-account file (step 8) |
| backup vars | skip | optional offsite (`ENABLE_CLOUD_BACKUP`, `CLOUD_PROVIDER`, …) | see `docs/deployment/BACKUPS_GUIDE.md` |

## 8. VPS: FCM file, nginx, TLS **[S now, P later]**

- [ ] **[S+P]** Firebase service account JSON → the VPS (the file must **exist** before the first deploy or Docker creates a *directory* at that path, even when `FCM_ENABLED=false`):
  1. Firebase console → project settings (the project the mobile app uses; the code's default file name mentions `workchop-b3069`) → **Service accounts** → **Generate new private key**.
  2. **Production host:**
     ```bash
     scp ~/Downloads/<downloaded>.json deploy@<PROD IP>:/opt/workchop/secrets/fcm-service-account.json
     ssh deploy@<PROD IP> 'sudo chown 1000:1000 /opt/workchop/secrets/fcm-service-account.json && chmod 600 /opt/workchop/secrets/fcm-service-account.json'
     ```
     (UID 1000 is the non-root user inside the API image.)
  3. **Staging host: never the production service account.** With `FCM_ENABLED=false` (the staging default) create a placeholder; if you want real pushes on staging, create a separate Firebase project and use its key instead:
     ```bash
     ssh deploy@<STAGING IP> "echo '{}' > /opt/workchop-staging/secrets/fcm-service-account.json && sudo chown 1000:1000 /opt/workchop-staging/secrets/fcm-service-account.json && chmod 600 /opt/workchop-staging/secrets/fcm-service-account.json"
     ```
     `.env.staging.example` already points `FCM_SERVICE_ACCOUNT_FILE_HOST` at `/opt/workchop-staging/secrets/`.
- [ ] **[S]** nginx for staging, on the VPS (files are in this repo under `deploy/nginx/`; copy them over with `scp` or paste):
  ```bash
  sudo cp workchop-proxy.conf        /etc/nginx/snippets/workchop-proxy.conf
  sudo cp websocket-upgrade.conf     /etc/nginx/conf.d/websocket-upgrade.conf     # once per VPS; skip if another site already defines $connection_upgrade
  sudo cp staging-api.workchop.app.conf /etc/nginx/sites-available/workchop-api-staging
  sudo ln -s /etc/nginx/sites-available/workchop-api-staging /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx
  ```
- [ ] **[S]** TLS (DNS from step 2 must resolve first):
  ```bash
  sudo certbot --nginx -d staging-api.workchop.app --redirect -m <your email> --agree-tos --no-eff-email
  sudo certbot renew --dry-run          # proves auto-renewal (systemd timer installed by the package)
  ```
- [ ] **[P]** later, same with `api.workchop.app.conf` → `/etc/nginx/sites-available/workchop-api`, then `sudo certbot --nginx -d api.workchop.app --redirect -m <your email> --agree-tos --no-eff-email`.
- [ ] The edge allows request bodies up to **15 MB** (portfolio images are capped at 10 MB each by the app) and proxies `POST /api/v1/payments/webhook` and `POST /api/v1/verification/webhook` unchanged; do not put basic-auth or IP allow-lists on those two.

## 9. First staging deploy **[S]**

- [ ] Make sure steps 1 to 8 are done and `.env.staging.enc` is on `develop` (or `main` before `develop` exists).
- [ ] If `develop` does not exist yet, create it now (step 4's first command). The push runs **CD (staging)**: build → GHCR → deploy → live E2E → "Mark image as staging-verified". Watch: `gh run watch --repo innocent98/workshop-backend`.
- [ ] GHCR: nothing to configure. The first run creates `ghcr.io/innocent98/workshop-backend` (private, auto-linked to the repo by the image's source label); the VPS pulls with the run's own token. If the pull says `denied`, open the package's settings and make sure the repo has **Read** access.
- [ ] Note: "Mark image as staging-verified" waits (up to 30 min) for the **`CI gate`** check on that commit to be green. If CI is red the image is **not** verified and production will refuse it; fix CI and push again.
- [ ] On the staging host after a green run: `cd /opt/workchop-staging && docker compose -f docker-compose.prod.yml ps` should show `api`, `celery_worker`, `celery_beat` healthy plus `db`, `redis`; `curl -s https://staging-api.workchop.app/api/v1/health` → `{"status":"ok",...}`.
- [ ] Send back: "staging is up" (or the failing step's log).

## 10. Seed data and admin **[S+P, once per environment, after the first green deploy]**

- [ ] Seed the service catalogue (idempotent): 
  `ssh deploy@<STAGING IP> 'cd /opt/workchop-staging && docker compose -f docker-compose.prod.yml exec api python scripts/seed_services.py'`
- [ ] Create the first admin from `FIRST_SUPERUSER_*` (idempotent; refuses if a non-admin with that email exists):
  `ssh deploy@<STAGING IP> 'cd /opt/workchop-staging && docker compose -f docker-compose.prod.yml exec api python scripts/create_admin.py'`
  then log in once and change the password. (Production: same on `<PROD IP>` with `/opt/workchop`.)

## 11. Providers

### Paystack
- [ ] **[S]** Test keys: Paystack dashboard → toggle **Test mode** → Settings → API Keys & Webhooks → copy test secret/public key into `.env.staging` (step 7).
- [ ] **[S]** Webhook URL (Test): same page → **Test Webhook URL** = `https://staging-api.workchop.app/api/v1/payments/webhook`. Paystack delivers every event to that one URL; the app acts on `charge.success`, `charge.failed`, `transfer.success`, `transfer.failed`, `transfer.reversed` and `refund.pending/processing/processed/failed`, and answers `ignored` to anything else.
- [ ] **[S+P] Disable the transfer OTP** (otherwise every artisan payout stalls waiting for an OTP that no server can enter): Paystack dashboard → Settings → **Preferences** (Transfers section) → turn **off** "Confirm transfers before sending" (label can differ slightly by dashboard version). Do it in Test mode and again in Live mode.
- [ ] **[P]** Business activation complete (Paystack requires it for live keys and live transfers), then live keys → `.env.production`, and **Live Webhook URL** = `https://api.workchop.app/api/v1/payments/webhook`.
- [ ] **[P]** Do one real small payment + refund on production before announcing launch; then confirm `PAYSTACK_WEBHOOK_SECRET` works (a webhook with a bad signature must return 401, a Paystack-delivered one 200: Paystack dashboard → Webhook logs).

### Dojah (artisan NIN + selfie)
- [ ] **[S]** Sandbox: Dojah dashboard → create/select the app → copy **App ID**, **Public key**, **Secret key** (= `DOJAH_API_KEY`) from the API keys page; create the Identity **widget** for NIN + selfie and copy its **Widget ID** (= `DOJAH_NIN_WIDGET_ID`). Put them into `.env.staging` with `DOJAH_ENVIRONMENT=sandbox`.
- [ ] **[S]** Webhook: Developers → **Webhooks** → add `https://staging-api.workchop.app/api/v1/verification/webhook`, subscribe the **`kyc_widget`** event, copy the **subscription secret** it shows → `DOJAH_WEBHOOK_SECRET` (this is *not* the API key). Re-encrypt and redeploy after adding it.
- [ ] **[P]** Production: Dojah needs your business to be activated for live NIN lookups; repeat with production keys, `DOJAH_ENVIRONMENT=production`, and webhook URL `https://api.workchop.app/api/v1/verification/webhook`.

### Cloudinary **[S+P]**
- [ ] Console → Dashboard → copy cloud name, API key, API secret. Use the same cloud with a different `CLOUDINARY_FOLDER` per environment (`workchop-staging` / `workchop`) or two separate product environments.

### SMTP **[S+P]**
- [ ] Pick a provider, verify the sending domain (SPF + DKIM records at your DNS), create credentials, fill the `SMTP_*` and `EMAILS_FROM_*` variables. Test by registering a user on staging and receiving the OTP.

### Firebase Cloud Messaging **[S+P]**: see step 8 (service-account file) and set `FCM_ENABLED=true`.

## 12. Production release **[P]**

- [ ] Steps 5 (`production` environment), 6 (production secrets/variables), 7 (`.env.production.enc` with **live** keys) and 8 (prod nginx + TLS, FCM file) are done.
- [ ] **Snapshot before the migration.** The production deploy takes a database snapshot automatically before `alembic upgrade head` whenever a database already exists (`backups/` on the VPS). A manual rollback (`image_tag`) skips migrations and the snapshot by design (`docs/deployment/ROLLBACK.md`). This release carries migration `a4c8e2f6b1d9` (review-moderation columns + a response-time backfill in one transaction). On the **very first** production deploy there is no database yet, so there is nothing to protect.
- [ ] Release. If `develop` was created from the same commit as `main` (the normal first time), `git push origin origin/develop:main` is a no-op and triggers nothing, so run the production workflow by hand against the verified image:
  1. Actions → **CD (staging)** → the green run → copy the image tag `sha-xxxxxxx` (first 7 characters of the commit), **or** read it from GHCR.
  2. ```bash
     gh workflow run "CD (production)" --repo innocent98/workshop-backend --ref main -f image_tag=sha-xxxxxxx
     ```
     (From the second release on: merge a PR into `develop`, wait for the green staging run, then `git fetch origin && git push origin origin/develop:main`.)
  3. Approve the deployment in the Actions UI (you are the required reviewer).
- [ ] Then step 10 for production (`/opt/workchop`): seed services, create the admin.
- [ ] Backups: the production deploy installs the nightly cron (02:00). Verify next day: `ssh deploy@<PROD IP> 'cd /opt/workchop && bash scripts/backup_status.sh'`. Recommended: also enable an offsite copy (`ENABLE_CLOUD_BACKUP=true`, Backblaze B2 via rclone: `docs/deployment/BACKUPS_GUIDE.md`), because local dumps die with the VPS disk. Do one **restore drill** on staging with a production-shaped dump.

## 13. Clean-ups and people **[P, before launch]**

- [ ] **Rotate the old test-account password.** It lives in git history (`test_accounts.txt`, removed from the tree in PR #6 but not from history). On any real server: never run `create_test_accounts.py` there; if an account created with that password exists anywhere (dev/staging DBs, TestFlight builds), change its password or delete the account. History is not rewritten.
- [ ] **New `SECRET_KEY` for every environment** (step 7). The value committed in `.env.example` is public: treat it as burned. Rotating it later signs every user out.
- [ ] Real `FIRST_SUPERUSER_*` (step 7), then `create_admin.py` (step 10); change the password after the first login.
- [ ] **support@workchop.app mailbox**: create it at your mail provider (also the natural `EMAILS_FROM`/reply address), and add forwarding to you. The app/FE reference it as the support contact.
- [ ] Uptime check: point any monitor (UptimeRobot, Better Stack) at `https://api.workchop.app/api/v1/health` (expects 200).

## 14. Quick "send me back" list

| When | Send |
|---|---|
| After step 1 | VPS IP, provider, size |
| After step 2 | "DNS done" + the real domain if not `workchop.app` |
| After step 6 | `gh secret list` / `gh variable list` output for staging (names only) |
| After step 9 | "staging up" or the failing log lines |
| Any time | the exact error text if a command here fails: it is quicker than guessing |

Never send: private keys, `.env*` contents, API keys, passwords, the encryption key.
