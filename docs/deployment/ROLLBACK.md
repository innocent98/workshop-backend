# Rollback: Workchop API

There are two kinds of rollback. Try the automatic one's log first, then use the manual one.

**Migrations are forward-only.** A rollback restores *code* (the API, the Celery worker and the Celery beat, which all run the same image). It never undoes a migration. Keep every migration backward-compatible for one release (add columns as nullable first, drop old ones in a later release) so the previous image still works on the new schema.

## 1. Automatic (during a deploy)

If a deploy fails a migration, the API health check, or the worker/beat health, `deploy-stack` puts the **previous image back on `api`, `celery_worker` and `celery_beat`**, waits for the API to answer, prints their logs and fails the run. You do nothing; check the run log to see why it failed.

What counts as healthy: the API answers `/api/v1/health`, and the worker and beat containers reach `healthy` (their compose healthchecks) without restarting. A crash-looping worker or beat fails the deploy: payouts, the hourly withdrawal reconcile and the 24 h auto-confirm depend on them, and such an image is never marked staging-verified.

What it does **not** undo is the database (see the note at the top).

## 2. Manual (a bad release is already live)

Redeploy an earlier image. It must be one that was staging-verified; production refuses anything else.

1. Find the tag: the repository's **Packages** page, or the *Summary* of an earlier **CD (production)** run. Tags look like `sha-a1b2c3d`.
2. **Actions → CD (production) → Run workflow** → enter the tag in `image_tag` → Run.
3. The workflow looks up the image's digest, confirms a `verified-sha256-…` tag exists for those exact bytes, and deploys it (with approval, if the environment requires it).

Rollback to **staging** works the same way from **CD (staging) → Run workflow → `image_tag`**. It deploys the existing image and does not build or mark anything verified.

**`image_tag` runs are ROLLBACK ONLY. Never use them to roll *forward* to a release with a newer schema.** Migrations are skipped, so the new code would start on an old schema. To go forward, push to `develop` and let a normal deploy run.

**A manual rollback skips the migration step.** The workflow passes `run_migrations: false` whenever `image_tag` is given: no pre-migration snapshot, no `alembic upgrade head`, no seed hook. Reason: the older image's Alembic does not know the database's newer revision, so `upgrade head` would fail ("Can't locate revision") and block the very rollback it is meant to allow. The schema stays at the newer revision and the older code runs against it, which is why migrations must stay backward-compatible for one release.

If a bad migration damaged **data** (not just code), rolling back the image is not enough: restore the pre-migration snapshot with `scripts/restore_db.sh` (see `BACKUPS_GUIDE.md`) and then roll back the image so code and schema agree. Production keeps a snapshot from before every migrating deploy in `backups/`.

To go *forward* again after a rollback, push a fix to `develop`; a normal deploy runs migrations as usual.

## "Production refuses: never staging-verified"

The image was built before this pipeline existed, its staging run never passed, or its commit's `CI gate` was not green when staging finished. Options:

- Pick a different, verified tag (the normal answer).
- Re-deploy the commit through `develop` so it is built and verified (the safe answer).

There is intentionally no bypass switch.

## After a rollback

`main` still points at the bad commit. Fix forward on `develop`, wait for staging-verified, then fast-forward `main` (see `BRANCHING.md`). Do not push anything else to `main` until then.
