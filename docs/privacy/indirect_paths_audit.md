# Indirect data paths audit (ZP-PRIV-VERIFY-001, Part 1 / section D)

Status: engineering inventory, awaiting independent review. Nothing in this document is "verified".
Prepared: 2026-10-19T00:00:00Z against branch `rugvedh` working tree (uncommitted changes included).
Control register: `docs/privacy/control_register.yaml`. Defects: `docs/privacy/defect_register.csv`.

An indirect path is any place worker personal data (or tenant data that identifies workers) leaves the
primary Postgres store outside a normal, PDP-authorized request/response: jobs, files, caches, model
egress, email, logs, telemetry, backups, non-production copies, webhooks, machine clients, federation
and statutory transports.

## Method

1. Code sweep (2026-10-19) of `backend/app` and `backend/scripts`:
   - Celery: every `@shared_task` in `app/tasks/*.py`, `celery_app.py` beat schedule and signals; every
     enqueue site (`.delay(`, `.apply_async(`, `chord(`, `group(`, `send_task(`).
   - FastAPI `BackgroundTasks`: every `background_tasks.add_task` / `tasks.add_task` call site.
   - In-process schedulers started in `main.py` lifespan.
   - File responses: `StreamingResponse`, `FileResponse`, `Content-Disposition`, CSV/PDF/XML/ZIP media
     types, mapped back to their route and to the route registry row in `route_policy_inventory.csv`.
   - Object storage (`core/object_storage.py` call sites), caches (`core/cache.py`, `lru_cache`).
   - Assist gateway, tools, knowledge retrieval and public widget.
   - `services/email_service.py` senders with attachments or value tables; `modules/communications`.
   - Logging filters (`core/redaction.py`), Sentry init in `main.py`, Celery logging signals.
   - Inbound/outbound webhooks, machine clients, federation, statutory transports.
   - Operator and seed scripts in `backend/scripts/`.
2. For each path: data class (route-registry vocabulary: worker, tenant_config, aggregate, platform,
   security, public), trigger, the authorization in force today, and the gap.
3. Each row cites the control id and the automated test (or "none" where proof is human/infra).

## Inventory

Legend: Gx = known finding id; Nx = new finding raised by this audit (not yet in the defect register).

