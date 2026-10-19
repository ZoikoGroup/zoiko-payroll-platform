# Mexico (MX) — Phase 7 Implementation Report: CFDI 4.0 + Nómina 1.2 lifecycle + PAC seam

Spec ZP-MX-ENG-001 v1.0 §13 (MX-016–MX-018, MX-035, MX-061, MX-062) · plan `MEXICO_PHASE_7_PLAN.md`.

**Approved 2026-10-17:**
- D1–D3 and D5–D9 as recommended.
- D4: reuse the HK durable-storage path, with its production refusal of the `/tmp` fallback. CFDI XML retention is a legal / Phase 10 retention-policy item.
- The §4.2 UNKNOWN rule is revised.
- D10–D12 stay open.

**Base:** `nikhil` = `8d287f3` (tree identical to `origin/main` `46c7957`, PR #108). PR #108's deploy run `39005680799` was green at every step, and so was frontend build `39005680877`.

**Alembic:** before this phase there was a single head, `c4f7a2d9e6b1` (201 revisions). Now there is a single head, **`d8b3e5f1a2c7`** (202 revisions).

The work is **staged on `nikhil`**; nothing is committed, pushed or merged.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite, 5 chunks (317 files) on scratch SQLite, **after every fix in this report** | **6,633 passed, 1 failed, 58 skipped, 2 xfailed** (6,694 tests). The one failure is the known **OOS-4** HK test: it reads the untracked local `docs/HONG_KONG_RELEASE_EVIDENCE/…/HK_CONFIGURATION_MASTER_MATRIX.csv`, which is absent from git, so CI skips it. Not caused by Mexico. |
| First full run (before the browser-found fixes in §6) | 6,631 passed, the same 1 OOS-4 failure, 58 skipped, 2 xfailed. |
| After the same-pay-date tie-break (§6.2, a Mexico-only change) | All Mexico files: **584 passed, 19 skipped**. Shared run-flow files (generate / advance): **1,387 passed, 1 skipped**. The full suite was not re-run for this change. |
| Phase 7 tests | `test_mexico_cfdi_lifecycle.py` (13 functions, 14 cases), `test_mexico_cfdi_unknown.py` (9), `test_mexico_cfdi_lineage.py` (6), `test_mexico_cfdi_routes.py` (3), `test_mexico_cfdi_migrations.py` (6, of which 4 run on PostgreSQL). With PG: **38 pass**. Plus, in `test_mexico_run_inputs.py`, 1 directional test and 1 same-pay-date tie-break test run in both commit orders (§6.2). `test_mexico_dormancy.py` covers the new routes. |
| Migration on **PostgreSQL 17** (throwaway cluster) | 4/4 PG tests, including the real `alembic upgrade head` through `env.py`, `alembic current` and `scripts.check_schema_drift`. Lock times are measured in §3. |
| Browser, flag **off** (the production setting) | **11/11.** `phase7-evidence/RESULTS-off.md`; screenshots inspected. |
| Browser, flag **on** (synthetic builder / signer / mock PAC, harness-only) | **16/16**, with no 5xx, no console errors and no page errors. `phase7-evidence/RESULTS-on.md`; every screenshot inspected. |
| ESLint (`src`) | **185 errors**, unchanged from the Phase 6 baseline. Every new file: 0 errors. `RunDetailPanel.jsx` has 1 error and `payrollService.js` 31, identical to HEAD. |
| `check:undefined` / `vite build` | 513 files clean / passes. |

## 2. What was built (plan order §11)

**Migration `d8b3e5f1a2c7` (mx_cfdi_m5)** creates three new tables. Nothing on any shared table is altered.

- `payroll_mx_cfdi_documents`:
  - the document's status, unknown action, UUID, SAT certificate number, PAC provider / environment / response, payload hash and `xml_storage_ref`;
  - cancellation and substitution lineage: `replaces_document_id`, `replaces_uuid` and `replaced_by_uuid`;
  - a unique `idempotency_key`;
  - unique (org, series, folio), a partial unique "one live document per payslip", and a partial unique UUID.
- `payroll_mx_cfdi_outbox`: the action, `attempt_no`, `payload_hash`, `idempotency_key`, status and `operator_confirmed_by_id`, with unique (document, action, attempt).
- `payroll_mx_cfdi_events`: an append-only timeline (type, from / to status, payload hash, detail, actor, time).

The migration has a literal `op.create_table` per table. It is guarded (`_has_table` / index checks), runs under `SET LOCAL lock_timeout = '5s'`, and its downgrade drops the three tables.

**Backend**

- **`mexico_pac.py`**: a thin `PacAdapter` ABC with four calls (`stamp`, `query_status`, `cancel`, `query_cancel_status`), plus small result dataclasses and a `CredentialHandle` that carries only an id / kind / ref.
  - `_ADAPTERS` is **empty** in `app/`, so `get_adapter` raises `MX_PAC_NOT_CONFIGURED`.
  - `ProviderRetryConfig(min_wait_seconds, min_not_found_queries)` lives in `_PROVIDER_RETRY_CONFIG = {}`, with **no default**. `retry_config()` returns None unless queries ≥ 2 and wait > 0.
  - The adapter interface is deliberately thin (D10), so the chosen provider fills one class.
- **`mexico_cfdi_builder.py`**: `CfdiPayloadBuilder` / `CfdiSigner` seams.
  - The production `SatBuilder` refuses with `MX_CFDI_BUILDER_BLOCKED` (S28 / S30 / S4).
  - `GcpSmSigner` refuses with `MX_CSD_SIGNING_BLOCKED` **before** any Secret Manager call.
  - Each seam has a read-only `blocked()` probe (§6.1).
- **`mexico_cfdi_service.py`** covers:
  - Preflight, in plan §2 order: committed run, approval drift, Active schema release, calculated payslip, employer, ACTIVE unexpired CSD, PAC provider / environment, and a passed sandbox stamp test before PRODUCTION (D7).
  - Generation: folio, builder → signer → durable storage through `object_storage.durable_storage_refusal` + `save_upload(subdir="mx_cfdi/{org}/{run}")`, which refuses the `/tmp` fallback in production (D4). It never logs the XML.
  - Idempotency key per document: `"mxcfdi-" + sha256(org:item:folio:payload_hash)[:56]`. Retries reuse the key and the payload. Queries use `{key}:q{n}` and cancels `{key}:c{n}`.
  - The state machine of plan §4.1 (any other transition is `MX_CFDI_ILLEGAL_TRANSITION`). Every transition writes an event.
  - The outbox, processed explicitly by an operator (D5):
    - status queries run first in each batch;
    - non-PENDING items are skipped;
    - one commit per item, with SUBMITTED committed **before** the outward call;
    - `SKIP LOCKED` on PostgreSQL.
  - **UNKNOWN (§4.2 as revised):**
    - a timeout or an unreadable answer → UNKNOWN; nothing is retried automatically;
    - `request_status_query` comes first;
    - a FOUND answer adopts the UUID (no second stamp);
    - after ≥ 1 NOT_FOUND since the last UNKNOWN entry, `confirm_retry` needs an admin **and** a reason. It records `OPERATOR_RETRY_CONFIRMED` and re-queues STAMP with the **same payload and the same idempotency key**;
    - `definitively_not_found` is never true without a provider config, so an automatic retry is impossible until D10;
    - a late FOUND while SIGNED adopts the UUID and withdraws the pending retry;
    - a UUID conflict → UNKNOWN;
    - `reconcile_after_restore` moves everything in flight to UNKNOWN.
  - **Cancellation and substitution (D6):** reasons come only from an Active `c_MotivoCancelacion` catalog. A reason that needs a related UUID must name this document's STAMPED replacement. The chain runs STAMPED → CANCEL_REQUESTED → CANCELLED → REPLACED, keeping the original UUID and setting `replaced_by_uuid`. `create_replacement` records the lineage; the correction run itself is Phase 9.
  - **Reset (plan §6):** `downstream_reasons` names every acted document (SUBMITTED, UNKNOWN, STAMPED, CANCEL_REQUESTED, CANCELLED, REPLACED), so `reset_run` refuses with `MX_RESET_DOWNSTREAM_ACTED`. Untransmitted GENERATED / SIGNED documents are VOIDED on reset, and their PENDING outbox items fail.
  - Views: run summary / lane, document view / detail (never XML), run documents, and the Super Admin `lifecycle_overview`.
- **`mexico_run_service.py`**:
  - `run_downstream_actions` → `downstream_reasons`;
  - `reset_run` voids untransmitted documents;
  - `run_status["cfdi"]` is the CFDI lane;
  - the `_month_to_date` fix (§6.2).
- **Routes** (org router, behind the Phase 4a guard):
  - `GET /runs/{id}/cfdi`, `POST /runs/{id}/cfdi/generate`;
  - `POST /cfdi/outbox/process`;
  - `GET /cfdi/documents/{id}`, `POST /cfdi/documents/{id}/status-query`, `POST /cfdi/documents/{id}/confirm-retry`, `POST /cfdi/documents/{id}/cancel`;
  - `POST /cfdi/reconcile`, `GET /cfdi/cancellation-reasons`.
- **Super Admin (read-only):** `GET /super-admin/compliance/mexico/cfdi?organization_id=`.

**Frontend**

- `MXCfdiStagePanel` (run stage 6):
  - shows the preflight reasons and the Generate / Process PAC queue buttons;
  - shows an UNKNOWN banner and **no retry button**;
  - renders nothing on 403 (§6.4).
- `MXCfdiDetailDrawer`:
  - status, UUID, payload hash, lineage, the event timeline and the PAC queue;
  - for UNKNOWN: "Query status", then "Confirm retry (same payload, same key)", which is disabled until a NOT FOUND answer and needs a reason.
- `MXCancelReplaceDialog`: catalog reasons only; asks for the replacement UUID when the reason requires one.
- `MXCfdiLifecycleTab`: a Super Admin tab with counts, UNKNOWN items, the schema release and the platform blocks.
- `MXRunStatusBadges`: the CFDI badge reads the lane, with tones for STAMPED / REPLACED / UNKNOWN / REJECTED / IN_PROGRESS. Its caption is updated for Phase 7.

**Tests only (never imported by `app/`):** `tests/_mx_mock_pac.py` (a deduplicating mock PAC: the same key always gives the same UUID, and `stamps_by_key` counts the real stamps) and `tests/_mx_cfdi_helpers.py` (synthetic builder / signer, labelled `SYNTHETIC-NOT-A-CFDI`).

The tests the user asked for:
- `test_late_found_after_not_found_produces_no_second_stamp`
- `test_retry_reuses_the_same_payload_and_the_same_key`
- `test_definitively_not_found_needs_provider_config_without_default`

## 3. Migration `d8b3e5f1a2c7` — measured on PostgreSQL 17

Alembic's `env.py` runs the whole upgrade in one transaction, so locks taken by the FK creation are held until commit.

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payslip_items` / `payroll_runs` / `payroll_employees`, from the first FK-creating statement to commit | **105.02 ms** (first run), **118.09 ms** (re-run 2026-10-19). |
| In flight | The migration holds AccessShare + ShareRowExclusive on the three tables. `payslip_items` stays **readable** (a count returned 1). A writer's `ROW EXCLUSIVE NOWAIT` is **refused**, so writes wait for about 0.1 s. |
| A writer holding `payslip_items` during the upgrade | The upgrade gives up after **5.14–5.17 s** (first run) / **5.09 s** (re-run) through `lock_timeout`, and **nothing is created**: the transaction rolls back, so a retry is safe. |
| Real CLI path | `alembic upgrade head` through `env.py`, `alembic current` = `d8b3e5f1a2c7`, and `check_schema_drift` clean. |

Not sampled separately: the FKs to `organizations`, `users` and `payroll_mx_cfdi_schema_releases` take the same lock mode inside the same transaction, so they are held for at most the same window.

## 4. What this does in production when merged (plan §8)

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `d8b3e5f1a2c7` | Three **new, empty** tables. **No column on any shared table.** The head moves `c4f7a2d9e6b1` → `d8b3e5f1a2c7`. FK creation takes SHARE ROW EXCLUSIVE on `payslip_items` / `payroll_runs` / `payroll_employees` (and on `organizations` / `users`) for about **0.1 s** (measured 105–118 ms). Reads continue and writes wait. If a long writer holds a table, the deploy's migration step **fails after 5 s with nothing created** and can simply be re-run. |
| CFDI service, state machine, outbox | **Unreachable.** Every new org route sits behind the Phase 4a guard (403, verified in the browser with the flag off). No Mexican run can be committed (no MX employee, no Active MX pack). The builder and signer refuse. **No document can exist.** |
| `PacAdapter` registry (`_ADAPTERS`) | **Empty** in `app/`. No outbound call to any PAC is possible; the mock lives only in `tests/`. |
| Retry rule | `_PROVIDER_RETRY_CONFIG` is empty with no default, so "definitively not found" is never true. Any retry would need an operator's confirmation; there is nothing to retry anyway. |
| `run_downstream_actions` | Queries an empty table and returns `[]`, so **reset behaviour is unchanged.** |
| `_month_to_date` fix (§6.2) | Mexico-only and dormant (`calc_inputs` refuses `MX_DORMANT`). No effect. |
| Storage | Nothing is written. If it ever were, production refuses the `/tmp` fallback (D4). |
| Secrets | Nothing is read. Signing refuses before any Secret Manager call; only `gcp-sm://` refs and fingerprints are stored (Phase 3). |
| Super Admin "CFDI lifecycle" tab | A read-only page showing 0 documents, "none Active" schema release, and the three blocks (`MX_CFDI_BUILDER_BLOCKED`, `MX_CSD_SIGNING_BLOCKED`, `MX_PAC_NOT_CONFIGURED`). |
| Run screen / badges | The CFDI stage renders nothing for a refused (403) run, and no other country's run screen changes (NL regression verified with the flag both on and off). |

**Net effect:** an additive schema change of three empty tables, one new read-only Super Admin tab, and no behaviour change for any jurisdiction.

## 5. Browser evidence (`docs/mexico/phase7-evidence/`)

The harness lives in `phase7-evidence/harness/`:
- `setup_db.py init | release | replace` builds a scratch SQLite DB with `@example.com` users.
- `serve.py on | off` starts the backend.
- `patches.py` is harness-only: it installs the synthetic builder / signer and a mock PAC scripted through a JSON control file, which logs every call's key and payload hash.
- `acceptance.py` drives installed Chrome against `vite preview` of the current build.

The harness CORS origin is passed as a process environment variable; `backend/.env` was not touched.

**Flag off (11/11):**
- NL runs are unchanged.
- The Mexican run shows only the dormancy refusal, with no CFDI stage.
- All 7 CFDI routes → 403.
- The Super Admin tab shows 0 documents and the three production blocks.

**Flag on (16/16):**

1. The committed run's preflight blocks on `MX_CFDI_NO_ACTIVE_SCHEMA_RELEASE`, and Generate is disabled.
2. With a synthetic release: Generate → SIGNED → Process → **STAMPED**. The CFDI badge → STAMPED while Payroll / Authorities / Bank are unchanged.
3. A forced PAC timeout → **UNKNOWN banner, no retry button**. The drawer offers "Query status"; the confirmed retry is disabled before any NOT FOUND, and the drawer says no provider rule exists.
4. Query → NOT FOUND (1) → the reasoned, confirmed retry → **STAMPED**. The PAC call log shows both STAMP attempts with **the same idempotency key and the same payload hash**. The events read `STATUS_NOT_FOUND`, `OPERATOR_RETRY_CONFIRMED`, `RETRY_READY`, `STAMPED`, and the queue reads `STAMP #2 · operator-confirmed`.
5. A replacement CFDI on a synthetic correction run is stamped. The cancel dialog lists only catalog reasons; SYN1 asks for the replacement UUID.
6. The lineage drawer shows the original **REPLACED**, its UUID kept, "Replaced by" = the replacement UUID, and the events `CANCEL_REQUESTED → CANCELLED → REPLACED`.
7. Reset → 409 `MX_RESET_DOWNSTREAM_ACTED`.
8. Badges: CFDI **REPLACED**; Payroll / Authorities / Bank unchanged.
9. NL is unchanged.
10. The Super Admin tab shows "3 document(s): REPLACED 1 · STAMPED 2".

## 6. Deviations and defects found during this phase

The browser pass found four problems that the tests had not; each is fixed and covered.

1. **The Super Admin overview probed the seams by calling them.** It called `build({})` / `sign(b"", None)` and caught `MXBlock`, so a working builder raising anything else would have turned the tab into a 500. The seams now have a read-only `blocked()` probe, and the overview never builds or signs. Test: `test_super_admin_overview_probes_the_seams_without_calling_them`.
2. **Phase 6 defect (on `main`, dormant): the month-to-date counted LATER payments.** `mexico_run_service._month_to_date` added every committed run in the pay-date month, including runs paid after this one. Committing Jun 16–30 changed Jun 1–15's subsidy month-to-date, which invalidated its approval (`MX_APPROVAL_INVALIDATED`, drift `monthToDate`) and blocked its CFDI. Now only payments ordered before this one count (the order is defined below). Directional test: `test_month_to_date_never_counts_a_later_payment_so_an_earlier_approval_survives` passes with the fix and **fails without it**. No production effect: Mexico is dormant.

   **Tie-break for the same pay date (added before commit, 2026-10-19).** The month's payments are ordered deterministically by **(pay date, `committedAt`, run id)** (`mexico_run_service._payment_order`). A run counts another committed run of the same month only if that run comes **before** it in this order. A run that is not committed yet sorts after every committed run of its pay date; a preview sorts after everything on its date.

   The first version of the fix broke a same-day tie by run id alone. That failed when the higher-id run was committed first: committing the lower-id run afterwards changed the first run's month-to-date and invalidated its approval. Ordering by commit time removes that, because a run committed later can never enter an already committed run's month-to-date.

   Test: `test_month_to_date_same_pay_date_tie_break_is_commit_order`, parametrised over both commit orders (id order and reverse id order). In each order:
   - the run committed first has month-to-date 0;
   - the run committed second counts exactly the first run's taxable income;
   - both approvals show no drift.

   With the id-only rule, the reverse-order case **fails**; with the commit-order key, both pass.

   This is intentional: a run with an *earlier* pay date that is committed after a later-dated run still changes the later run's month-to-date, which invalidates its approval. That payment really was made earlier in the month, so the later run's subsidy has to be recalculated.

   After this change: all 42 Mexico test files gave **584 passed, 19 skipped** (the skips are the PostgreSQL-only tests). The 44 shared test files that drive generate / advance (the run-integration surface) gave **1,387 passed, 1 skipped**.
3. **The run's CFDI lane showed IN PROGRESS for a finished cancel / replace chain.** The lane now reads each payslip's latest document:
   - any UNKNOWN → UNKNOWN;
   - anything still moving → IN_PROGRESS;
   - else REJECTED, VOIDED or STAMPED;
   - else CANCELLED / REPLACED.

   Asserted in the lineage tests.
4. **Flag off: the CFDI stage rendered a box around the 403 message.** It now renders nothing on 403; the Phase 6 preflight panel already shows the dormancy refusal.

Design notes:

5. **No replacement route.** `create_replacement` has no route: the correction run is Phase 9. The harness calls the service directly to show the lineage.
6. **Explicit outbox processing (D5).** The outbox is processed only by an operator; there is no background worker.
7. **XML retention.** Retention of the stored XML is an open legal / Phase 10 item (D4); nothing deletes it.

## 7. Open / prerequisites (production cannot generate a CFDI until all are done)

- **D10: PAC provider.** Implement one `PacAdapter` subclass and register it in `_ADAPTERS`. Its `ProviderRetryConfig` (minimum wait, and more than one NOT_FOUND query) comes from that provider's documentation. Until then, every retry needs operator confirmation.
- **D11: SAT sources S28 / S30 / S4.** These cover the Nómina 1.2 catalog workbook with `nomina12.xsd`, the CFDI 4.0 catalogs / Anexo 20 with `cfdv40.xsd`, and S4. They are needed for the real `SatBuilder` and the Active schema release with `c_MotivoCancelacion` (cancellation reasons stay unavailable until then).
- **D12: GCP Secret Manager** live in production, for `GcpSmSigner` to resolve the employer's CSD key behind its `gcp-sm://` ref.
- **Durable storage, a shared prerequisite.** Cloud Storage (`PAYROLL_GCS_BUCKET` / `PAYROLL_STORAGE_BACKEND=gcs`) must be configured in production, or CFDI generation refuses (D4). The same configuration closes the HK durable-storage item (G5 finding F-8, `object_storage.durable_storage_refusal`), so one infrastructure change serves both. XML retention is a legal / Phase 10 policy.
- **Carried over:** G1–G8, Phase 8 / 10 registering in `run_downstream_actions`, and OOS-4. OOS-4 depends on the untracked HK owner pack (`docs/HONG_KONG_RELEASE_EVIDENCE/`, HK "commit 8"), not on code.
