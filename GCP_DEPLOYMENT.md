# Zoiko Payroll Platform — GCP Deployment Requirements Document

**Version:** 1.0
**Prepared for:** Zoiko Payroll Platform (standalone repo — `zoiko-payroll-platform`)
**Target cloud:** Google Cloud Platform
**Status:** Draft for infrastructure sign-off

---

## 1. Purpose and Scope

This document defines the infrastructure, configuration, security, and operational
requirements to deploy the Zoiko Payroll Platform to Google Cloud Platform. It covers
the FastAPI backend, the React SPA frontend, the database, the AI assistant subsystem
("Zoiko Payroll Assist"), and all supporting services, secrets, and third-party
dependencies. It also documents open items discovered during code review that must be
resolved before a production go-live.

This document does not cover application-level functional requirements (see
`docs/Zoiko_Payroll_Assist_PRD_*` and related specs in the repository).

---

## 2. System Overview

| Layer | Technology | Deployment unit |
|---|---|---|
| Backend API | Python 3.12+, FastAPI, SQLAlchemy 2, Uvicorn | Container (Cloud Run) |
| Frontend | React 19, Vite 8, Tailwind 4 (static SPA build) | Static assets (Cloud Storage + CDN) or container (Cloud Run + nginx) |
| Database | PostgreSQL 14+ | Cloud SQL for PostgreSQL |
| Background jobs | APScheduler (in-process, `assist/scheduler.py`) | Runs inside the backend container **or** replaced by Cloud Scheduler (see §7.3) |
| AI assistant | Deterministic engine (always on) + optional OpenAI-compatible LLM gateway | Same backend container; outbound HTTPS call only |
| Email | SMTP (stdlib `smtplib`) | Outbound only; no separate service, needs relay/provider |
| File uploads | Compliance documents, organization logos | Cloud Storage via `app/core/object_storage.py` (§8) |

The system has **no message queue, no cache layer, and no separate microservices** in
its current form (see §12 for future-state notes). It is a two-tier deployment:
backend API + Postgres, with a static frontend in front.

---

## 3. GCP Service Inventory

### 3.1 Required services

| # | GCP Service | Purpose | Sizing guidance |
|---|---|---|---|
| 1 | **Cloud Run** (backend) | Hosts the FastAPI container (`Dockerfile` target `backend`) | Start: 1 vCPU / 512Mi–1Gi RAM, `min-instances=1` (see §7.3), `max-instances` per expected concurrency, request timeout ≥ 120s (SSE streaming) |
| 2 | **Cloud SQL for PostgreSQL** | Primary datastore, replaces the `postgres:16-alpine` container in `docker-compose.yml` | PostgreSQL 15/16, start at db-custom-2-4096 (2 vCPU/4GB), enable automated backups + PITR |
| 3 | **Cloud Storage** | Serves the built frontend SPA (`frontend/dist`); also hosts uploads — compliance documents + org logos (§8) | Standard storage class; one bucket for static site, one (or prefix) for uploads |
| 4 | **Cloud CDN** | Fronts the frontend bucket for caching/latency | Attach to the HTTPS load balancer backend bucket |
| 5 | **Secret Manager** | Stores all secrets (§5.2) | One secret per credential, versioned |
| 6 | **Artifact Registry** | Stores backend/frontend container images | Docker format repository |
| 7 | **Cloud Load Balancing (HTTPS)** | Single entry point; routes `/api/*` to Cloud Run backend, `/*` to frontend bucket — mirrors the existing `nginx.conf` split | Managed SSL certificate |
| 8 | **VPC + Serverless VPC Access connector** | Lets Cloud Run reach Cloud SQL over private IP | Required if Cloud SQL uses private IP instead of the Cloud SQL Auth Proxy sidecar |
| 9 | **Cloud Logging / Cloud Monitoring** | Captures backend stdout/stderr, sets up alerting | Automatic once Cloud Run is deployed; configure log-based metrics/alerts manually |

### 3.2 Recommended (non-blocking) services