### Background jobs

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| J1 | `generate_payslips_for_run_task` / `generate_payslip_for_employee_task` (`app/tasks/payroll_tasks.py`) | worker | `POST /api/payroll/runs/{run_id}/generate-payslips` with async dispatch and `REDIS_URL` set | Payload is ids only (`job_context`). `core/job_auth.authorized_job` re-loads the user, role, tenant, org status and object scope on every execution and retry; binds tenant context + `SET LOCAL app.tenant_id`; denial emits `JOB_DENIED` | G3 fixed | Platform Engineering | D08 | `tests/privacy/test_jobs_and_machines.py::test_celery_payslip_task_refuses_a_stale_retry`; `::test_t10_job_replay_after_change_is_denied_and_audited` (T10) |
| J2 | `finalize_payroll_run_task` (chord callback) | worker (aggregates) | End of J1 chord | None of its own: ids only, filters by `organization_id`, runs with no tenant context (RLS mode `system`) | N1: callback not re-authorized. Low risk (recomputes totals for a run whose header tasks were authorized) but inconsistent with D08 "every execution" | Platform Engineering | D08 | none |
| J3 | `preview_payroll_run_task`, `check_stale_payroll_runs_task` | worker | No enqueue site found; not in beat | None (no `authorized_job`) | N2 (latent): would run unscoped; preview result (wage data) would land in the Redis result backend | Platform Engineering | D08 | none |
| J4 | `employee_tasks.bulk_create/update/delete_employees_task`, `import_employees_from_xlsx_task`, `sync_employee_statutory_profile_task`; `attendance_tasks.bulk_upload_attendance_task` | worker | Implemented, but no enqueue site found | None (`SessionLocal()`, no `authorized_job`); full PII payloads (employee dicts, base64 XLSX) would transit the broker | N2 (latent): must be wrapped in `authorized_job` with ids-only payloads, or deleted, before anything enqueues them | Platform Engineering | D08 | none |
| J5 | `report_tasks.*`, `email_tasks.*`, `billing_tasks.*`, `assist_tasks.*`, remaining attendance/auth tasks | n/a | n/a | Bodies raise `NotImplementedError` | none found (stubs) | Platform Engineering | D08 | n/a |
| J6 | `auth_tasks.revoked_token_cleanup_task`, `weekly_revoked_token_cleanup_task` (beat) | platform | Celery beat 03:00 / Sun 05:00 UTC | System maintenance, no worker data | none found | Platform Engineering | D08 | n/a |
| J7 | Redis broker + result backend (`celery_app.py`) | worker ids / job status | Any enqueue | JSON serializer, ids-only payloads for J1, `result_expires=3600` | Redis AUTH/TLS, persistence (RDB/AOF) and host access not evidenced | Infrastructure owner | D02, D08 | none (infra) |
| J8 | Celery worker logs | any | Task execution | `after_setup_logger` / `after_setup_task_logger` signals install `RedactingLogFilter` + correlation filter | G5 fixed | Platform Engineering | D03 | `tests/privacy/test_redaction_federation_governance.py::test_forced_errors_leave_no_sensitive_values_in_logs` |
| J9 | Payroll run notifications `_run_notifications_in_background` (`payroll/service.py`) | worker (recipient emails, payslip PDFs) | Run advanced to APPROVED / PAID | `BackgroundTasks`; `authorized_job(org_wide=True)` re-checks the approver | G3 fixed | Platform Engineering | D08 | `tests/privacy/test_jobs_and_machines.py::test_job_runs_under_the_requesters_tenant_scope` |
| J10 | `communications.queue_email` -> `_dispatch_in_background` | worker contact data | Any email queued during a request | Message content is built inside the authorized request; dispatch opens a fresh session with no tenant context (RLS `system`) | none found (no re-read of worker data); note dispatch is in-process and lost on restart | Platform Engineering | D08 | `tests/test_communications_dispatch.py` |
| J11 | Registration emails (`auth/service.py` `register_enterprise`, `register_trial`) | platform (org + admin contact) | Public registration | Public route; recipient is the registrant and Super Admin alert list | none found (no worker data) | Platform Engineering | A01 | n/a |
| J12 | In-process schedulers in `main.py` lifespan (assist sweep, trial, dunning, BWM aggregation, token cleanup, support-access sweep) | platform / billing aggregates | Timers | System code, no tenant context (RLS `system`) | BWM aggregation reads worker-month records for billing; its output is consumed only by tenant routes and k-suppressed platform aggregates (the per-worker invoice explanation route is retired) | Platform Engineering | A02, A06 | `tests/privacy/test_route_registry.py` |

### Files, reports and exports

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| E1 | `GET /api/payroll/payslips/{payslip_id}/download` | worker | User download | PDP `export`; org_admin/payroll_admin; object scope; `EXPORT_STARTED` event; large-export rule | none found | Platform Engineering | B07, A05 | `tests/privacy/test_t09_t12.py::test_t09_file_urls_and_job_results_are_not_reachable`; T03 |
| E2 | `GET /api/payroll/runs/{run_id}/download`, `/reports/{report_id}/download`, `/runs/{run_id}/bank-transfer-file`, `/generated-reports/{id}/certificates.zip`, `/singapore/reports/cpf-ezpay/{report_id}/file` | worker | User download | PDP `export` for org_admin/payroll_admin; support_temp denied export | none found | Platform Engineering | B07, C04 | T03, T07 (`tests/privacy/test_t01_t08.py::test_t07_grant_for_a1_read_only_denies_a2_tenant_b_writes_and_exports`) |
| E3 | `GET /api/payroll/generated-reports/{id}/certificate/{employee_id}` | worker | User download (PDF attachment) | Registered as `read` (not `export`); principals include `support_temp` and `employee` | N3: a file download classified as read. A JIT support user can download a worker certificate PDF (C04 says grants never export); no `EXPORT_STARTED` event, invisible to the large-export rule | Platform Engineering | C04, B07, E03 | none |
| E4 | `GET /api/payroll/generated-reports/{id}/rti-xml` | worker (identifiers, pay) | User download | Registered as `read`, org_admin/payroll_admin | N4: export-shaped file classified as read; no export event or alerting | Platform Engineering | A05, E03 | none |
| E5 | `GET /api/super-admin/reports/export` | aggregate | Super Admin CSV | k = 5 suppression, >= 2 orgs for money cells (DEC-1) | DEV-4: differencing ledger per process | Platform Engineering | A02, A06 | `tests/privacy/test_t09_t12.py::test_t09_bi_aggregates_suppress_small_cohorts` |
| E6 | `GET /api/super-admin/compliance/source-artifacts/{id}/download` | platform | Super Admin | Platform documents (official tax sources), no worker data | none found | Platform Engineering | A01 | `tests/privacy/test_route_registry.py` |
| E7 | Generated report detail `GET /api/payroll/generated-reports/{id}` | worker | UI | `read`; includes `support_temp` with field projection | Confirm field projection covers `rendered_data` (nested employees list) | Platform Engineering | B04, C04 | T07 |

