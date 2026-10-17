# Mexico (MX) — Phase 6 Plan: Payroll run integration

Spec ZP-MX-ENG-001 v1.0 §13 (MX-036, MX-039–MX-041) · plan v1.1 §9 · `MEXICO_PHASE_5_IMPLEMENTATION_REPORT.md` §8 (the inputs Phase 6 must supply).
**Plan only — nothing is built.** Standing rules apply:
- stage only;
- zero behaviour change for other jurisdictions;
- never infer a statutory value;
- fail closed;
- nothing Active by code;
- merging to `main` deploys to production and runs Alembic (§13).

**Baseline — checked 2026-10-17:**

- **Phase 5 is in `main`.** It was committed on `nikhil` as `1575015` and merged as **PR #106** (`5775299`) on top of PR #105 (`8ae86ee`, Brazil Phases 0–2 from `venu`, whose deploy succeeded). PR #106's deploy, run 38992536267, succeeded: test ✅ · single-head ✅ · SSH deploy ✅ · drift ✅.
- **Brazil added a migration.** PR #105 brought `b7a1c9e3d5f2_brazil_statutory_foundation_phase1` (parent `8b2f6d4e1a93`). Production is therefore expected to be at **`b7a1c9e3d5f2`**, not `8b2f6d4e1a93`; check with `alembic current`. Phase 6's migration chains from whatever `main`'s head is when Phase 6 is built.
- **The merge was clean**, as a trial `git merge-tree` had predicted. Brazil touched four Phase 5 files — `engine/base.py` and the Mexico activation-gates, scaffolding and seed tests. In the tests it only added `BR` to the pinned country tuples. Before Phase 6 starts, `nikhil` must be fast-forwarded to `main`, which brings in Brazil's code and migration.
- **Line numbers are the same on the merged tree** (`main` + Phase 5) and on `nikhil`, because Brazil's `service.py` edits only extend existing tuples on their own lines.

---

## 1. Dormancy — defence in depth

Phase 6 replaces `mexico_service.calc_inputs`, which until now has always raised `MX_ENGINE_NOT_IMPLEMENTED`. Its first statements become a guard that runs before any read:

```python
def calc_inputs(db, run, employee, resolved_pack=None, as_of=None) -> dict:
    org_id = employee.organization_id
    if not mexico_dormancy.onboarding_enabled():
        raise MXBlock("MX_DORMANT", mexico_dormancy.DORMANT_MESSAGE, org_id)
    if not mexico_dormancy.is_mexico(service._resolve_org_country(db, org_id)):
        raise MXBlock("MX_ORG_NOT_MEXICAN", "…payroll jurisdiction is not Mexico", org_id)
    if run is not None and run.organization_id != org_id:
        raise MXBlock("MX_RUN_ORG_MISMATCH", …)
    if run is not None and (run.mx_run_type or "ORDINARY") != "ORDINARY":
        raise MXBlock("MX_RUN_TYPE_PHASE9", …)          # aguinaldo / PTU / finiquito → Phase 9
    …
```

This is the same predicate as the 4a router guard `require_mexico_tenant` (`mexico_org_router.py:42`). It is applied a second time here because `calc_inputs` is reached from shared code, not from the Mexico router.

### Every production path into a Mexican calculation, and why each stays closed

The engine runs `countries/mexico.calculate` only when `ctx.country == "MX"` (dispatch `engine/standard.py:219`). A context gets country MX only from an employee whose country resolves to MX.

