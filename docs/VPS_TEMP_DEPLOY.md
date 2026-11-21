> **DEPRECATED (2026-11-21).** This was the 3-day in-house test deploy. It is superseded by the CI/CD pipeline,
> `docker-compose.prod.yml` and [`docs/deployment/DEPLOYMENT_GUIDE.md`](deployment/DEPLOYMENT_GUIDE.md). Kept for
> reference only; do not use it for new deploys. It is not deleted because it documents the interim stack
> (`workchop-temp_*`, port 8001) that may still be running on the VPS until it is torn down (section 7).

# Workchop API Temporary VPS Deploy (3-Day In-House Test)

This guide deploys the backend as an isolated temporary stack on a VPS that already runs another Docker project.

## What this setup isolates

- Project namespace: `workchop_temp`
- API host port: `8001` (container still listens on `8000`)
- Separate container names: `workchop-temp_*`
- Adminer only if profile `tools` is enabled

## 1. Prepare VPS files

On VPS, place project at:

```bash
/opt/workchop-api
```

Then copy Firebase service account JSON to:

```bash
/opt/workchop/secrets/fcm-service-account.json
```

Required because compose mounts:

- host: `/opt/workchop/secrets/fcm-service-account.json`
- container: `/run/secrets/fcm-service-account.json`

## 2. Environment setup

Create `.env` from your current working config:

```bash
cp .env.example .env
```

Set these for VPS use:

- `DATABASE_URL=postgresql://user:password@db:5432/workchop_db`
- `REDIS_URL=redis://redis:6379/0`
- `FCM_SERVICE_ACCOUNT_FILE=/run/secrets/fcm-service-account.json`
- `FCM_SERVICE_ACCOUNT_FILE_HOST=/opt/workchop/secrets/fcm-service-account.json`
- `SERVER_HOST=https://<your-domain-or-ngrok>`
- `BACKEND_CORS_ORIGINS=[...]` with valid frontend origins

## 3. Start temporary stack

```bash
API_HOST_PORT=8001 docker compose \
  -f docker-compose.yml \
  -f docker-compose.vps-temp.yml \
  -p workchop_temp \
  up -d --build
```

Check status:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp ps
```

## 4. Seed services (inside server)

Run once after stack is healthy:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp \
  exec api python /app/scripts/seed_services.py
```

Optional test accounts:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp \
  exec api python /app/scripts/create_test_accounts.py
```

## 5. Health checks

```bash
curl -i http://127.0.0.1:8001/health
curl -i http://127.0.0.1:8001/api/v1/health
```

## 6. Logs

```bash
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp logs -f api
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp logs -f celery_worker
```

## 7. Stop and remove temporary stack

```bash
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp down
```

To remove volumes too (DB/Redis data):

```bash
docker compose -f docker-compose.yml -f docker-compose.vps-temp.yml -p workchop_temp down -v
```