### Object storage and caches

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| O1 | `core/object_storage.py` (GCS bucket `PAYROLL_GCS_BUCKET` or local disk): compliance documents, org logos, source artifacts, Germany PAP assets | tenant_config / worker documents | Upload and download routes | Access only through DB rows behind the PDP; keys are random UUIDs under a subdir | Bucket IAM, retention, CMEK and audit logging not in IaC; objects are not tenant-prefixed; runtime SA documented with `roles/storage.objectAdmin` (broader than needed) | Infrastructure owner | D02 | none (HP-02) |
| C1 | Redis cache `core/cache.py` | reference data | Tax resolution | Only `engine/tax_cache.py` uses it (statutory rates/slabs) | none found (no worker data cached) | Platform Engineering | B06 | `tests/privacy/test_data_layer.py` |
| C2 | Browser / proxy / CDN caches | any | Every credentialed response | `no_store_middleware` in `main.py`: `Cache-Control: no-store, private`, `Vary: Authorization` | G9 fixed | Platform Engineering | B06 | `tests/privacy/test_t09_t12.py::test_t09_responses_are_never_cacheable` |
| C3 | In-process `lru_cache` (authz callgraph, tenant table registry, secretbox keys) | metadata | Import | No data rows cached | none found | Platform Engineering | B06 | n/a |

### Assist (LLM)

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| A1 | `assist/gateway.generate_llm_answer` -> external OpenAI-compatible provider (`ASSIST_MODEL_BASE_URL`) | worker (scrubbed) | Assist chat with a model configured | `core/outbound.real_delivery_allowed("assist_llm")` gate (blocked outside production-like envs); `scrub_for_egress` on evidence/knowledge/tool output; `scrub_text` on the prompt; kill switch | G2 fixed. Residual R1: person names typed as free text in the user's question are not masked (only keyed name fields become `[PERSON]`) | Platform Engineering | D07 | `tests/privacy/test_t09_t12.py::test_t11_names_wages_and_injected_secrets_never_reach_the_model`; `::test_t11_model_egress_is_blocked_outside_production_like` |
| A2 | Assist tools (`assist/tools.authorize_tool`) | worker | Tool call | Evaluated through the PDP as a synthetic route; tenant mismatch, scope and parameter tampering denied and audited | none found | Platform Engineering | D07 | `tests/privacy/test_t09_t12.py::test_t11_tool_denials_are_neutral_and_audited` |
| A3 | Knowledge retrieval (`assist/knowledge.search_kb`) | tenant_config | Assist chat | Global items (`organization_id IS NULL`) + own tenant only | none found | Platform Engineering | D07 | `tests/privacy/test_t09_t12.py::test_t11_knowledge_never_crosses_tenants` |
| A4 | Public Assist widget (`assist/public_service.py`) | public | Anonymous chat | Public KB sentinel only; account-shaped intents redirected; kill switch applies | none found | Platform Engineering | D07 | `tests/privacy/test_t09_t12.py::test_t11_kill_switch_stops_every_assist_path` |
| A5 | Assist conversation storage and retention | worker (free text) | Chat | Tenant tables under RLS | Celery retention / archive tasks are stubs; confirm the in-process assist sweep enforces conversation retention | Platform Engineering | F03 | none |