| # | Path | Where | Closed by |
|---|---|---|---|
| 1 | Run preview | `preview_payroll_run` `service.py:19776` (ctx :20122, calc :20161) | (a) No Mexican employee exists while the flag is off: MX is in the dormant strategy map only, `employee_validation._STRATEGIES` has no MX, pinned. (b) The new `calc_inputs` guard. (c) No Active MX pack: `_resolve_effective_rate_inputs` → canonical-only (`_CANONICAL_PACK_ONLY_COUNTRIES` :1512, :1586) raises `MissingComplianceConfigurationError` before the engine. (d) Engine preflight. |
| 2 | Generate / regenerate | `_compute_payslip_values` :24933 (ctx :25190, calc :25239). Reached from `_generate_single_payslip` :25869 (← `generate_payslip_for_employee` :26308, `generate_payslips_for_run` :26451), `regenerate_employee_payslip` :26694, `_sg_dry_run_trace` :17043, `_sg_frozen_recompute` :17990, `hong_kong_service.py:4412/:4442` | (a)–(d) as above. The SG and HK callers only ever pass SG/HK employees. |
| 3 | Add one employee to a run | `add_payslip_item` :31657 (ctx :31867, calc :31909) | (a)–(d). |
| 4 | Fixed-country calculators | `preview_germany_calculation` :7457, `preview_singapore_calculation` :22614, `calculate_au_employee_schedule5_withholding` :23560, `preview_sweden_calculation` :40435, IT/SA/CH/HK service calculators | Each hard-codes or validates its own country. None can produce `country="MX"` (pinned by a test that greps for `country="MX"` construction outside Mexico modules). |
| 5 | Golden harness | `hmrc_golden_harness.py:386/:394` via `mexico_service.pack_golden_check` | `tests/fixtures/mx_golden/` is empty. It runs only at pack activation, which still fails gates 1–4. No production write. |
| 6 | Run transitions | `advance_payroll_run_status` :31462 → hook loop :31509 → `_mx_before_run_transition` | Reached only if the run has MX payslips (`_run_has_country_payslips` :31457), which needs path 2 or 3 first. Phase 6 keeps AUTHORIZED / PAID refused (§7). |
| 7 | Bank export | `_build_bank_export_rows` :32256 → `payment_treatment` :32292 | Phase 6 changes Mexico's `payment_treatment` from `{}` to **hold every MX item** ("bank settlement is Phase 10"). It is unreachable anyway, since no MX run can reach PAID. |

**Test to pin this.** With the flag off, plant a Mexican employee directly by SQL on a scratch DB, bypassing creation. Then:
- preview, generate and add-item each refuse with `MX_DORMANT`;
- with the flag on but a non-Mexican org, they refuse with `MX_ORG_NOT_MEXICAN`;
- nothing is written in any of these cases.

---

## 2. The three NL-pattern call sites

Each mirrors the NL call exactly. It is guarded by `country == "MX"` and passes a new `mexico_inputs=` kwarg to `build_context_from_employee`, which splats only into the `mx_*` fields.

| Site | NL call today | MX call (new) | Persisted |
|---|---|---|---|
| **Preview** `preview_payroll_run` :19776 | :19996-20000 `call("NL","calc_inputs", db, None, emp, None, as_of=period_end or date.today())` | `call("MX","calc_inputs", db, None, emp, None, as_of=<pay date>, period=(start,end), read_only=True)`. **The pay date only; never `date.today()` (MX-004).** If the preview has no pay date, refuse with `MX_PAY_DATE_MISSING`. | Nothing. The preview response gains `mxPreview` (the trace) for MX rows. |
| **Generate** `_compute_payslip_values` :24933 | :25115-25118 `call("NL","calc_inputs", db, run, employee, resolved_pack)` | Same signature, `as_of=run.pay_date`. The resolved pack id/version goes into `mx_pack`. | `"mx_calculation_snapshot": result.mx_result`, next to `nl_calculation_snapshot` at :25396 |
| **Add item** `add_payslip_item` :31657 | :31763-31766 (NL passes `resolved_pack=None` although `pack` is resolved at :31681) | Pass the resolved `pack`; `as_of=run.pay_date` | `mx_calculation_snapshot=calc.mx_result` next to :31947 |

Serialization: `_serialize_payslip` (NL read at :32592) maps `mxCalculationSnapshot`. `schemas.py` gains the field.

**MX-039 — preview never mutates.**
- `preview_payroll_run` has no direct writes today (its docstring at :19778 says so).
- The one indirect write risk is the org-rate seeding in `get_contribution_rates` :283 and `get_tax_slabs` :352. MX skips it because it takes the canonical-only branch at :1586 before any seeding.
- `calc_inputs(read_only=True)` only queries. The ledger writers (§4) live in a separate `commit_run` that preview never imports.
- **Test:** wrap a full MX preview in an SQLAlchemy `before_flush` / `after_cursor_execute` listener. Assert no INSERT/UPDATE/DELETE and that `session.new`, `session.dirty` and `session.deleted` are empty. Run it twice and assert identical output.

---

## 3. Where the Phase 5 inputs come from

Every input is read **as of the run's pay date or period**, never the server date. An input the repo has no source for yet blocks; it is never defaulted.

