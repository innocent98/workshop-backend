# Deployment Guide: Workchop API

How the deployed stack is laid out and operated. The one-time owner setup (accounts, DNS, secrets) is
in [OWNER-SETUP-CHECKLIST.md](OWNER-SETUP-CHECKLIST.md); what each CI/CD stage does is in
[CICD_PIPELINE.md](CICD_PIPELINE.md). This replaces the temporary VPS guide
(`docs/VPS_TEMP_DEPLOY.md`, now deprecated).

## Compose files

| File | Use |
|---|---|
| `docker-compose.yml` | **Local development.** Builds from source, bind-mounts `./app`, publishes ports, includes Adminer under the `tools` profile. |
| `docker-compose.prod.yml` | **Staging and production** (the same file; only the decrypted `.env` differs). Image from the registry by digest, nothing built or mounted from source, db/redis unpublished, API on `127.0.0.1` only, worker + beat, healthchecks, restart policies, log rotation. |
| `docker-compose.vps-temp.yml` | **Deprecated** override for the 3-day in-house test. Kept for reference; do not use for new deploys. |

## What runs on the VPS

```
internet → nginx (80/443, TLS) → 127.0.0.1:${API_PORT} → api ─┬→ db (PostGIS, named volume)
                                                              └→ redis (broker, rate limits, token blacklist)
                                  celery_worker ─┘  celery_beat (exactly one) ─┘
```