### Email

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| M1 | Sensitive-field change notice (`send_employee_sensitive_fields_changed_email`) | worker | Bank/tax/identifier edit | Sent to the worker (and previous address if the email changed); values masked to last 4 | G1 fixed | Platform Engineering | D03 | `tests/privacy/test_redaction_federation_governance.py::test_sensitive_change_notice_carries_no_values` |
| M2 | Payslip-ready email with PDF attachment (`send_payslip_ready_email`) | worker (full payslip) | Run PAID | Recipient is the worker's own address | G7 OPEN, DEV-7: unencrypted PDF attachment over SMTP | Product | D03 | none |
| M3 | Employee created / deleted emails | worker (own name, code, department) | Employee create/delete | Worker's own address | none found (own data); plaintext email channel | Product | D03 | n/a |
| M4 | Support access / break-glass tenant notices | support | Grant events | Org admins of the tenant; ids, reason, window | none found | Platform Engineering | C06 | `tests/privacy/test_support_access.py::test_break_glass_flow_review_and_lockout` |
| M5 | Security alert email (`send_security_alert_email`) | security | Alert fired | `SECURITY_ALERT_EMAILS`; ids and counts only | Single channel (DEC-10, recorded risk) | Security Engineering | E03 | `tests/privacy/test_security_events.py::test_every_rule_fires_dedupes_and_never_carries_personal_data` |
| M6 | `communication_events` table (recipient_email, provider_response) | worker contact | Every send | Tenant table under RLS; not exposed to platform roles | Retention period for this table not defined | Platform Engineering | F03 | none |

### Logs, telemetry, audit

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| L1 | Application logs (uvicorn, app loggers) | any | Always | `RedactingLogFilter` on all root/uvicorn handlers; value patterns + sensitive keys | Free-text person names are not pattern-matched | Platform Engineering | D03 | `tests/privacy/test_redaction_federation_governance.py::test_forced_errors_leave_no_sensitive_values_in_logs` |
| L2 | nginx access logs on the VM (`deploy/nginx/zoiko-payroll.conf`) | ids, IPs, query strings | Every request | Outside the app filter | Retention and access to VM logs not evidenced | Infrastructure owner | D01, D03 | none (infra) |
| L3 | Sentry (`main.py`) | any | Unhandled error | `send_default_pii=False`, `max_request_body_size="never"`, `include_local_variables=False`, `before_send` / `before_breadcrumb` scrub. Celery workers do not initialize Sentry | G4 fixed | Platform Engineering | D04 | `tests/privacy/test_redaction_federation_governance.py::test_sentry_before_send_scrubs_body_headers_frames_and_breadcrumbs`; `::test_sentry_is_configured_without_pii_bodies_or_locals` |
| L4 | `security_events`, `authz_decision_events`, support audit | security | Every denial / privileged action | Ids and codes only; append-only triggers; hash chain | See "Other findings" (chain lock, purge GUC) | Platform Engineering | E01, E02 | `tests/privacy/test_security_events.py::test_every_security_event_is_free_of_personal_data` |

### Backups, non-production, scripts

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| BK1 | Database backups / PITR (Neon or GCP), `pg_dump` exports, snapshot buckets | all | Provider schedule / operator | Not evidenced in repo | Awaiting `deploy/security/backup_iam.tf` applied + restore drill (`deploy/scripts/restore_drill.sh`) | Infrastructure owner | D02 | none (HP-02) |
| NP1 | Non-prod databases, seeds (`scripts/seed_org.py`, `generate_synthetic_data.py`) | synthetic | Developer / CI | `core/nonprod_guard.py` refuses production-origin data in named non-prod envs; `_local_db_guard.py` for write scripts | Guard depends on production running with `ENVIRONMENT=production`/`prod` (otherwise the origin marker is never written). `_local_db_guard.py` notes the default `.env` points at a shared remote Postgres | Platform Engineering + Infrastructure | D09 | `tests/privacy/test_nonprod_data.py` (referenced by the register; not present at time of writing) |
| NP2 | Operator scripts against production: `hk_parallel_reconciliation.py export` (per-employee amounts by employee code to a local CSV), `hk_production_readonly_verification.py`, `germany_production_operator_evidence.sh`, `germany_production_db_evidence.sql` | worker (NP2 export) / aggregate | Manual, on the VM or an operator host | Read-only sessions; no PDP, no tenant approval; DB credentials of the operator | Output files with worker pay data land on operator hosts; only HP-01 (PAM, session recording) controls this | Infrastructure owner | D01 | none (HP-01) |
| NP3 | `scripts/deidentify_database.py` | all | Before any non-prod restore | Refuses production; stamps `data_deidentified_at` | Review coverage: numeric pay values are kept; text/XML payload columns whose names do not match the personal-field pattern (for example statutory filing payload XML) and object-storage files are not touched | Platform Engineering | D09 | none |