| Context field | Source | Notes / gaps |
|---|---|---|
| `mx_payroll_date` | `run.pay_date` | Required. |
| `mx_payment_period` | The profile's `mx_pay_frequency_code` mapped to an Art. 96 code. It must agree with the run's frequency, else `MX_PAY_FREQUENCY_MISMATCH`. | **D3.** |
| `mx_period` | Start/end are `run.period_start`/`period_end`. `days_paid` (ISR / subsidy, salary days) follows the employer's **salary-days convention** (D13): WEEKLY_7 = 7, DECENAL_10 = 10, DAILY = days worked; for QUINCENAL_15 / MONTHLY it is `CALENDAR` (actual days) or `FIXED` (15 / 30) per `payroll_mx_labor_policies.salary_days_convention`, and unset → BLOCK `MX_SALARY_DAYS_CONVENTION_UNSET` (never inferred). **Contribution days (IMSS / INFONAVIT) are always calendar days**, independent of the convention. `absence_days` / `incapacity_days` come from `PayrollAttendanceRecord` (absent / unpaid leave) through `_count_unpaid_leave_days` :20618, which is fed by `PayrollLeaveRequest` via `_sync_leave_to_attendance` :34261. **Segments:** split at every date where a national row starts or ends inside the period; each segment carries `pack_rows_for_golden(db, pack, seg_start)`. | Any absence or incapacity day blocks (Phase 5 Q6) until the IMSS contribution-day rules are transcribed. Incapacity has no source yet: the leave type `sick` is treated as incapacity → block. |
| `rate_map` / `slabs` | The Active national pack resolved by pay date (canonical-only) | Unchanged shared path. |
| `mx_profile` | `EmployeeStatutoryProfile` in force on the pay date (Phase 4), as a dict | |
| `mx_earnings` | The salary line `{code: "MX_SALARY", kind: ORDINARY_SALARY, amount: mx_daily_salary × days_paid}`. Allowance lines from `PayslipAllowanceItem` (`models.py:1985`, built by `_compute_allowance_components` :24996) use code `allowance:<key>`. Attendance extras use `attendance:rewards|bonus|other_compensation` (the HK keying at :25185-25189 / `_hk_attendance_extras_by_kind` :20683). | **D2.** Every code needs an ACTIVE `PayrollMxEarningClassification` (`models.py:9434`), org row first, else canonical. Otherwise it is blocked by preflight. `ctx.gross` = Σ lines + hour lines, so the Phase 5 `MX_GROSS_MISMATCH` check holds. |
| `mx_classifications` | `PayrollMxEarningClassification` in force on the pay date (ACTIVE, or SUPERSEDED inside its window) | MX-006 replay. |
| `mx_hours` | **No source exists.** The repo has no timesheet or approved-hours system (`models.py:1413`: "no attendance/timesheet system for any country"). HK "R5" is a test (`test_hong_kong_e2e.py::test_r5_…`) over HK's own `payroll_hk_work_hours` (`models.py:7201`, `hong_kong_service.record_work_hours` :223, `overtime_pay` :281). That table has no approval fields: rows count as verified when entered. `PayrollAttendanceRecord.hours` is a free string with no overtime or approval. | **D1.** Recommended: a new Mexico approved-hours table (§4), four-eyes approved with evidence. Until rows exist, `mx_hours = None` → no overtime / Sunday premium (Phase 5 Q9), and rest-day work cannot be entered. |
| `mx_variable_accumulator` | `payroll_mx_variable_accumulators` (new, §4): the prior bimester's committed variable pay and days | **D4** (bootstrapping a new tenant). |
| `mx_month_to_date` | Σ of committed MX snapshots in the same pay-date month for the employee: `isr_taxable`, `subsidy.applied`. This is the SE `_se_month_to_date_prior` :21903 / SG `_load_sg_month_to_date` :22203 pattern. | Read-only. Counts committed runs only. |
| `mx_min_wage_zone` | Derived from `mx_work_state` + `mx_work_municipality` against `MX_ZLFN_MUNICIPALITIES` content | That content is empty today → `UNRESOLVED` → blocks. |
| `mx_registration`, `mx_risk_premium` | Profile `mx_imss_registration_id` → `PayrollMxImssRegistration`, and its ACTIVE `PayrollMxRiskPremium` covering the period | |
| `mx_labor_policy` | ACTIVE `PayrollMxLaborPolicy` of the employer, in force on the pay date, `floor_check_status = PASS` | Not PASS → blocked. |
| `mx_infonavit_notices` | `PayrollMxInfonavitNotice` rows of the employee overlapping the period | |
| `mx_isn_state_pack` | The work state's ISN pack: status, id/version and rows resolved by pay date | |
| `mx_pack` | The resolved national pack: id, version, cited source codes | Trace (MX-063). |

---

## 4. Persistence

Rule (MX-039): preview writes nothing; generate writes only the payslip snapshot and preflight exceptions; **ledgers are written only at commit**.

