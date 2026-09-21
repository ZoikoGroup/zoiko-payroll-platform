# Staging Environment — Provisioning Proposal

**Status:** Proposal for review. Nothing described here has been provisioned.
The companion workflow (`.github/workflows/backend-deploy-staging.yml`) is
merge-safe but inert — it only fires on a push to a `staging` branch (which
doesn't exist yet) or a manual dispatch, and every step needs secrets that
aren't configured.

This mirrors the platform's **actual** current architecture — a single GCE
VM running the backend under a Python venv, deployed via SSH + systemd (see
`GCP_DEPLOYMENT.md` §0) — not the aspirational Cloud Run design described
elsewhere in that document. A staging environment should look like a second
copy of what's real today, not a second copy of a design that was never built.

---

## 1. Why a staging environment

Today, every push to `main` that passes the test suite deploys straight to
production (`backend-deploy.yml`). There is no environment to catch:
- A migration that runs cleanly against the tiny/synthetic pytest SQLite
  fixtures but behaves differently against a real Postgres instance with
  real data volume (this project has hit exactly this class of bug multiple
  times — VARCHAR truncation, Numeric precision limits, orphaned Alembic
  revisions).
- A frontend/backend integration issue that unit tests don't exercise (no
  browser-based test currently runs in CI at all).
- Manual smoke-testing of a risky change before it reaches real payroll data.

## 2. Two provisioning options

### Option A — Second, fully isolated GCE VM (recommended)

A separate VM, separate Postgres database, separate systemd service —
structurally identical to production, just smaller.

- **Isolation:** complete. A staging-side mistake (bad migration, crashed
  process, disk full) cannot affect production.
- **Cost shape:** roughly the cost of running a second copy of whatever the
  production VM currently costs — this doc does not have access to the
  actual VM tier/region/billing account to quote a number, and one
  shouldn't be guessed. Ask whoever manages the GCP billing console for the
  current production VM's monthly cost and assume staging costs about the
  same or less (a smaller machine type is normally sufficient for staging
  load).
- **What to provision:**
  1. A second GCE VM (same OS image/setup script as production, smaller
     machine type is fine).
  2. A second Postgres database — either a separate Cloud SQL instance
     (full isolation, roughly doubles the DB cost) or a second database on
     the *same* Postgres server under a different name (cheaper, but a
     staging query storm or lock contention could theoretically affect
     production's connections to the same server — a real, if small,
     trade-off).
  3. A second `.env` file on the staging VM with its **own**
     `PAYROLL_SECRET_KEY` (never reuse production's — see `GCP_DEPLOYMENT.md`
     §5.2's rotation rule) and its own `PAYROLL_DATABASE_URL` pointing at
     whichever DB option above is chosen.
  4. Three new GitHub Actions secrets: `STAGING_SSH_HOST`, `STAGING_SSH_USER`,
     `STAGING_SSH_KEY` — deliberately separate from `GCP_SSH_*` so a staging
     workflow run can never authenticate against the production host.
  5. A `staging` branch in the repo (the workflow's trigger).
  6. Optionally: a GitHub **Environment** named `staging` (already referenced
     in the draft workflow via `environment: staging`) with required
     reviewers, so a staging deploy can be gated the same way production
     could be — GitHub creates this automatically on first use if not
     configured, so this step can be skipped entirely for a v1.
  7. Whatever DNS/subdomain access is wanted (e.g. `staging.payroll.zoiko...`)
     if this needs to be reachable outside the team's own network — not
     required if staging is only ever accessed via VPN/SSH tunnel/IP allowlist.

### Option B — Same VM, second app instance

Run a second copy of the backend (different port, different systemd unit)
and a second Postgres *database* (not instance) on the same VM as
production.

- **Isolation:** partial. Cheaper (no second VM bill), but a staging-side
  resource spike (CPU, disk, memory) can degrade production on the same box,
  and a staging Postgres connection storm shares the same DB server's
  connection limit with production.
- **Cost shape:** effectively free beyond the marginal disk/CPU staging
  actually uses — no second VM bill.
- **Recommendation:** acceptable for a low-traffic internal tool, but this
  platform runs real payroll/financial data — the isolation Option A buys is
  worth the extra VM cost for a system in this category. Option B is noted
  here mainly as the cheaper fallback if budget is the binding constraint.

**Recommendation: Option A.** The isolation matters more than the marginal
cost difference for a payroll platform, and the failure mode Option B risks
(staging degrading production) is exactly the kind of incident a staging
environment exists to prevent, not introduce.

## 3. What this proposal deliberately does NOT include

- Actually creating any GCP resource — that requires someone with console/
  billing access to this project's GCP account, which this session does not
  have and would not use unilaterally even if it did.
- A separate frontend staging deployment — the frontend has no CD step at
  all yet (see `GCP_DEPLOYMENT.md` §0), so a frontend staging environment is
  a follow-on decision once the frontend has a real deploy path at all, not
  something to bolt on here.
- Redis/shared-state changes, load balancer changes, or any other item from
  `GCP_DEPLOYMENT.md`'s original Cloud Run proposal — those remain a
  separate, larger future-state decision, independent of this staging ask.

## 4. Rough sequencing if approved

1. Provision the VM + DB (Option A) — infra task, not a code change.
2. Add the 3 `STAGING_SSH_*` secrets to the repo.
3. Create the `staging` branch.
4. Merge `backend-deploy-staging.yml` (already drafted, safe to merge now —
   it does nothing until the above three steps happen).
5. First push to `staging` exercises the whole pipeline end-to-end; treat
   that first run as the real test of this proposal, not this document.