### Integrations

| # | Path | Data class | Trigger | Current authorization | Gap | Owner | Control | Test id |
|---|---|---|---|---|---|---|---|---|
| W1 | Inbound Stripe webhook `POST /api/billing/webhooks/stripe` | billing | Stripe | `stripe.Webhook.construct_event` with `STRIPE_WEBHOOK_SECRET` | G6 OPEN: a Stripe webhook signing secret was committed in `backend/stripe_listen.log` (still tracked in the working tree at time of writing; being removed). Secret must be rotated by the platform owner (HP-11, PD-001); git history still contains it | Platform owner | D06 | none (HP-11) |
| W2 | Outbound tenant webhooks (`security/machine_clients.create_webhook`, `build_delivery`) | worker events | Registration by org_admin | https only, signed (`Zoiko-Signature`), event id replay protection, tenant-pinned payload check | N5: no dispatcher calls `build_delivery` (registrations accepted, nothing is delivered); no SSRF guard beyond `https://` (internal hosts / IP literals accepted); no signing-secret rotation endpoint (disable only); payload field contract undefined | Platform Engineering | D06 | `tests/privacy/test_jobs_and_machines.py::test_webhooks_are_signed_replay_protected_and_tenant_pinned` |
| MC1 | Machine clients `zpmc_` credentials | worker (scoped) | API call | Same PDP; read-only; scope -> route map; field classes; new-network alert; rotation/expiry | none found | Platform Engineering | D06 | `tests/privacy/test_jobs_and_machines.py::test_t10_machine_client_naming_another_tenant_is_denied` |
| FD1 | Zoiko One federation (`security/federation.py`) | identity | Token exchange | Disabled until `FEDERATION_ISSUER` + key set; global claims refused; role from DB | DEV-6 (fake IdP only) | Identity Engineering | D05 | `tests/privacy/test_redaction_federation_governance.py::test_federation_refuses_over_broad_forged_or_cross_product_claims` |
| ST1 | Statutory authority transports (NL Digipoort, UK RTI, ELSTER, DSN, others) | worker | Tenant-run filing (DEC-3) | Tenant routes behind the PDP | G8 (integrity, not privacy): `ValidationServiceTransport.send` in `backend/app/modules/payroll/netherlands_digipoort.py` does not call the authority; it returns a fabricated `ACK` (`VAL-<key>`, `<Status>VALID</Status>`) for any XML starting with `<?xml` that contains `<Loonaangifte`, and `submit_return` defaults to this channel. A return can be recorded as acknowledged without any filing. Per-transport egress not inventoried individually here (follow-up) | Payroll Engineering (NL) | n/a (integrity) | none |
| SA1 | JIT support temporary login | worker (scoped, read-only) | Approved grant | Section C controls (C01-C08) | See E3 | Platform Engineering | C01-C08 | T06-T08 |

## Other findings (not data egress, but they affect the evidence)