| Object | Written at | Shape | Idempotency |
|---|---|---|---|
| `payslip_items.mx_calculation_snapshot` (JSON, nullable) | generate / regenerate / add-item | Phase 5 `mx_result`, plus `inputHash` (canonical JSON hash of every context input) and `contentHash` (hash of the rate_map / slab rows and classification ids/versions) | Regenerate overwrites, before commit only. |
| `payroll_runs.mx_approval_fingerprint` (JSON, nullable) | APPROVED | `{fingerprint, approvedBy, approvedAt, committedAt, items:[{payslipItemId, inputHash, contentHash, totals}]}` (NL `nl_approval_fingerprint` shape, `models.py:1498`) | Re-approval after a reset writes a new value. |
| `payroll_runs.mx_run_type` (String(16), nullable, **no default**) | Run creation for MX orgs | ORDINARY / AGUINALDO / PTU / FINIQUITO / CORRECTION. NULL is read as ORDINARY. Only ORDINARY is accepted in Phase 6. | — |
| `payroll_mx_preflight_exceptions` | generate (replaced on each regenerate) | id, payroll_run_id, payslip_item_id, employee_id, code, severity (BLOCK / WARN), message, acknowledged_by_id, acknowledgement_note, acknowledged_at, created_at | The run's open rows are deleted and recreated on regenerate. BLOCK rows can't be acknowledged (**D8**). |
| `payroll_mx_imss_branch_lines` | **commit** | id, payslip_item_id, branch_code, side, segment_start, base_amount, contribution_days, rate_pct, amount | UNIQUE(payslip_item_id, branch_code, side, segment_start) |
| `payroll_mx_isn_liabilities` | **commit** | id, payslip_item_id, organization_id, state_code, base_amount, rate_pct, amount, jurisdiction_pack_id, period_key | UNIQUE(payslip_item_id, state_code) |
| `payroll_mx_sbc_history` (deferred from Phase 4) | **commit** | id, employee_id, organization_id, effective_from, sbc_fixed, sbc_variable, sbc_total, factor, components (JSON), payroll_run_id, source (RUN / MOVEMENT) | UNIQUE(employee_id, effective_from, payroll_run_id) |
| `payroll_mx_variable_accumulators` (deferred) | **commit** | id, employee_id, organization_id, bimester_key (YYYY-Bn), variable_total, days, payroll_run_id | UNIQUE(employee_id, bimester_key, payroll_run_id). The value read is Σ over committed runs. |
| `payroll_mx_benefit_accruals` (deferred) | **commit** | id, employee_id, organization_id, concept (AGUINALDO / VACATION / VACATION_PREMIUM), period_key, statutory_amount, employer_amount, payroll_run_id | UNIQUE(employee_id, concept, period_key, payroll_run_id) |
| `payroll_mx_approved_hours` (**D1**, new) | Operator entry; second-person approval | id, organization_id, employee_id, week_start, ordinary_hours, overtime_hours, sundays_worked, rest_days_worked, evidence_document_id, status (DRAFT / APPROVED / SUPERSEDED), recorded_by_id, approved_by_id (≠ recorded_by), approved_at | One APPROVED row per (employee, week_start) (partial unique) |

`commit_run(db, run, actor)` is called inside the APPROVED transition (NL precedent: `_nl_before_run_transition` `netherlands_service.py:1211` → `nl_commit_run` :1190). It writes all ledger rows in the same transaction as the status change. A repeat call is a no-op because of the unique keys plus a `committedAt` check. **Reset** — `POST /mexico/runs/{id}/reset` (org admin, reason required; the run returns to **Review**) — deletes that run's ledger rows in the same transaction, clears `mx_approval_fingerprint` and `approved_by/at` (**D10**), and is audited. There is no other backward move for a run in the platform (`advance_payroll_run_status` is forward-only; SG/CH send a run back to Review only on fingerprint mismatch).

**Reset rule for later phases (approved 2026-10-17).** Reset deletes ledger rows only while **no downstream lifecycle has acted on the run**. Once any CFDI for the run is stamped (Phase 7), any authority filing / liability that includes it is submitted or paid (Phase 8), or any bank instruction for it is released (Phase 10), reset is **refused** (`MX_RESET_DOWNSTREAM_ACTED`) — corrections then go through the CFDI cancel/replace and correction-run flows, never a ledger delete. Phase 6 builds the check as `mexico_service.run_downstream_actions(db, run) -> list[str]`, empty today (no downstream objects exist); **Phases 7, 8 and 10 must each register their check there** (stamped CFDI, filed/paid authority line, released bank instruction), with a test that a reset after their action is refused. Recorded also in `MEXICO_IMPLEMENTATION_PLAN.md` §10, §11, §13.

