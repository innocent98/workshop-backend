# Pre-Deploy Guide: Workchop API

Run the **fast** checks locally before pushing; CI runs everything heavy (full test suite, image build, Trivy,
Semgrep, live staging E2E) on every push, so reproducing it on a laptop only wears the machine.

## Run locally (every push)

```bash
poetry run black --check app tests
poetry run isort --check-only app tests
poetry run flake8 app tests
poetry run pytest tests/<the files you touched> -q --no-cov     # only the tests for what you changed
```

Those are the exact commands the `lint` job runs (`.github/workflows/ci.yml`). Added or edited a migration? Also, on a
**scratch** PostGIS database (never a real one):

```bash
poetry run alembic heads                      # must print exactly one head
poetry run alembic upgrade head && poetry run alembic downgrade -1 && poetry run alembic upgrade head
```

## Leave to CI

The full `pytest` run, the e2e smoke suite, coverage, the image build and Trivy scan, Semgrep. Do **not** run them
locally. When CI goes red, read CI's output, reproduce just the failing step, fix, push once.

## Why migrations must be re-runnable

The deploy runs `alembic upgrade head` on every deploy. Alembic skips revisions already applied, so that is safe, but a
data backfill inside a migration runs exactly once against the real data: write it to be correct on an empty table and
on production-sized data, and remember production is snapshotted right before it runs (see `BACKUPS_GUIDE.md`).

## Common pitfalls

### 1. `.env.<env>.enc` out of sync

If you edit `.env.staging` locally but forget to re-encrypt, CD ships the old env:

```bash
./scripts/env.sh encrypt staging && ./scripts/env.sh verify staging
git add .env.staging.enc && git commit -m "chore: bump staging env"
rm .env.staging
```

### 2. New setting without a value in the encrypted env

`app/core/config.py` has required fields (`ENVIRONMENT`, `SERVER_HOST`, `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`,
`FIRST_SUPERUSER_*`) and optional ones with defaults. Add any new variable to **both** `.env.*.example` files, set it in
the real env files, re-encrypt, and push the `.enc` together with the code that reads it.

### 3. Test pipeline changes from a branch, carefully

`cd-staging.yml` and `cd-production.yml` only run automatically for pushes to `develop` and `main`. To try a change to
`.github/workflows/` or `actions/deploy-stack`, push the branch and use **Actions → Run workflow** with that branch
selected: it uses that branch's copy of the file. A manual staging run with `image_tag` redeploys an existing image and
builds nothing.

### 4. Migrations that add NOT NULL without a default

Adding a NOT NULL column to a non-empty table fails unless the column has a server default, or it allows NULL, you
backfill, then tighten to NOT NULL in a later migration. Keep migrations backward-compatible for one release: an
automatic rollback restores the previous image but not the schema.
