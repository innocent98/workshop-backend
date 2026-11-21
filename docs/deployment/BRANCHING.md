# Branching and Releasing — Workchop API

Two long-lived branches:

| Branch | Meaning | What a push does |
|---|---|---|
| `develop` | Integration. Everything lands here through a PR. | `cd-staging.yml` builds the image once, deploys it to staging, runs the live E2E, and marks the image **staging-verified**. |
| `main` | Production. Always a commit that was verified on staging. | `cd-production.yml` finds the verified image for that commit and deploys it. It never builds. |

## The release rule: fast-forward `main` to `develop`

A fast-forward moves the `main` pointer to a commit that already exists on `develop`. No new commit is created, so `main` has **the same commit SHA** that staging tested, and production can find the image built for it.

A squash merge, a merge commit, or "rebase and merge" all create a **new SHA**. No image was built for it, so production refuses to deploy (it says so in the log).

## How to release

1. Open the **Actions** tab. On the `develop` tip, the **CD (staging)** run must be green, including the *Mark image as staging-verified* job.
2. Fast-forward `main`:

```bash
git fetch origin
git push origin origin/develop:main
```

That one command pushes the remote `develop` commit to `main`. Git refuses it if it is not a fast-forward, which is the safety you want.

Equivalent, if you prefer to see it locally:

```bash
git checkout main
git pull --ff-only origin main
git merge --ff-only origin/develop     # fails if main has commits develop lacks
git push origin main
```

3. Watch **CD (production)**. It resolves the verified image, asks for approval if the `production` environment has required reviewers, deploys, and rolls back on a failed health check.

> The GitHub **Merge** button for a develop→main PR cannot fast-forward. Do not open a PR from `develop` to `main`; push as above.

## One-time repo settings

**Settings → Branches (or Rulesets):**

| Branch | Setting | Why |
|---|---|---|
| `main` | **Require linear history** | Blocks merge commits, so only fast-forwards can land. |
| `main` | Restrict who can push (maintainers only) | A direct push is how you fast-forward. Do **not** also require a pull request on `main`, or your own fast-forward push will be rejected. |
| `main` | Block force pushes and deletion | Keeps production history intact. |
| `develop` | Require a pull request and the **CI gate** check | Every change is tested before it reaches staging. |
| Environment `production` | Deployment branches: `main` only | Production secrets are unreachable from any other branch. |
| Environment `staging` | Deployment branches: `develop` only | Same, for staging. |

## Hotfixes

Do not push a fix straight to `main`: no image exists for it, so production refuses it. Hotfix through `develop` (PR, merge, wait for staging-verified, fast-forward). If production is on fire, roll back first (see `ROLLBACK.md`), then fix forward.

## If `main` and `develop` have diverged

Someone merged into `main` by another route. Do not force-push. Reset the situation on `develop`:

```bash
git checkout develop
git merge origin/main        # bring main's extra commits into develop
git push origin develop      # staging builds and verifies the result
```

When staging is verified, `develop` contains everything on `main`, so the fast-forward works again.

## Tagging a release (optional)

A version tag is a label on a commit production already runs. It builds and deploys nothing:

```bash
git tag -a v1.4.0 -m "v1.4.0" && git push origin v1.4.0
```