---

## 5. Migration `mx_run_m4` on shared live tables

The rules are the same as `8b2f6d4e1a93_mx_employee_m3` (the only migration in the repo that uses `lock_timeout`; earlier NL ones such as `972ecd8c1dba` did not), with one addition: **lock ordering** (approved 2026-10-17).

**How `alembic/env.py` runs migrations.** `run_migrations_online` uses one `context.begin_transaction()` for the whole upgrade, and `transaction_per_migration` is not set (env.py:61-70). So every pending revision runs in **one** transaction, and every lock is held until the whole upgrade commits. Splitting the ALTERs into separate revisions would therefore not release their locks. Changing env.py would change how every migration on the platform runs, so it is not done. Instead the revision uses `op.get_context().autocommit_block()`, which commits the transaction so far and runs each statement inside the block as its own transaction.

Order inside the single revision `mx_run_m4` (PostgreSQL):

1. **New tables first**, in the migration's transaction, under `SET LOCAL lock_timeout = '5s'`:
   - the seven tables of §4;
   - their FKs are created with the table, so no `NOT VALID` / `VALIDATE` step is needed;
   - creating an FK takes a brief `SHARE ROW EXCLUSIVE` lock on `payslip_items` / `payroll_runs` / `payroll_employees`. It blocks writes but not reads, and is held only until the block below commits it.
   - The new Mexico column on `payroll_mx_labor_policies` (D13) goes here too: a Mexico-only table that is not live.
2. **`autocommit_block`** commits step 1 and releases those locks. Then:
   - `SET lock_timeout = '5s'` (session level; `SET LOCAL` does nothing outside a transaction);
   - `ALTER TABLE payslip_items ADD COLUMN mx_calculation_snapshot JSON`, its own transaction. The `ACCESS EXCLUSIVE` lock is held only for this metadata-only statement and released at its commit;
   - `ALTER TABLE payroll_runs ADD COLUMN mx_approval_fingerprint JSON, ADD COLUMN mx_run_type VARCHAR(16)`, its own transaction;
   - `RESET lock_timeout`.

   The lock on `payslip_items` is never held while the migration waits for `payroll_runs` or creates tables. Both columns are nullable with no DEFAULT and no CHECK, so the statements are metadata-only, with no rewrite and no validation scan.
3. **Guards.**
   - `down_revision` = `main`'s head at build time (`b7a1c9e3d5f2`, Brazil), keeping a single head.
   - Every step checks the catalog and skips what already exists. This matters because a failure in step 2 leaves step 1 committed; the deploy is simply re-run and finishes the remaining steps.
   - The downgrade drops only Mexico objects, with each ALTER again in its own transaction under `lock_timeout`.
   - SQLite (dev/test) has no `autocommit_block` need: plain `create_table`, plus `batch_alter_table` for the labour-policy column.

**Foreign keys — ON DELETE (approved 2026-10-17).**

| Table | FK | ON DELETE | Why |
|---|---|---|---|
| `payroll_mx_preflight_exceptions` | payroll_run_id, payslip_item_id, employee_id | **CASCADE** | Transient generation output; it goes with its run or item. |
| `payroll_mx_imss_branch_lines`, `payroll_mx_isn_liabilities` | payslip_item_id | **RESTRICT** | Committed ledger: never removed silently. |
| `payroll_mx_sbc_history`, `payroll_mx_variable_accumulators`, `payroll_mx_benefit_accruals` | payroll_run_id | **RESTRICT** | Same. |
| same three | employee_id | **RESTRICT** | Same. |
| all ledger tables | organization_id | CASCADE (but org deletion is blocked by the RESTRICT through `payroll_runs → payslip_items`) | An MX organisation with committed payroll can't be hard-deleted. That is correct for statutory records. |
| `payroll_mx_approved_hours` | employee_id CASCADE; evidence_document_id SET NULL | — | Hours are inputs. An approved run's fingerprint binds their ids, so removing one fails re-verification closed. |

Ledger rows exist only after commit (APPROVED). Every shared deletion path is already Draft-only: `delete_payroll_run` (`service.py:31569`) and `delete_payslip` (:31595). The Mexico hook adds a refusal for any item or run of a run whose `mx_approval_fingerprint.committedAt` is set, so the RESTRICT is a database backstop and never the first line of defence. **Tests:**
- before approval, the shared item-removal (`delete_payslip`), run deletion and `regenerate_employee_payslip` paths work for MX items, and their preflight exceptions cascade;
- after commit, the same paths are refused by the hook;
- a raw SQL delete is refused by the FK.