| Id | Finding | Control |
|---|---|---|
| N6 | `security/events.emit` serializes the hash chain with a per-process `threading.Lock`. With several uvicorn workers, Celery workers or schedulers writing at the same time, two rows can take the same `prev_hash`, so `verify_chain` would report a break with no tampering. Needs a DB-level serialization (advisory lock or `SELECT ... FOR UPDATE` on a chain-head row) | E02 |
| N7 | `security_events.anchor()` and `GcsRetentionSink` exist but nothing calls them (no scheduler, no script). `SECURITY_ANCHOR_BUCKET` is read nowhere. HP-04 "anchor job scheduled" has no code to schedule | E02 |
| N8 | The append-only triggers allow DELETE when the session sets `zoiko.audit_purge = 'on'`. Any role that can connect (including the application role) can set it | E02, C08 |
| N9 | RLS mode is a client-set GUC (`app.rls_mode`). Sessions with no tenant context (jobs, schedulers, audit writers, public routes) run as `system` and see every row. RLS protects against forgotten filters on requests that carry a context; it does not protect against a holder of the application credentials | B05 |
| N10 | `production` deploy workflow triggers on pushes to `main` and `rugvedh` and checks out `GITHUB_REF_NAME` on the production VM, so a feature branch deploys to production. No `privacy-isolation` job and no `.github/CODEOWNERS` at time of writing | E06, F07 |

## Re-run checklist

Run on every release that touches a CODEOWNERS privacy path, and at least quarterly.

- [ ] `grep -rn "@shared_task\|apply_async\|\.delay(\|chord(\|send_task(" backend/app`: every implemented task that touches worker data uses `authorized_job` and an ids-only payload.
- [ ] `grep -rn "add_task(" backend/app`: every BackgroundTasks entry re-authorizes or only sends prepared content.
- [ ] `grep -rn "StreamingResponse\|FileResponse\|Content-Disposition" backend/app`: every file-producing route is `action=export` in `route_policy_inventory.csv` and excludes `support_temp`.
- [ ] `grep -rn "cache_set(" backend/app`: no worker data cached; keys tenant-namespaced if ever added.
- [ ] `grep -rn "object_storage\." backend/app`: new uploads go through DB rows behind the PDP.
- [ ] Assist: `gateway.py` egress still behind `outbound.real_delivery_allowed` and `scrub_for_egress`; T11 green.
- [ ] `grep -n "attachments" backend/app/services/email_service.py`: no new attachments; value tables masked.
- [ ] Sentry init still has `include_local_variables=False` and `before_send`.
- [ ] `git ls-files | grep -iE "\.log$|\.sqlite|dump|\.sql$"`: no logs or dumps tracked; `python -m scripts.scan_test_data` clean.
- [ ] Webhooks: dispatcher (when added) uses `build_delivery`, SSRF guard, rotation.
- [ ] Backups: restore drill result JSON newer than 90 days in EP-02/EP-05.
- [ ] Update this table, the defect register and the register's `tests:` fields; note the git SHA here.

| Run | Git SHA | Date (UTC) | By | Notes |
|---|---|---|---|---|
| 1 | (uncommitted working tree on `rugvedh`) | 2026-10-19T00:00:00Z | engineering | initial inventory |

## Status update 2026-10-19T00:00:00Z (after this audit)

| Finding | Status |
|---|---|
| N1 finalize callback | FIXED: `finalize_payroll_run_task` re-authorizes via `authorized_job` (org-wide), `job_ctx` passed through the chord |
| N2 / J3-J4 unenqueued tasks | FIXED: `@requires_job_principal` on every implemented employee / attendance / preview task; a missing or stale `job_ctx` returns "not authorized" (no autoretry) |
| N3 certificate PDF | FIXED: classified `export` (generator: `certificate` segment); `support_temp` and `employee` no longer listed |
| N4 RTI XML | FIXED: classified `export` (generator: `-xml` suffix); export events + large-export alert apply |
| N6 hash-chain concurrency | FIXED: `pg_advisory_xact_lock` before reading the head; Postgres test with 8 concurrent writers and the in-process lock disabled |
| N7 anchoring not scheduled | OPEN: PD-008 |
| N8 purge flag settable by any role | FIXED: purge honoured only for members of `zoiko_audit_purger` (Postgres test as the app role) |
| N9 client-set RLS mode / system context | OPEN: PD-007, DEV-2 / DEV-8 |
| N10 feature-branch production deploy | PARTLY: privacy-isolation job + CODEOWNERS added; branch restriction open (PD-013) |
| W2 webhooks not dispatched | OPEN: PD-009 |
| Region API / backups | OPEN: PD-010 |
| Assist free-text names | OPEN: PD-011 |
| De-identification coverage | OPEN: PD-012 |