| # | GCP Service | Purpose |
|---|---|---|
| 10 | **Cloud Build** | CI/CD — builds the multi-stage `Dockerfile`, pushes to Artifact Registry, deploys to Cloud Run on merge |
| 11 | **Cloud Scheduler** | Triggers Assist's KB-expiry and session-retention sweeps on a timer via authenticated HTTP call to the existing admin endpoints, as an alternative/complement to the in-process APScheduler (§7.3) |
| 12 | **Cloud Armor** | WAF / edge rate-limiting in front of the load balancer, complementing the app's own `slowapi` in-process limiter |
| 13 | **Memorystore for Redis** | Only needed if you require a *shared* rate limiter across multiple Cloud Run instances (today's `slowapi` limiter is per-instance/in-memory — see §9.2) |

### 3.3 Explicitly not needed

- No Pub/Sub, Cloud Tasks, or Cloud Functions — the app has no async job queue.
- No Redis/Memcached for application caching — none is used in the codebase.
- No Kubernetes (GKE) — a single backend container + static frontend does not warrant
  a cluster; Cloud Run is a better fit.

---

## 4. Container Build Requirements

Source: repository root `Dockerfile` (3-stage multi-stage build).

| Stage | Base image | Output | Notes |
|---|---|---|---|
| `frontend-build` | `node:20-alpine` | `frontend/dist` | `npm ci` then `npm run build` |
| `frontend-serve` | `nginx:alpine` | Static frontend container | Only needed if serving frontend via Cloud Run instead of Cloud Storage + CDN |
| `backend` | `python:3.12-slim` | Backend API container | Installs `tesseract-ocr`, `libgl1`, `libglib2.0-0`, `libpq-dev`, `gcc` as system packages — **these must be present in the runtime image**, not just build time, since `pytesseract` shells out to the `tesseract` binary at runtime for compliance-document OCR |

**Action:** Build backend and frontend as two separate images pushed to Artifact
Registry; deploy backend to Cloud Run, deploy frontend either to Cloud Run (using the
`frontend-serve` stage) or to Cloud Storage (recommended, cheaper, uses Cloud CDN).

---

## 5. Configuration and Secrets

### 5.1 Environment variables (non-secret) — set as Cloud Run env vars

| Variable | Default | Notes for GCP |
|---|---|---|
| `PAYROLL_DB_SSL_MODE` | `require` | Set based on Cloud SQL connection method — `disable` if using the Cloud SQL Auth Proxy/connector over a trusted channel, otherwise per Cloud SQL's TLS requirements |
| `JWT_ISSUER` | `zoiko-payroll-platform` | Leave as-is unless multi-environment isolation is needed |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Business decision |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Business decision |
| `APP_NAME` / `APP_VERSION` | — | Cosmetic |
| `DEBUG` | `true` | **Must be `false`/`production` in GCP** — controls the SQLite dev-fallback guard (§6) |
| `PAYROLL_CORS_ORIGINS` | localhost list | **Must be updated** to the production frontend domain(s) |
| `FRONTEND_URL` | localhost | Used in outbound email links (invite/reset/form-fill) — must be the public production URL |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_FROM_EMAIL` / `SMTP_USE_TLS` | — | See §10.1 |
| `ASSIST_MODEL_PROVIDER` | empty | `openai-compatible` to enable the LLM gateway, empty for deterministic-only |
| `ASSIST_MODEL_BASE_URL` / `ASSIST_MODEL_NAME` / `ASSIST_MODEL_TIMEOUT_SECONDS` | — | See §10.2 |
| `ASSIST_SWEEP_ENABLED` / `ASSIST_SWEEP_INTERVAL_HOURS` | `true` / `24` | See §7.3 for the Cloud Run scale-to-zero implication |
| `ASSIST_KILL_SWITCH_ENABLED` | `false` | Startup default only — live-toggled via admin endpoint/`PlatformSetting` afterward |
| `PAYROLL_GCS_BUCKET` | — | **Set in production** — uploads (compliance docs, org logos) go to this Cloud Storage bucket via `app/core/object_storage.py`; leave unset for local dev (disk under `UPLOAD_BASE_DIR`) |
| `PAYROLL_STORAGE_BACKEND` | `auto` | `auto` (default) = GCS when `PAYROLL_GCS_BUCKET` is set, else local disk; force with `gcs`/`local` |
| `PAYROLL_GCS_UPLOAD_PREFIX` | empty | Optional key prefix inside the uploads bucket (e.g. `prod`) |
| `UPLOAD_BASE_DIR` / `PAYROLL_COMPLIANCE_DOC_UPLOAD_DIR` | `/tmp/uploads/...` | Dev/local fallback only — production must set `PAYROLL_GCS_BUCKET` (§8) |

### 5.2 Secrets — must be in Secret Manager, injected as env vars at deploy time

| Secret | Purpose | Rotation note |
|---|---|---|
| `PAYROLL_SECRET_KEY` | JWT signing key | Never reuse across environments; rotating invalidates all active sessions |
| `PAYROLL_DATABASE_URL` | Full Postgres connection string (with credentials) | Store as one secret; include `+psycopg` driver prefix |
| `SETUP_KEY` | Gates Super Admin bootstrap script | Rotate/remove after initial seeding if desired |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Outbound email auth | Per SMTP provider's rotation policy |
| `ASSIST_MODEL_API_KEY` | LLM provider key (if `ASSIST_MODEL_PROVIDER` is enabled) | Only needed if the optional LLM gateway is turned on |

**Rule:** `PAYROLL_SECRET_KEY` and all passwords/API keys must never be baked into the
container image or committed to `.env` inside the image layer — inject at runtime via
Cloud Run's native Secret Manager integration.

---

## 6. Database Requirements

- **Engine:** PostgreSQL 14+ (repo tested against `psycopg[binary]>=3.1.18`).
- **Schema bootstrap:** No Alembic migrations exist. Schema is created via
  `Base.metadata.create_all` — either automatically on app startup
  (`initialize_database()` in `lifespan`) or explicitly via
  `python -m migrations.create_all.create_all`.
- **Production guardrail already in code:** if `PAYROLL_DATABASE_URL` is empty and the
  app is *not* in a recognized dev/DEBUG mode, `database.py` raises at startup rather
  than silently falling back to SQLite. **Confirm `DEBUG=false` (or `ENVIRONMENT` unset
  from `development`) is set in the Cloud Run service** so a misconfigured deploy fails
  loudly instead of writing to an ephemeral SQLite file inside the container.
- **Connectivity:** Use either (a) the Cloud SQL Auth Proxy as a sidecar/connector
  (Cloud Run's built-in `--add-cloudsql-instances` flag), or (b) private IP + Serverless
  VPC Access connector. Auth Proxy is simpler for a first deployment.
- **Backups:** Enable Cloud SQL automated daily backups + point-in-time recovery
  (payroll data is financial/regulatory — retention policy should be set deliberately,
  not left at default).
- **Seeding:** After first deploy, run `scripts/seed_super_admin` (requires `SETUP_KEY`,
  `PAYROLL_SUPER_ADMIN_EMAIL`, `PAYROLL_SUPER_ADMIN_PASSWORD`) as a one-off Cloud Run
  job or via `gcloud run jobs execute`, not as part of the normal request-serving
  container lifecycle.

---

## 7. Compute and Runtime Requirements

### 7.1 Backend (Cloud Run)

- Concurrency: FastAPI/Uvicorn handles multiple requests per instance; set Cloud Run
  `--concurrency` based on load testing (start at 40–80).
- Timeout: Set request timeout to accommodate the Assist SSE stream endpoint
  (`GET /api/assist/responses/{id}/events/stream`) — Cloud Run supports up to 60
  minutes; 120–300s is a reasonable starting point unless SSE sessions run long.
- CPU allocation: Use "CPU always allocated" if background work (the in-process
  scheduler, §7.3) must keep running between requests on a given instance.

### 7.2 Frontend

- If served via Cloud Storage + CDN: no compute needed, just bucket + LB backend
  bucket config, matching the `try_files ... /index.html` SPA-fallback behavior
  currently done by `nginx.conf` (configure the LB's 404 response to serve
  `index.html` for client-side routing).
- If served via Cloud Run (`frontend-serve` stage): treat as a second, much lighter
  Cloud Run service; can scale to zero freely since it's stateless.

### 7.3 Background scheduler — decision required

`app/modules/assist/scheduler.py` runs an in-process `BackgroundScheduler`
(APScheduler) that sweeps expired KB items and retention-expired sessions every
`ASSIST_SWEEP_INTERVAL_HOURS` (default 24h). This only runs while a container instance
is alive.

**This conflicts with Cloud Run's default scale-to-zero behavior.** Two options:

| Option | Trade-off |
|---|---|
| **A. Set `min-instances=1`** on the backend Cloud Run service | Simplest — no code change. Costs a small always-on instance. |
| **B. Disable `ASSIST_SWEEP_ENABLED` and use Cloud Scheduler** to call the existing manual admin endpoints (`POST /api/assist/admin/retention/run` and the KB-expiry endpoint) on a timer via an authenticated OIDC-signed request | More "serverless-native," lets the backend scale to zero, but requires exposing/protecting those admin endpoints for machine-to-machine auth |

**Recommendation:** Start with Option A for simplicity; revisit Option B once traffic
patterns justify scale-to-zero savings.

---

## 8. Storage Requirements — RESOLVED in code (bucket provisioning still required)

Code review found **two upload paths that wrote to local container disk**, defaulting
to `/tmp/uploads/...`:

1. `PAYROLL_COMPLIANCE_DOC_UPLOAD_DIR` (`payroll/service.py`) — compliance document
   uploads (OCR'd via Tesseract).
2. Organization logo uploads (`organizations/router.py`), same `UPLOAD_BASE_DIR`
   default.

**Cloud Run's filesystem is ephemeral** — writes are lost whenever an instance is
recycled, scaled down, or replaced by a new revision.

**Status:** the preferred code change is implemented — both paths now go through
`app/core/object_storage.py`. When `PAYROLL_GCS_BUCKET` is set (or
`PAYROLL_STORAGE_BACKEND=gcs`), uploads are written to that bucket and the DB rows
store `gs://<bucket>/<key>` references; reads (logo data URIs, document OCR/extraction)
and deletes resolve through GCS too. Without the variable, behavior is unchanged
local-disk dev mode, so existing dev workflows and tests keep working.

**Still required at deploy time:**

- Create an uploads bucket (Standard class) and grant the backend Cloud Run service
  account `roles/storage.objectAdmin` on it (§9.4).
- Set `PAYROLL_GCS_BUCKET` (+ optional `PAYROLL_GCS_UPLOAD_PREFIX`) on the service.
- Migrate any pre-existing local rows if this ever ran with real data on disk.

---

## 9. Security and Networking Requirements

### 9.1 CORS and origins

`PAYROLL_CORS_ORIGINS` must be updated from the localhost defaults to the exact
production frontend origin(s). If frontend and backend are served under the same
domain via the load balancer path-based routing (`/api/*` → backend, `/*` → frontend),
CORS becomes same-origin and this list can be minimal — this mirrors the current
`nginx.conf` proxy design intent and is the recommended topology.

### 9.2 Rate limiting

`slowapi` (`200/hour`, `60/minute` default, `core/rate_limiter.py`) is **in-process,
in-memory** — limits are per Cloud Run instance, not global. With multiple instances,
effective limits are higher than configured. Acceptable for a first deployment;
revisit with Memorystore-backed limiting if abuse becomes a concern.

### 9.3 TLS

- Managed SSL certificate on the HTTPS load balancer for the public domain.
- Cloud SQL connections encrypted via the Auth Proxy or private-IP + VPC (see §6).

### 9.4 IAM

- Backend Cloud Run service account: least-privilege — Cloud SQL Client, Secret
  Manager Secret Accessor (scoped to only the secrets it needs), and Cloud Storage
  Object Admin on the uploads bucket (see §8).
- No end-user IAM is involved — the app manages its own JWT-based auth entirely
  independently of GCP IAM.

### 9.5 Logging redaction

`main.py` already implements a logging filter that redacts `token=`/`code=` query
parameters from access logs before they reach the logging backend — this works
unchanged under Cloud Logging with no additional configuration.

---

## 10. Third-Party / External Dependencies

### 10.1 SMTP (required for email notifications)

The app sends outbound email via `smtplib` (STARTTLS or SMTP_SSL, `certifi`-backed TLS
context) — see the separate Email Communications analysis for the full list of
triggers (password reset, invites, payroll-run-approved, payslip-ready, leave
decisions, update-form invites, Assist handoff confirmations).

**Requirement:** an SMTP relay or transactional-email provider reachable from Cloud
Run (e.g., SendGrid, Postmark, Mailgun, or Google Workspace SMTP relay). Cloud Run can
reach any public SMTP endpoint over the internet by default — no special networking
needed unless the provider requires a static egress IP, in which case a **Cloud NAT +
VPC connector** is needed to give Cloud Run a stable outbound IP for allow-listing.

### 10.2 LLM Gateway (optional)

If `ASSIST_MODEL_PROVIDER=openai-compatible` is enabled, the backend makes outbound
HTTPS calls to the configured `ASSIST_MODEL_BASE_URL` (e.g., OpenAI). This is a
standard outbound call — no inbound firewall changes needed. If the provider fails,
the code already falls back to the deterministic engine automatically (no
availability risk to the core product from enabling this).

### 10.3 Tesseract OCR

Required system binary for compliance-document OCR (`pytesseract`). Already installed
in the `backend` Dockerfile stage — **no additional GCP service needed**, just confirm
the production image build includes it (it does, per current `Dockerfile`).

---

## 11. Monitoring, Logging, and Operational Readiness

| Requirement | Implementation |
|---|---|
| Application logs | Cloud Run auto-captures stdout/stderr → Cloud Logging; app already uses `logging.basicConfig` |
| Health checks | `GET /health` (DB connectivity check) and `GET /` (basic liveness) already exist — wire into Cloud Run's startup/liveness probe config |
| Alerting | Configure Cloud Monitoring alerting policies on: 5xx rate, Cloud SQL CPU/connections, Cloud Run instance count hitting `max-instances`, failed scheduled sweep jobs (if using Cloud Scheduler per §7.3 Option B) |
| Audit trail | The app has its own internal audit tables (`AssistAuditEvent`, `PayrollActivityLog`) — these are business-level audit logs, separate from and in addition to GCP's own Cloud Audit Logs (which cover GCP resource-level access, not application actions) |

---

## 12. Out of Scope / Future-State Notes

- **Microservices split:** The codebase is a modular monolith with real, enforced
  SQL foreign keys crossing module boundaries (e.g., payroll tables FK directly to
  `users.id`/`organizations.id`; Assist's `tools.py` reads payroll ORM models
  directly). A microservices decomposition is a multi-month application-level
  refactor, not a deployment-topology decision, and is **not** in scope for this
  document. If pursued later, Assist is the most loosely-coupled candidate to peel
  off first (see prior architecture discussion).
- **Multi-region / DR:** Not addressed here — single-region Cloud Run + Cloud SQL
  (with cross-region backup replication) is assumed sufficient for initial launch.
  Revisit if uptime SLAs require multi-region failover.

---

## 13. Pre-Deployment Checklist

- [ ] `DEBUG=false` set on the Cloud Run backend service (prevents silent SQLite fallback)
- [ ] `PAYROLL_CORS_ORIGINS` updated to production frontend domain
- [ ] `FRONTEND_URL` updated to production URL (used in emailed links)
- [ ] All secrets in §5.2 created in Secret Manager and wired to Cloud Run
- [ ] Cloud SQL instance provisioned, backups + PITR enabled
- [ ] Cloud SQL connectivity path chosen and tested (Auth Proxy vs. private IP + VPC connector)
- [x] **Compliance-document and org-logo uploads redirected off local disk to Cloud Storage (§8) — code done; create bucket + set `PAYROLL_GCS_BUCKET` at deploy**
- [ ] Backend `min-instances` decision made for the Assist scheduler (§7.3)
- [ ] SMTP provider selected, credentials in Secret Manager, test email sent end-to-end
- [ ] Load balancer routing (`/api/*` → backend, `/*` → frontend) configured and tested
- [ ] Managed SSL certificate issued and attached to the load balancer
- [ ] Super Admin seeded via one-off job (`scripts/seed_super_admin`), `SETUP_KEY` rotated/restricted afterward
- [ ] Health check endpoints wired into Cloud Run probes
- [ ] Logging/alerting policies configured in Cloud Monitoring
- [ ] Full backend test suite (`pytest tests/ -q`, 160 tests) passing against the production-config build before promoting

---

*End of document.*