**`payslip_items` size.**
- The repo has no row count. The table is the platform's largest: one row per employee per run, across every country since launch, with about 15 JSON snapshot columns.
- Size does not matter for a nullable no-default `ADD COLUMN` on PostgreSQL ≥ 11, because only the catalog changes.
- What matters is **waiting for the lock**: a long-running transaction holding the table, such as bulk generation or a bank export, blocks the ALTER. Without `lock_timeout`, every later payroll query would then queue behind it.
- With 5 s the deploy step fails cleanly and is re-run.
- Read-only query for you to run before merge:
  ```sql
  SELECT reltuples::bigint AS approx_rows, pg_size_pretty(pg_total_relation_size('payslip_items'))
  FROM pg_class WHERE relname = 'payslip_items';
  ```

**Tests on throwaway PostgreSQL 17** (port 55433, the Phase 4b harness):
- the emitted statement sequence is exactly the plan above: tables, then the autocommit block with the two ALTERs last;
- **lock hold times are measured and reported**: how long each `ACCESS EXCLUSIVE` on `payslip_items` / `payroll_runs` was held (statement start to commit), and that no exclusive lock on `payslip_items` is held while `payroll_runs` is waited for;
- a held `ACCESS SHARE` on `payroll_runs` makes its ALTER fail after about 5 s. Meanwhile a third connection can still read and write `payslip_items`, proving its lock is not held. A re-run then completes;
- a held lock on `payslip_items` makes the upgrade fail after about 5 s with neither column added;
- existing rows stay NULL, and other countries' snapshots are byte-identical;
- the upgrade is idempotent, and the downgrade is clean;
- `check_schema_drift` passes.

---

## 6. Approval fingerprint binding (MX-040)

At APPROVED the hook recomputes each Mexican item's inputs from the database (not from the stored snapshot) and hashes them together. The hash covers:
- **content:** national pack id/version and every row the calculation read, i.e. the trace's `content_rows`: UMA, minimum wages, ISR tariff, subsidy, IMSS, CEAV, INFONAVIT; the ISN pack id/version and rows;
- **classifications:** id and version for every earning code used;
- **employer:** IMSS registration id/status, risk-premium id/rate/window, labour-policy id/version;
- **employee:** profile version id (identifiers, daily salary, work state/municipality, seniority), SBC components, INFONAVIT notice ids and versions, approved-hours row ids and versions, variable accumulator total and days, month-to-date figures;
- **earnings:** every earning line (code, amount);
- **bank instruction:** the employee's bank-account row id and its updated_at.

Then:
- **APPROVED:** the hook stores `{fingerprint, items}` and commits the ledgers (§4).
- **AUTHORIZED / PAID** (refused in Phase 6, §7) and any **re-read:** recompute and compare. A mismatch returns 409 `MX_APPROVAL_INVALIDATED` naming the changed component, e.g. "risk premium for registration 3 changed". The only way forward is a reset to Review and regenerate.
- **Read-time check:** the run detail shows "Approval invalidated: <component>" whenever the recomputed fingerprint differs.

**Tests:** change each bound component in turn after approval, e.g. edit a UMA row, supersede a classification, approve a new risk premium, add an INFONAVIT notice, change the work state, change the bank account. Each one invalidates the approval. An unrelated change, such as another employee's profile or an NL pack edit, does not.

---

## 7. Separate status lifecycles (MX-041)

| Lifecycle | Object | Phase 6 |
|---|---|---|
| Payroll | `payroll_runs.status` | Draft → Review → **Approved** (fingerprint + commit). **AUTHORIZED and PAID stay refused** for runs with MX items (`MX_RUN_NOT_SUPPORTED`, message updated) until CFDI (Phase 7) and bank settlement (Phase 10) exist, because a Mexican payment needs a stamped CFDI. |
| CFDI | `payroll_mx_cfdi_documents` (Phase 7) | Not created. Badge: "CFDI — not started (Phase 7)". |
| Authority | IMSS / SUA / ISR / ISN liabilities (Phase 8) | The ISN liability rows written at commit are **ledger lines, not a filing**. Badge: "Authorities — not started (Phase 8)". |
| Bank | settlement (Phase 10) | `payment_treatment` holds every MX item. Badge: "Bank — held (Phase 10)". |

Rule: no lifecycle sets or reads another's status in order to advance itself.

**Test:** across every payroll transition, assert that no CFDI, authority or bank row or field changes. Assert that the badges come from four independent sources.

---

## 8. Frontend

All components mount only when the run has MX items, using the existing `(item.country || item.countryCode) === "MX"` pattern.

