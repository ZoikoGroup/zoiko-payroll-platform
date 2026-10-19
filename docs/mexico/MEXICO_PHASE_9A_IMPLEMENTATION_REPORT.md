# Mexico (MX) — Phase 9a Implementation Report: Correction runs

Spec ZP-MX-ENG-001 v1.0 MX-040 / MX-010 (never edit a committed or fiscal record) · plan `MEXICO_PHASE_9_PLAN.md` (approved 2026-10-19 as recommended: D1 sub-phases 9a → 9e; this is 9a, built under D10).

**Base.** `nikhil` = `8ee13dd`, the same tree as `origin/main` `422d4d2` (PR #110, Phase 8; deploy `39214061815` green, so production should be at `e3b9c2d7f4a1`).

**Alembic.** Before: a single head, `e3b9c2d7f4a1` (203 revisions). Now: a single head, **`f5c1a8d3e9b2`** (204 revisions).

The work is **staged on `nikhil`**. Nothing is committed, pushed or merged.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite, 5 chunks (326 files) on scratch SQLite, after every change in this report | **6,724 passed, 1 failed, 66 skipped, 2 xfailed** (6,793 tests). The failure is **OOS-4**: the HK test that reads the untracked local HK owner pack. Not code, not Mexico. |
| Phase 9a tests | `test_mexico_corrections.py` (14) and `test_mexico_corrections_migrations.py` (6, of which 4 run on PostgreSQL). All pass. All Mexico test files: 672 passed earlier this phase (before the last test was added; the full suite includes it). `test_mexico_dormancy.py` lists the 3 new routes: 403 with the flag off. |
| Migration on **PostgreSQL 17** | 4/4 PG tests (real `alembic upgrade head`, `alembic current` = head, `check_schema_drift`). The Phase 8 PG tests were re-run alongside; 12/12. |
| Browser, flag **off** | **6/6** (`phase9a-evidence/RESULTS-off.md`). |
| Browser, flag **on** | **11/11** (`phase9a-evidence/RESULTS-on.md`), with no 4xx / 5xx and no console errors. Screenshots inspected. |
| ESLint / `check:undefined` / `vite build` | 0 errors in the new panel; `RunDetailPanel.jsx` still has its 1 error from before this phase. 521 files clean. The build passes. |

## 2. What was built

**Migration `f5c1a8d3e9b2` (mx_corrections_m7)** adds **one new table**, `payroll_mx_run_corrections`, and no shared column (`payroll_runs.mx_run_type` already exists). It has a partial unique index: one live correction per original payslip. The run and corrected-payslip FKs are `SET NULL`, so a voided draft keeps its record after its run is deleted. The migration is guarded, runs under `lock_timeout` 5 s, and its downgrade drops only the table.

**`mexico_correction_service.py`**
- **Opening a correction.**
  - Requires a **committed** run (ordinary or correction), payslips of that run, a reason, and no live correction on those payslips (`MX_CORRECTION_ALREADY_OPEN`).
  - Creates a `CORRECTION` run with the **same period and pay date** and recalculates it with the current inputs.
  - It is atomic: if the recalculation fails, the run and its records are removed (a defect found by the browser check, §5).
- **Commit** (inside the APPROVED transition, `on_commit`):
  - each correction becomes COMMITTED;
  - its deltas (corrected − original: gross, ISR taxable / withheld, IMSS employee / employer and per branch, INFONAVIT, ISN, net) are recorded.
- **Ledgers** (`mexico_run_service.commit_run`):
  - for a CORRECTION run, **deltas** go to the aggregate ledgers (ISN liabilities, variable accumulators, benefit accruals);
  - the **full corrected rows** go to the per-payslip traces (IMSS lines, SBC history with `source = CORRECTION`);
  - the original's rows are never touched (tested by comparing them byte-for-byte).
- **Month-to-date (subsidy, MX-013):**
  - a committed correction adds only its delta, and only to runs committed **after** it (or not yet committed);
  - a correction run's own calculation leaves out the payslips it replaces and their earlier chain.

  So **a correction never changes an already committed run**: no approval drift, the same principle as the month-to-date ordering fix shipped with Phase 7.
- **Chains:** a later correction targets the corrected payslip; `replaced_chain` walks back through committed corrections.
- **Reset:**
  - a run with a live correction on any of its payslips refuses reset (a new `run_downstream_actions` reason);
  - a committed correction run resets like any run, and its corrections become DRAFT again;
  - a draft correction is **voided**: the records are kept (VOIDED, reason, actor) and the uncommitted run is deleted.
- **Shared delete guard:** `service.delete_payroll_run` refuses a Mexican correction run directly (MX-only branch), so it goes through void.

**Cross-phase**
- **Phase 7 CFDI:** for a CORRECTION run, the corrected payslip's document **replaces** the original's STAMPED one (substitution link plus a `REPLACEMENT_LINKED` event). An untransmitted original is VOIDED (`VOIDED_BY_CORRECTION`). One in flight refuses (`MX_CFDI_ORIGINAL_IN_FLIGHT`).
- **Phase 8 authorities:** a correction payslip accrues its **deltas**, possibly negative. They go into a complementary liability when the period was already filed. Its SBC rows yield a MODIFICACION movement linked to the correction run.

**Run guard:** `CORRECTION` is admitted (`BUILT_RUN_TYPES`). AGUINALDO / PTU / FINIQUITO are still refused with `MX_RUN_TYPE_PHASE9` until 9b–9d (tested).

**Routes** (behind the Phase 4a guard):
- `GET /runs/{id}/corrections`;
- `POST /runs/{id}/corrections` (`itemIds`, `reason`);
- `POST /corrections/{run_id}/void` (`reason`).

**Frontend:** `MXCorrectionsPanel` in the run detail's Mexico block.
- On a committed run: the corrections of it, and a picker (payslips + reason) to open a correction run.
- On a correction run: what it corrects, the posted differences, "Void" while uncommitted, and, once committed, corrections of the correction (the chain).
- With the flag off it renders nothing (403).

## 3. Migration `f5c1a8d3e9b2` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payslip_items` / `payroll_runs` / `payroll_employees`, from the first FK-creating statement to commit | **69–101 ms** over three runs (100.85, 75.31 and 68.68 ms). |
| In flight | `payslip_items` stays readable; a writer's `ROW EXCLUSIVE NOWAIT` is refused, so writes wait about 0.1 s. |
| A writer holding `payslip_items` | Gives up after **5.09–5.11 s** with **nothing created**. |
| CLI path | `alembic upgrade head`, current = head, schema drift clean. |

## 4. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `f5c1a8d3e9b2` | **One new, empty table.** No shared column. The head moves `e3b9c2d7f4a1` → `f5c1a8d3e9b2`. About 0.1 s of SHARE ROW EXCLUSIVE on `payroll_runs` / `payslip_items` / `payroll_employees` (reads continue, writes wait); fails fast after about 5 s with nothing created if a writer holds a table. |
| Correction service / routes | **Unreachable.** The 3 routes return 403 (verified in the browser with the flag off), and no Mexican run can be committed in production. |
| `mexico_run_service` changes | MX-only and dormant (`calc_inputs` refuses `MX_DORMANT`). For an ordinary run, month-to-date and commit behave exactly as before; only CORRECTION runs take the new paths. |
| `run_downstream_actions` | Also queries the new empty table and returns `[]`, so reset is unchanged. |
| `service.delete_payroll_run` | A new MX-only branch for runs whose `mx_run_type` is CORRECTION. There are none, so nothing changes for any country. |
| Phase 7 / Phase 8 hooks | Run only for CORRECTION runs; none exist. |
| Run screen | The corrections panel renders nothing for a refused (403) organisation; no other country's screen changes. |

**Net effect:** one additive table and no behaviour change for any jurisdiction.

## 5. Deviations and findings

1. **Correction creation was not atomic** (found by the browser check). The run and its draft records were committed before the recalculation, so a calculation error left a half-made correction behind. It now removes both and re-raises. Test: `test_a_failed_recalculation_leaves_no_half_made_correction`.
2. **Two UI gaps** were found in the browser screenshots. After "Void" the panel reloaded the deleted run and got a 404; it now shows "Correction voided — … Close this run". A committed correction run did not show corrections of itself or offer to correct it again; the chain is now visible and correctable.
3. **The harness needed a SQLite stand-in for `pg_advisory_xact_lock`** (the run-code generator's PostgreSQL lock). This is harness-only (`phase9a-evidence/harness/patches.py`); production is PostgreSQL. The tests already did the same on their own connection.
4. **Month-to-date semantics for corrections are an engineering rule, not a transcribed one.** A correction's delta counts only for runs committed after it, so committed approvals never change. Whether SAT expects the subsidy of later payments in the month to be re-tested against corrected earlier payments is a legal question for S3 / S24, recorded as open.
5. **A negative complementary liability** (a correction that lowers pay after the period was filed) accrues correctly, but `file_liability` refuses amounts ≤ 0 ("nothing to file"). How an overpayment is credited (compensation) is a legal / SAT question (S24), left open.
6. **Correction runs reuse the original period and pay date** (D10), so the CFDI replacement carries the same period. The legal form of re-paid differences ("diferencias" paid later) is not asserted.

## 6. Open / next

- **9b** (aguinaldo + vacation) next, per D1. Phase 9 blocks X1–X8 are unchanged (no Phase 9 source saved).
- **Legal questions from §5.4 / §5.5** (S3 / S24).
- **Carried over:** Phase 8 X1–X7, Phase 7 D10–D12, G1–G8, Q9, OOS-4.