| Service | Container name | Notes |
|---|---|---|
| `api` | `${COMPOSE_PROJECT_NAME}_api` | uvicorn on `:8000` in the container; healthcheck `/api/v1/health`. |
| `celery_worker` | `…_worker` | `--concurrency=2`. Sends e-mail/push, auto-confirms bookings, settles withdrawals. |
| `celery_beat` | `…_beat` | **Never scale beyond one.** Without it the hourly withdrawal reconcile and the 24 h auto-confirm never fire. |
| `db` | `…_db` | `postgis/postgis:15-3.4-alpine`, volume `postgres_data`. **Never `down -v`.** |
| `redis` | `…_redis` | `noeviction` (unlike the dev stack's `allkeys-lru`): it is the Celery broker, so memory pressure must raise an error rather than silently drop queued tasks or revoked tokens. |

Layout on the VPS (`DEPLOY_PATH`: `/opt/workchop` production, `/opt/workchop-staging` staging). The pipeline writes
`.env`, `docker-compose.prod.yml` and a few scripts there; there is no git clone on the server.
`<DEPLOY_PATH>/secrets/fcm-service-account.json` (Firebase) is placed by hand: production uses the production service account; staging has its own file (a `{}` placeholder while `FCM_ENABLED=false`) and must never use the production one.

## Migrations: only in the deploy

The image entrypoint (`docker-entrypoint.sh`) runs `alembic upgrade head` on every start unless
`SKIP_MIGRATIONS=true`. `docker-compose.prod.yml` sets that for **every** service, so a restart, a crash loop
or `docker compose up` never migrates. The deploy action runs the migration **once**, in a one-off container
(`docker compose run --rm api alembic upgrade head`), before the stack is started. Production additionally
takes a database snapshot first (see [BACKUPS_GUIDE.md](BACKUPS_GUIDE.md)).

Keep migrations backward-compatible for one release: an automatic rollback restores the previous *image*, but
the schema stays at the new head.

## Environment

`.env.staging.enc` / `.env.production.enc` are committed encrypted ([ENV_ENCRYPTION.md](ENV_ENCRYPTION.md)).
`.env.staging.example` / `.env.production.example` list every variable. Two things worth knowing:

- `DATABASE_URL` and `REDIS_URL` are **built by the compose file** from `POSTGRES_*`; do not set them in the env file.
- `PAYSTACK_WEBHOOK_SECRET` must equal `PAYSTACK_SECRET_KEY` (Paystack signs with the secret key; the app rejects all webhooks when it is empty).

## Nginx and TLS

Files: `deploy/nginx/` (`workchop-proxy.conf` snippet, `websocket-upgrade.conf`, and one vhost per hostname:
`api.workchop.app.conf` → `127.0.0.1:8000`, `staging-api.workchop.app.conf` → `127.0.0.1:8001`).

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx/workchop-proxy.conf    /etc/nginx/snippets/workchop-proxy.conf
sudo cp deploy/nginx/websocket-upgrade.conf /etc/nginx/conf.d/websocket-upgrade.conf   # once per VPS
sudo cp deploy/nginx/api.workchop.app.conf  /etc/nginx/sites-available/workchop-api
sudo ln -s /etc/nginx/sites-available/workchop-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.workchop.app --redirect -m <email> --agree-tos --no-eff-email
sudo certbot renew --dry-run
```

What the config guarantees (and why):

| Setting | Why |
|---|---|
| `proxy_set_header X-Forwarded-For $remote_addr` (**overwrite**, not append) | The API trusts `X-Forwarded-For` (`FORWARDED_ALLOW_IPS=*`, safe because the port is bound to localhost) so slowapi limits per real client. Appending would let a caller spoof any IP and dodge the login/OTP limits. Revisit if Cloudflare or a load balancer is ever added. |
| `Upgrade` / `Connection` via `$connection_upgrade` | WebSocket-safe if a websocket route is ever added (none today) without breaking upstream keep-alive. |
| `client_max_body_size 15m` | Portfolio images are capped at 10 MB each by the app (`app/utils/file_upload.py`), plus multipart overhead. Profile images are 5 MB. |
| 120 s read/send timeouts | Slow mobile uploads; Paystack/Dojah calls made while serving a request. |
| No auth or IP filtering on `location /` | `POST /api/v1/payments/webhook` (Paystack) and `POST /api/v1/verification/webhook` (Dojah) must be reachable; the app verifies each signature. |

## Day-to-day operations (on the VPS)

```bash
cd /opt/workchop                                   # or /opt/workchop-staging
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 -f api
docker compose -f docker-compose.prod.yml logs --tail=100 celery_beat
grep '^API_IMAGE=' .env                            # the exact digest that is running
curl -sS http://127.0.0.1:8000/api/v1/health       # (8001 for staging)
docker stats --no-stream
```

One-off tasks (run inside the running API container):

```bash
docker compose -f docker-compose.prod.yml exec api python scripts/seed_services.py
docker compose -f docker-compose.prod.yml exec api python scripts/create_admin.py
docker compose -f docker-compose.prod.yml exec api alembic current
```

Database shell (zero extra RAM; no Adminer in production):

```bash
docker exec -it workchop_db psql -U "$(sed -n 's/^POSTGRES_USER=//p' .env)" -d "$(sed -n 's/^POSTGRES_DB=//p' .env)"
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Deploy fails at "Empty deploy input(s)" | A GitHub Environment secret is unset: see the owner checklist step 6. |
| `.env.<env>.enc not found` / `Could not decrypt` | Commit the encrypted file; the `ENV_ENCRYPTION_KEY` secret must be the key that encrypted it. |
| API unhealthy right after deploy | `docker compose logs --tail=200 api`. Usual cause: a missing/invalid variable (the app refuses to boot without `SECRET_KEY`, `SERVER_HOST`, `ENVIRONMENT`, `FIRST_SUPERUSER_*`, a valid `BACKEND_CORS_ORIGINS` JSON array). |
| Bind-mount error / `/run/secrets/fcm-service-account.json` is a directory | The Firebase file did not exist on the host at first start; remove the directory at `/opt/workchop/secrets/fcm-service-account.json`, place the file, redeploy. |
| Webhooks return 401 from Paystack | `PAYSTACK_WEBHOOK_SECRET` empty or different from `PAYSTACK_SECRET_KEY` (test vs live mismatch). |
| Everyone gets rate-limited together | nginx is not overwriting `X-Forwarded-For`, or `FORWARDED_ALLOW_IPS` was removed. |
| Registration works but no OTP e-mail | `SMTP_*` missing: the app only logs the e-mail when SMTP is not configured. |
| No withdrawals reconciled / bookings never auto-confirm | `celery_beat` not running or unhealthy: `docker compose ps`, then its logs. |
| 502 from nginx | `docker compose ps`; `curl 127.0.0.1:<API_PORT>/api/v1/health`; `API_PORT` in `.env` must match the `server` line in the nginx vhost. |