| Component (new, `components/jurisdiction/mexico/run/`) | Mounted in | Shows |
|---|---|---|
| `MXRunPreflightPanel.jsx` | `RunDetailPanel.jsx` beside the SG/HK/NL preflight panels (:469-471) | BLOCK / WARN exceptions per employee with code, message and the source or gate needed. Calculate and Approve are disabled while a BLOCK exists. WARN rows can be acknowledged (**D8**). Data: `GET /mexico/runs/{id}/preflight` on the 4a-guarded org router. |
| `MXRunCalculationTrace.jsx` | The per-item trace drawer (`StatutoryTraceDrawer.jsx`, opened at `RunDetailPanel.jsx:343`) | Perceptions and their classification (gross / exempt / taxable / SBC / ISN / CFDI node); the ISR bracket; subsidy; SBC components and segments; each IMSS branch as base × days × rate; the CEAV band; INFONAVIT employer and credit; ISN; entitlements; content rows with source codes and pack version. Every amount comes from the snapshot; nothing is recomputed in the browser. |
| `MXRunStatusBadges.jsx` | The run header (`RunDetailPage.jsx` / `RunStatusTimeline.jsx`) | Four separate badges: Payroll, CFDI, Authorities, Bank (§7), plus "Approval invalidated" when relevant. |
| Payslip view, Mexico section | `PaySlips/PayslipStub.jsx`, beside `chSnapshot` :87 / `nlSnapshot` :107 | Perceptions, ISR withheld (after subsidy), IMSS employee, INFONAVIT credit, net. SBC is shown separately from pay (MX-037). The employer cost is in a collapsed section. |

**StatusPill.** The shared `StatusPill` (`components/StatusPill.jsx:17`) maps unknown statuses to "deactivated", so the badges use their own explicit style map. `StatusPill` itself is not changed (about 48 users).

---

## 9. Production effect when merged

The flag (`MX_TENANT_ONBOARDING_ENABLED`) is unset in production, so False.

| Change | Production effect |
|---|---|
| `calc_inputs` stops raising `MX_ENGINE_NOT_IMPLEMENTED` | It raises `MX_DORMANT` instead. It is also unreachable: no Mexican employee can exist, and no Active MX pack. |
| Three call sites in `service.py` | Each is a new `if country == "MX"` branch that is never true. NL, SA, HK and every other country are unchanged (their suites plus snapshot pins). |
| `_mx_before_run_transition` | Allows APPROVED for MX runs; still refuses AUTHORIZED/PAID. No MX run exists. |
| `payment_treatment` | Holds every MX item; there are none. |
| Migration `mx_run_m4` | 1 nullable column on `payslip_items`, 2 on `payroll_runs` (metadata-only, `lock_timeout` 5 s, one ALTER each); 6–7 new empty tables. On a held lock the deploy step fails cleanly and is re-run; the running app keeps the previous code. `check_schema_drift` passes. Head moves from `main`'s head (today `b7a1c9e3d5f2`) to `mx_run_m4`. |
| Serializer / schemas | `mxCalculationSnapshot` is null on every existing payslip. |
| Frontend | MX panels mount only when a run has MX items; none do. |
| New routes `/mexico/runs/...`, `/mexico/hours/...` | Behind the 4a guard → 403. |

Net effect: an additive schema change, and no behaviour change for any existing organisation.

---

## 10. Tests

- **Dormancy:** for every path in §1, flag off → refused; flag on but not a Mexican org → refused; nothing written.
- **Preview non-mutation:** the flush/SQL listener, run twice, identical output.
- **Call sites:** a synthetic MX org on a scratch DB with an Active **test-only** pack (synthetic rows, as in `test_mexico_activation_gates`), run through preview, generate, regenerate and add-item. Assert the snapshots, totals and net pay that `standard.py` computes.
- **Inputs (§3):**
  - segment split at a mid-period row change (the Jan/Feb UMA);
  - absence → block;
  - pay-frequency mismatch → block;
  - unclassified allowance key → block;
  - hours present only once approved;
  - accumulator read from committed runs only;
  - month-to-date excludes uncommitted runs.
- **Ledgers:**
  - commit writes every ledger;
  - a repeat commit is a no-op;
  - reset removes that run's rows;
  - preview and generate write no ledger rows.
- **Fingerprint:** every bound component invalidates the approval; unrelated changes don't.
- **Lifecycles:** isolation (§7); AUTHORIZED/PAID refused.
- **Migration:** PostgreSQL tests (§5).
- **Regression:** the full suite in chunks, plus the NL / SA / HK run suites.

## 11. Browser checks

