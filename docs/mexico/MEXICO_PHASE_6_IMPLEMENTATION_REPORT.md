# Mexico (MX) — Phase 6 Implementation Report: Payroll run integration

Spec ZP-MX-ENG-001 v1.0 §13 (MX-036, MX-039–MX-041) · plan `MEXICO_PHASE_6_PLAN.md`. Decisions D1–D12 were approved as recommended, with D1 = the approved-hours table and D4 = option (a). D13, the reset rule, the lock ordering and the FK rules were added on 2026-10-17.

Base: `nikhil` fast-forwarded to `main` `5775299` (PR #106, Phase 5 + Brazil PR #105). Single Alembic head before this phase: `b7a1c9e3d5f2`. The work is staged on `nikhil`; nothing is committed.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite, 5 chunks (312 files) on scratch SQLite | **6,583 passed, 2 failed, 54 skipped, 2 xfailed.** One failure is the known **OOS-4** HK test. The other was `test_model_tables_have_migrations`, which needs a literal `op.create_table` per new table; the migration was fixed and the test passes. The full suite was not re-run after that fix (see the next row). |
| Re-run after the late fixes (migration literals, response schema) | Migration, manifest and metadata tests: **23 passed** (including PostgreSQL). Schema-sensitive suites (DE, NL, SG, CH payslip surfaces, shared-helper snapshot) and all Mexico tests: **1,098 passed, 15 skipped**. |
| New Phase 6 tests | `test_mexico_run_integration.py` (27), `test_mexico_run_inputs.py` (10), `test_mexico_run_dormancy.py` (10), `test_mexico_run_migrations.py` (6, 4 of them on PostgreSQL). All pass. |
| Migration on **PostgreSQL 17** (throwaway cluster, `MX_PG6_TEST_URL`) | 4/4, including the real `alembic upgrade head` through `env.py`, `alembic current` and `scripts.check_schema_drift`. Lock-hold times measured (§3). |
| Browser, flag **off** (production setting) | **8/8.** See `phase6-evidence/RESULTS-off.md`. |
| Browser, flag **on** (synthetic Active test pack) | **12/12.** See `phase6-evidence/RESULTS-on.md`. Key screenshots inspected. |
| ESLint (`src`) | 185 errors. No new errors in any file this phase touched (each was checked against HEAD). The +1 over Phase 4's 184 arrived with the Brazil merge. |
| `check:undefined` / `vite build` | 509 files clean / passes. |

## 2. What was built

**Backend**
- **`mexico_run_service.py`** (new) does the following:
  - **Guard** (plan §1): refuses with `MX_DORMANT`, `MX_ORG_NOT_MEXICAN`, `MX_RUN_ORG_MISMATCH` or `MX_RUN_TYPE_PHASE9` before any read.
  - **Input builders** (plan §3), all read-only and dated by the run's pay date:
    - the period from the run's dates;
    - the S28 pay-frequency mapping (D3);
    - salary days by the labour-policy convention (D13);
    - contribution segments split at every row change, each with its own rows;
    - absence and incapacity from attendance rows;
    - approved hours (D1);
    - the bimester accumulator from committed rows, or an approved opening balance (D4);
    - month-to-date from committed runs;
    - the zone, registration, ACTIVE premium and labour policy, which must have passed its floor check;
    - classifications, notices, the ISN pack and the pack rows (`pack_rows_for_golden`, with row-level dates).
  - **Payslip split** (D2), **snapshot**, and the **blocked sentinel**.
  - **Preflight exceptions:** BLOCK can never be acknowledged; WARN needs a note.
  - **Approval:** stale or blocked payslips are refused; the fingerprint is stored and **`commit_run`** writes every ledger in the APPROVED transaction, idempotently.
  - **Drift check:** `approval_drift` / `run_status` names the changed component (MX-040).
  - **AUTHORIZED / PAID / CLOSED** are refused (MX-041).
  - **`reset_run`** returns the run to Review and deletes its ledger rows, after checking **`run_downstream_actions`** (empty today; Phases 7, 8 and 10 must register their checks).
  - **`refuse_if_committed`** blocks deletion of a committed run's items or the run itself.
  - **`payment_treatment`** holds every MX item (D11).
  - **Approved hours and opening balances**, both four-eyes with evidence.
- **`mexico_service.py`:** `calc_inputs`, `_mx_before_run_transition` and `payment_treatment` now delegate to the run service. `calc_inputs` no longer raises `MX_ENGINE_NOT_IMPLEMENTED`; the guard replaces it. `statutory_summary` is now phase 6.
- **`service.py`** (Mexico-only hunks):
  - **Preview** (`preview_payroll_run`): guarded read-only inputs. The pay date is `period_end`, and preview refuses when it's missing (never `date.today()`). A blocked employee gets a blocked row; dormancy refusals abort the preview; MX rows get `mxPreview`.
  - **Generate** (`_compute_payslip_values`): inputs, money columns from the Mexican lines, and `mx_calculation_snapshot`.
  - **Generation loop:** a FAILED sentinel plus exception rows per reason; dormancy refusals abort.
  - **Regenerate:** clears the employee's exceptions on success.
  - **`add_payslip_item`:** computed amounts; disagreeing manual amounts are refused, never replaced.
  - **Serializer:** emits `mxCalculationSnapshot`.
  - **Deletion:** `delete_payroll_run` and `delete_payslip` refuse a committed MX run.
  - **Import:** `MissingComplianceConfigurationError` is now imported at module level.
- **`schemas.py`:** `mxCalculationSnapshot` on the payslip response. *Found by the browser check: the shared response model was stripping it. A regression test was added.*
- **Engine:** `base.py` gains `mx_pack_rows` and `mx_input_components`, and `preflight.py` reads `mx_pack_rows` when it is set. The shared resolver hands ORM rows keyed per component, so the engine reads the date-filtered dict rows instead.
- **`mexico_content.py`:** `MX_PAY_FREQUENCY_ISR_PERIOD = {}`, a value-free S28 mapping. While it is empty, every calculation blocks.
- **Labour policy (D13):** `salary_days_convention` (CALENDAR / FIXED) in the model, schema, service and view.
- **`mexico_org_router.py`:** `GET /runs/{id}/preflight`, `POST /runs/{id}/preflight/{eid}/acknowledge`, `GET /runs/{id}/status`, `POST /runs/{id}/reset`, `GET/POST /employees/{id}/hours`, `POST /hours/{id}/approve`, `POST /employees/{id}/opening-balances`, `POST /opening-balances/{id}/approve`. All sit behind the 4a guard.
- **Migration `c4f7a2d9e6b1_mx_run_m4`** (§3) plus the manifest entry.

**Frontend**
- `components/jurisdiction/mexico/run/MXRunPreflightPanel.jsx`: exceptions, WARN acknowledgement, and reset with a reason.
- `MXRunStatusBadges.jsx`: four separate badges, plus "Approval invalidated" naming the changed components.
- `MXRunCalculationTrace.jsx`: per-payslip drill-down, every figure from the snapshot.
- These are mounted in `RunDetailPanel.jsx`. `PayslipStub.jsx` gains the Mexico section: deductions from the snapshot, employer cost, and SBC shown apart from pay (MX-037).
- `MXEmployerPanels.jsx`: the salary-days convention in the labour-policy form and table.
- `payrollService.js`: the new calls.

**Docs:**
- `MEXICO_PHASE_6_PLAN.md`: D13, the reset rule, the lock ordering and the FK table.
- `MEXICO_IMPLEMENTATION_PLAN.md`: the reset rule, written into Phases 7, 8 and 10.
- `OUT_OF_SCOPE_DEFECTS.md`: **OOS-8**.
- `PRODUCTION_STATE.md`: PR #105 and #106 rows.
- `phase6-evidence/`.

## 3. Migration `c4f7a2d9e6b1` (mx_run_m4) — lock ordering, measured on PostgreSQL 17

`alembic/env.py` runs the whole upgrade in one transaction, without `transaction_per_migration`. Separate revisions would therefore not release their locks, and env.py was not changed. The revision instead uses `autocommit_block()`:

1. Seven tables, with their FKs created alongside, and the Mexico-only labour-policy column, under `SET LOCAL lock_timeout = '5s'`.
2. **The autocommit block** commits step 1, sets a session `lock_timeout = '5s'`, and then runs:
   - `ALTER TABLE payslip_items ADD COLUMN mx_calculation_snapshot JSON` as its own transaction;
   - `ALTER TABLE payroll_runs ADD COLUMN mx_approval_fingerprint JSON, ADD COLUMN mx_run_type VARCHAR(16)` as its own transaction;
   - `RESET lock_timeout`.

   Both ALTERs are nullable, with no DEFAULT and no CHECK, so neither rewrites nor scans the table.
3. Every step checks the catalog first. A deploy that fails in step 2 leaves step 1 committed, and a re-run completes it.

| Measured (`test_mexico_run_migrations.py`, printed) | Result |
|---|---|
| `payslip_items` ACCESS EXCLUSIVE held (statement start → commit) | **0.62–0.79 ms** (4 runs) |
| `payroll_runs` ACCESS EXCLUSIVE held | **0.49–0.72 ms** |
| Another connection holds ACCESS SHARE on `payroll_runs` | Upgrade gives up after **5.34–5.59 s** with `lock timeout`. During the wait, a third connection read `payslip_items` and took ROW EXCLUSIVE NOWAIT in **~7 ms**, and **no ACCESS EXCLUSIVE lock was granted** on either table. The `payslip_items` column was committed and the `payroll_runs` columns were absent; a re-run completed. |
| A held lock on `payslip_items` | Fails after ~5 s with neither shared column added. The tables exist and the re-run is guarded. |
| Existing rows | Every new column NULL; an NL payslip's snapshot byte-identical; idempotent re-run; clean downgrade. |
| Real CLI path | `alembic upgrade head` (env.py) from `b7a1c9e3d5f2` → `c4f7a2d9e6b1`; `alembic current` = head; `check_schema_drift` exit 0. |

**`payslip_items` size:** still unknown here. You asked the DB-access holder for the `reltuples` query. Size doesn't change the hold time, which is the 0.6–0.8 ms above, because the column add is metadata-only. It only matters if a long transaction holds the table, and then the 5 s timeout fails the deploy cleanly.

**ON DELETE:**

| FK | ON DELETE |
|---|---|
| Preflight exceptions → run, item, employee | CASCADE |
| IMSS branch lines / ISN liabilities → payslip item | RESTRICT |
| SBC history / variable accumulators / benefit accruals → run, employee | RESTRICT |
| `organization_id` on the ledger tables | CASCADE (org deletion is still blocked through the RESTRICT chain) |
| Approved hours → employee | CASCADE |
| Evidence documents | SET NULL |

Tests cover:
- deleting an item or run before approval works, and its exceptions cascade (PRAGMA `foreign_keys` on, in SQLite);
- after commit, the hook refuses deletion with 409;
- regenerate after the fix works for MX items.

## 4. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| `calc_inputs` stops raising `MX_ENGINE_NOT_IMPLEMENTED` | It raises **`MX_DORMANT`** before any read, pinned by `test_mexico_run_dormancy.py` and checked in the browser. It is also unreachable: no Mexican employee can be created, and no MX pack is Active. |
| Three call sites in `service.py` | Each is a new `if country == "MX"` branch that is never true. NL, SA, HK, BR and every other country are unchanged (full suite, plus the per-country and shared-snapshot suites). |
| Generation loop `except MissingComplianceConfigurationError` | Re-raises for every non-MX country and every guard code, exactly as before. Only a Mexican statutory block becomes a sentinel. |
| `_mx_before_run_transition` | APPROVED is allowed only with preflight clear and current payslips; AUTHORIZED / PAID / CLOSED are refused. No MX run exists. |
| `payment_treatment` | Holds every MX item; there are none. |
| `delete_payroll_run` / `delete_payslip` | A new check, reached only when a run has `mx_approval_fingerprint`, which no existing run has. |
| Payslip response schema | `mxCalculationSnapshot` is `null` on every existing payslip. |
| Migration `c4f7a2d9e6b1` | Seven empty tables. One nullable column on the Mexico-only labour-policy table. On the shared live tables, one nullable column on `payslip_items` and two on `payroll_runs`, each ALTER its own transaction, holding ACCESS EXCLUSIVE for under 1 ms as measured. If a lock can't be had within 5 s, the deploy step fails cleanly and is re-run; the app keeps serving the previous code. `check_schema_drift` passes. Head `b7a1c9e3d5f2` → **`c4f7a2d9e6b1`**. |
| New routes `/api/payroll/mexico/runs/…`, `/hours/…`, `/opening-balances/…` | Behind the 4a guard → 403 (pinned and browser-checked). |
| Frontend | MX panels mount only when a run has MX items. None do; the NL run screen is unchanged (browser). The labour-policy form has a new optional field (Mexico workspace only). |
| `mx_golden` | Still empty, so activation stays refused. |

Net effect: an additive schema change and no behaviour change for any existing organisation.

Suggested PR description: "Mexico Phase 6 — run integration, dormant (calc_inputs refuses MX_DORMANT), migration c4f7a2d9e6b1 additive (shared ALTERs metadata-only, own transactions, lock_timeout 5 s)."

## 5. Browser evidence (`docs/mexico/phase6-evidence/`)

Harness:
- `harness/setup_db.py` builds a scratch DB. It records the shared attendance gate's admin override on the synthetic run, because there are no attendance rows.
- `harness/patches.py` holds the SYNTHETIC S28 / ZLFN mappings and is used only by the setup and server processes.
- `harness/serve.py on|off` starts the backend.
- `harness/acceptance.py on|off` drives installed Chrome against `vite preview`.

**Flag on, 12/12:**
1. The run drawer shows the Mexico preflight with `MX_SALARY_DAYS_CONVENTION_UNSET` (`on_01b`), plus four separate badges, with Bank HELD (`on_01a`).
2. A labour-policy v2 with CALENDAR is recorded and activated through the API.
3. The UI "Recalculate payslip" clears the block, and the trace shows every section with the hand-checked synthetic figures: ISR 450.00, E&M fixed 225.00, CEAV employer 852.16, ISN 270.00 (`on_02`).
4. Draft → Review → Approved: the payroll badge shows Approved and the other three are unchanged (`on_03`).
5. Changing the ACTIVE risk premium in the scratch DB shows "Approval invalidated … riskPremium" (`on_04`).
6. Authorize is refused with `MX_RUN_NOT_SUPPORTED`.
7. The payslip view shows the Mexico section: employer cost 2,496.59 and SBC 631.23 per day, apart from pay (`on_05b`).
8. The ledgers are committed.
9. The NL run screen has no Mexico panels.
10. There were no 4xx, 5xx or console errors.

**Flag off, 8/8:**
1. The NL run screen is unchanged.
2. The Mexican run's drawer shows only the dormancy refusal: no badges, no trace.
3. The Mexico run, status and hours routes return 403.
4. A Mexican preview is refused with `MX_DORMANT`.
5. The Super Admin Mexico workspace loads.

The only 4xx responses and console errors are those expected 403s.

**Fixed during the run:**
1. `mxCalculationSnapshot` was stripped by the shared response model; it is now declared, with a test.
2. The trace's value column rendered off-screen inside the wide employee table; it now has a width cap.

## 6. Deviations and design notes

1. **Commit point.** Ledgers are committed at APPROVED, as in NL (D10), in the same transaction as the status change. The commit runs before `committedAt` is stamped, because `committedAt` is its idempotency key.
2. **Hourly rate.** No transcribed rule derives an hourly rate from the daily salary, so approved overtime blocks with `MX_HOURLY_RATE_RULE_MISSING`. Sunday premium works, using the policy rate × daily salary. Open item, S26.
3. **Pay frequency.** `mx_pay_frequency_code` → Art. 96 period is a value-free S28 mapping, empty until transcribed. A run's own period kind comes from calendar arithmetic on its dates; catorcenal, for example, is unsupported.
4. **Absence and incapacity.** Read from the shared attendance rows: absent or unpaid leave counts as absence, sick leave as incapacity. Both block (Phase 5 Q6).
5. **Run-level totals.** The shared run "Employer contribution" total shows 0.00 for MX, because Mexico's employer cost lives in `mx_result`. It is shown in the Mexico panels and the payslip section. Mapping it into the shared total is left for review: it would change the shared aggregate's meaning.
6. **Approval of hours and opening balances.** Approval must come from a different user than the recorder. These are org-admin routes; no Super Admin view exists yet.
7. **OOS-8.** The shared preview get-or-creates the org's default payroll policy (every country, pre-existing). It was logged and not changed; Mexico's own inputs are pinned read-only.

## 7. Open / prerequisites

- S28 pay-frequency mapping, S26 hourly-rate rule, ZLFN list and all Batch A/B content.
- `payslip_items` row count (your DB holder).
- Phases 7, 8 and 10 must register in `run_downstream_actions`.
- G1–G8, Q9, `MX_IDENTITY_TOKEN_KEY`, OOS-4, OOS-7 and OOS-8.