1. **Flag off (production setting):** run screens unchanged for an NL org; no MX panels; Mexico routes 403; Super Admin Mexico workspace still loads.
2. **Flag on (scratch DB, synthetic Active test pack, synthetic MX employee):**
   - the run preflight panel lists the blocks;
   - after fixing them, generate gives a trace drawer with every section;
   - the four badges are shown;
   - approve stores the fingerprint;
   - editing a risk premium shows "Approval invalidated";
   - AUTHORIZED is refused with the Phase 7 message;
   - the payslip view shows the Mexico section.

   Screenshots are inspected. The synthetic values are labelled as such and never reused as golden vectors.

## 12. Order of work

1. Update `nikhil` to `main` (Phase 5 + Brazil).
2. Migration and models, with the PostgreSQL tests.
3. `calc_inputs` with the guard, plus the input builders (§3).
4. The three call sites and the serializer.
5. Preflight exceptions and route.
6. Fingerprint and `commit_run`, plus the transition hook.
7. `payment_treatment` hold.
8. Approved-hours table and four-eyes routes (if D1).
9. Frontend.
10. Full suite, lint/build, browser checks, report, stage, stop.

---

## 13. Decisions (approved 2026-10-17: D1–D12 as recommended, D1 = add the approved-hours table, D4 = option (a); D13 added)

| # | Question | Recommendation |
|---|---|---|
| D1 | **Approved hours.** The repo has no approval-of-hours source, and HK's work-hours table has no approval fields. Add `payroll_mx_approved_hours` (weekly, evidence, recorded-by ≠ approved-by), or ship Phase 6 with no hours, so overtime and Sunday premium can't be paid yet? | Add the table in `mx_run_m4`. Without it, Q9 (overtime only from approved hours) means overtime can never be paid. |
| D2 | **Earning lines.** Salary = `mx_daily_salary × days_paid`. Allowances become `allowance:<key>` and attendance extras `attendance:<kind>`, each needing an MX classification. This ignores the shared monthly `basic` for MX. | Yes. Mexican pay is daily-salary based, and the codes reuse the HK keying. |
| D3 | **Payment period.** The profile's `mx_pay_frequency_code` must match the run frequency; a mismatch blocks rather than picking one. | Yes. |
| D4 | **Variable accumulator for a tenant's first bimester.** There's no history. Options: (a) block employees with `mx_salary_type` VARIABLE/MIXED until an evidenced, four-eyes opening balance is entered; (b) treat as zero. | (a). FIXED salary type gets {0, 0}. Zero for a variable earner would understate SBC. |
| D5 | **`payslip_items` size.** Please run the read-only query in §5 on production. The migration is metadata-only either way; the number tells us how long a held lock could matter. | — |
| D6 | **Run types.** Phase 6 accepts ORDINARY only; aguinaldo, PTU, finiquito and correction runs are refused until Phase 9. | Yes. |
| D7 | **AUTHORIZED / PAID.** Stay refused for MX runs until CFDI (Phase 7) and bank settlement (Phase 10). | Yes. A Mexican payment needs a stamped CFDI. |
| D8 | **Preflight acknowledgement.** BLOCK exceptions can never be acknowledged or overridden; only WARN can, with a note. | Yes. |
| D9 | **Fingerprint storage.** A JSON column on `payroll_runs` (NL shape), not the audit trail (SG/CH). | Yes. Simplest to re-verify. |
| D10 | **Commit point.** Ledgers are written at APPROVED (NL precedent); a reset to Review deletes that run's ledger rows in the same transaction. Alternative: a separate "Commit" step after approval. | APPROVED with reversible reset. The statuses stay unchanged, and AUTHORIZED is refused anyway in Phase 6. |
| D11 | **Bank hold.** `payment_treatment` holds every MX item until Phase 10. | Yes. |
| D13 | **Salary-days convention.** For QUINCENAL_15 / MONTHLY periods, salary days are calendar days or a fixed 15 / 30 — an employer / contract convention, not inferred. A new `salary_days_convention` (CALENDAR / FIXED) on the employer labour policy (Phase 3 table, Mexico-only column in `mx_run_m4`, set in the labour-policy panel); unset → BLOCK. IMSS / INFONAVIT contribution days stay calendar days. | Approved. |
| D12 | **Baseline.** Phase 5 is merged (PR #106). Before Phase 6, update `nikhil` to `main` (`git pull origin main` on `nikhil`, a fast-forward) so Phase 6 is built on Brazil's head, and confirm production's `alembic current` (expected `b7a1c9e3d5f2`). | Yes — you run the pull (stage-only rule); I verify. |
