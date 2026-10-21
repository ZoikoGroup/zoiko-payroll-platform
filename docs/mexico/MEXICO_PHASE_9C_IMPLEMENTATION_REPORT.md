# Mexico (MX) — Phase 9c Implementation Report: Termination and finiquito

Spec ZP-MX-ENG-001 v1.0 §17 MX-057 / MX-058 · plan `MEXICO_PHASE_9_PLAN.md` (approved 2026-10-19; this is 9c, built under B6, D5 and D6).

**Base.** `nikhil` = `5ff6d17`: the merge of `origin/rugvedh` (ZP-PRIV, PR #113) into `nikhil`. This branch also contains `main` up to PR #114.

**Alembic.**
- Before: a single head, Rugvedh's merge revision `c3e5a7b9d1f4` (211 revisions).
- Now: a single head, **`b4d8f2c6a9e3`** (212 revisions).

**Git.** Committed on `nikhil`, **not pushed** (the user's instruction, 2026-10-21).

**The constraint (unchanged).** No Phase 9 source is saved. Every rule here is a content seam that is **empty**, so in production:
- no termination can be recorded (`MX_TERMINATION_RULE_MISSING`);
- no finiquito can be calculated (`MX_FINIQUITO_RULE_MISSING`).

The computation is proved with SYNTHETIC rules in tests and in the browser.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite (5 chunks, 344 files, scratch SQLite) | **6,988 passed, 10 failed, 87 skipped, 2 xfailed.** No Mexico test failed; the 10 are explained in §6 (1 already fixed; 4 local-only; 5 Brazil / ZP-PRIV). |
| Phase 9c tests | `test_mexico_termination.py` (13) and `test_mexico_termination_migrations.py` (6, of which 4 run on PostgreSQL). All pass. |
| Phase 9c tests on PostgreSQL 17 | 6/6, three runs: real CLI path, current = head, schema drift clean. |
| Tests updated for the intended change | Three tests: the Phase 8 BAJA test now requires an approved termination (D6); FINIQUITO is no longer "refused"; the migration tables list includes the new table. |
| Browser | **off 9/9**, **on 5/5** (flag on, rules empty: the production reality once Mexico opens) and **rules 11/11** (SYNTHETIC rules). No 5xx and no page errors. The only 4xx in rules mode is the deliberate four-eyes refusal. Screenshots inspected. |
| ESLint / `check:undefined` / `vite build` / `npm test` | 0 errors in new or changed files; 555 files clean; the build passes; 87/87 privacy UI checks and 12/12 attendance checks pass. |

## 2. What was built

**Content seams (`mexico_content.py`, both empty).**
- `MX_TERMINATION_REASONS` — the reason catalog. Each entry is a rule object with its own source, label and the separation components the reason triggers (indemnity, seniority premium, … — LFT Arts. 47–53, 162, S26).
- `MX_FINIQUITO_RULE` — the vacation days still owed at termination (LFT Arts. 76–81) and the withholding of a finiquito paid on its own (S24 / S25).

**Engine (`engine/jurisdictions/mexico/termination.py`).** It fixes only the interface and validates what a rule returns:
- negative amounts are refused;
- days for a service year that is not in the ledger are refused;
- a negative withholding is refused.

`special_pay` now admits the concepts a FINIQUITO run may carry: aguinaldo, `VACATION_PAYOUT`, vacation premium and separation. The orchestrator withholds a FINIQUITO run with the finiquito rule (per-concept taxable amounts), never the ordinary tariff (MX-009). Like aguinaldo, it has no IMSS / CEAV / INFONAVIT and no subsidy.

**Migration `b4d8f2c6a9e3` (mx_terminations_m9)** adds **one new table**, `payroll_mx_terminations`, and no shared column.
- **One live termination per employee:** a partial unique index on `status <> 'CANCELLED'`.
- **Row-level security:** the table gets the ZP-PRIV policy that `d7f9b1c3e5a6` derives for it (a worker table, strategy "org"), on **this table only**. Re-running `apply_rls()` would take an exclusive lock on every tenant and worker table. Calling `classify()` held the FK locks for about 4 s, so the predicate is fixed and the PostgreSQL test proves `classify()` agrees.

**`mexico_termination_service.py`**
- **Record:**
  - date (the last day employed), a catalog reason, an evidence reference and a note;
  - an unknown reason → `MX_TERMINATION_REASON_UNKNOWN`;
  - no evidence → refused;
  - a second live termination → refused.
- **Approve:**
  - by another person (`MX_FOUR_EYES_REQUIRED`);
  - sets the employee's date of leaving (keeping the previous value);
  - generates the IMSS **BAJA**, and returns any committed ordinary periods that run past the termination (a correction run fixes those).
- **Cancel:**
  - needs a reason, and only before a finiquito run exists;
  - an approved termination's BAJA is withdrawn only if it never left Zoiko (otherwise `MX_BAJA_ALREADY_EXPORTED`, and nothing changes);
  - the previous date of leaving is restored.
- **FINIQUITO run:**
  - one per termination, period = the termination date, paid on or after it;
  - atomic: a failed calculation leaves nothing behind.
- **Finiquito lines:**
  - proportional aguinaldo of the termination year (the 9b rule; skipped when that year's aguinaldo was already committed);
  - the vacation still owed (FiniquitoRule, from the 9b ledger) paid out with the policy premium;
  - the reason's separation components.

  Every missing rule is reported at once.
- **Commit:** writes PAID_OUT vacation records per service year (linked to the run and payslip) and marks the termination **COMMITTED**. **Reset** removes them and sets it back to APPROVED. The 9b reset now leaves PAID_OUT rows to this module.

**The ordinary run (`mexico_run_service`)**
- The final period pays to the termination date: calendar days, and IMSS contribution days end there.
- A fixed-days convention blocks (`MX_SALARY_DAYS_PARTIAL_PERIOD`), because no proration of fixed days is transcribed.
- A period after the termination raises `MX_EMPLOYEE_TERMINATED`, and the shared selection (`service.generate_payslips_for_run`, MX-only hook) drops the employee.
- A FINIQUITO run selects exactly its termination's employee.

**IMSS (`mexico_imss_service`, D6).** The BAJA source is now an **approved termination only**: `date_of_leaving` alone no longer generates one. The source kind is `TERMINATION`. The withdrawal path was split so that a cancellation is all-or-nothing.

**Routes** (behind the Phase 4a guard):
- `GET /termination-reasons`;
- `GET` / `POST /employees/{id}/terminations`;
- `POST /terminations/{id}/approve`, `/cancel` and `/finiquito-run`.

All 6 are in the ZP-PRIV route registry (writes: org_admin; reads: org_admin / payroll_admin).

**Frontend.** `MXTerminationPanel` sits on the Mexican employee's statutory panel. It shows:
- the catalog block, or a form whose reason list holds only catalog codes;
- the records, with the BAJA movement and the finiquito run;
- approve / cancel / open finiquito run.

## 3. ZP-PRIV integration fixes (with the merge of PR #113)

Rugvedh's default-deny policy check now runs before Mexico's guard. Changes made for that:
- **Super Admin's Mexico employer readiness** no longer reads employee rows. The "employees with blocking exceptions" line is not evaluated for platform users, so it is never PASS and the employer is never live-eligible in that view; the organisation's own view still evaluates it.
- **The Super Admin Mexico organisation picker** no longer consults employees (a Mexican employee needs a Mexican employer).
- **Two Mexico employee queries** use `organization_scoped(...)`.
- **Tests updated:**
  - dormancy: payroll admins on org-admin routes are refused by the policy, and a non-existent employee gets a 404;
  - Super Admin employee routes are retired (403);
  - `no-store, private`;
  - the 10 MB upload guard is bounded by the number of middleware layers.
- **Rugvedh's identifier scan:** synthetic PEM markers carry `privacy-scan: allow`, and a checksum-invalid IBAN replaced a valid one.
- **`drift_pending_filter`** (PR #114) now understands `batch_alter_table(...)` columns and counts only `upgrade()`.
- **Route registry** regenerated. The user's uncommitted `/health/version` and `/health/ready` routes are left out, because they are not part of the commit.

## 4. Migration `b4d8f2c6a9e3` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payroll_runs` / `payroll_employees` / `users` / `organizations` | **55–86 ms** over three runs (55.33, 59.22 and 86.49 ms). |
| In flight | Reads continue; a writer's `ROW EXCLUSIVE NOWAIT` is refused; no existing table is locked exclusively. |
| A writer holding `payroll_runs` | Gives up after **5.12–5.23 s** with nothing created. |
| Row-level security | ENABLE + FORCE plus the `zoiko_rls` policy on the new table, matching `classify()`. |
| CLI path | `alembic upgrade head`, current = head, schema drift clean. |

## 5. What this does in production when merged

- `MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.
- Production's database is at Rugvedh's `e1a3c5e7f9b2`, so `alembic upgrade head` runs `a6d2f9c4b8e1` → `c3e5a7b9d1f4` → `b4d8f2c6a9e3`.
- Merging `nikhil` also ships ZP-PRIV, so it needs Rugvedh's agreement.

| Change | Production effect |
|---|---|
| Migration `b4d8f2c6a9e3` | One new, empty table with its RLS policy. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s with nothing created if a writer holds a table. |
| Routes | **Unreachable.** All 6 routes are refused (verified in the browser with the flag off). |
| Engine and run changes | MX-only. Without an approved termination, the ordinary path is unchanged. No termination can exist (catalog empty). |
| BAJA source (D6) | Switches from `date_of_leaving` to approved terminations, MX only. There are no MX employees. |
| `generate_payslips_for_run` hook | Runs only for a FINIQUITO run or when a Mexican employee is selected. |
| Screens | The termination panel shows only the dormancy refusal. NL is unchanged in all three modes. |

**Net effect:** one additive table and no behaviour change for any jurisdiction.

## 6. Full suite and findings

Five chunks (344 files) on scratch SQLite, run sequentially on the finished tree: **6,988 passed, 10 failed, 87 skipped, 2 xfailed**. **No Mexico test failed.** The 10 failures:

| Failures | Test(s) | Cause | Owner |
|---|---|---|---|
| 1 | `test_alembic_migration_manifest` (registered migration edited) | `b4d8f2c6a9e3` was edited after its hash was registered (the RLS change in §2); it has never been applied anywhere. The manifest was regenerated and the test re-run: 10/10. | Fixed |
| 3 | `tests/privacy/test_route_registry.py` (registered / fresh / public routes) | The user's **uncommitted** `/health/version` and `/health/ready` routes in `backend/app/main.py` are in the local app but not in the committed registry. A fresh generation without them equals the committed registry (1,125 entries). Re-generate when that `main.py` change is committed. | Local only |
| 1 | `tests/privacy/test_data_layer.py` (raw-query ratchet 123 / 121) | Two raw `query(PayrollEmployee)` sites in `brazil_router.py` (Super Admin Brazil organisation picker and employee list), from `main`'s Brazil Phase 2 in Rugvedh's merge. The three Mexico sites were converted (§3). | Brazil / Rugvedh |
| 1 | `test_brazil_router.py::test_org_scoping_is_explicit` | Expects 422 from the Super Admin Brazil employee list; ZP-PRIV retires that route for platform principals (403), as for Mexico (§3). | Brazil |
| 1 | `test_hong_kong_configuration.py` | Reads `docs/HONG_KONG_RELEASE_EVIDENCE/…`, the untracked local HK owner pack (the OOS-4 kind). Fails on its own as well. | Local only |
| 3 | `test_outbound_delivery_guard`, `test_payroll_email_templates`, `test_payroll_email_templates_batch2` | Order-dependent: all pass when run on their own (169 passed with HK config). These tests were changed by the ZP-PRIV merge. | Rugvedh |

Also run: the ZP-PRIV privacy suite on SQLite within the full run; `scripts.scan_test_data` (0 new findings); Phase 9c PostgreSQL tests 6/6 three times. Rugvedh's PostgreSQL privacy suite (`ZP_TEST_POSTGRES_URL`) was started and interrupted by a session restart; it is not yet re-run.

## 7. Deviations and findings

1. **The final ordinary period pays to the termination date** (calendar days; contribution days end there), and a fixed-days convention blocks. The acknowledged design said "an ordinary payslip with a mid-period termination blocks". That would have left the salary owed for the final days payable nowhere, so this is the smaller, fail-closed alternative. To confirm with S26 / S10.
2. **Terminations have no Super Admin view.** They are worker-level data and, under ZP-PRIV, a platform principal never reads worker rows. Plan §5's "Super Admin read-only views" does not apply to 9c.
3. **The vacation ledger's balance after a finiquito** still shows the current service year's policy days less what was paid out (the browser shows 16 − 4.91 = 11.09). The days owed at termination come from the FiniquitoRule (prorated); the rest is not owed. This is display only, and a later phase could mark the year closed.
4. **Termination status names:** DRAFT / APPROVED / COMMITTED / CANCELLED. The plan's PAID belongs to Phase 10 (bank), as for every run.

## 8. Open / next

- **Sources:** S26 (reason catalog, components, vacation owed), S24 / S25 (finiquito withholding), S28 (the CFDI separation node) for every Phase 9c rule.
- **9d** (PTU), then **9e** (annual ISR adjustment).
- **Integration (not Mexico):**
  - two Brazil Super Admin employee queries keep Rugvedh's raw-query ratchet at 123/121;
  - the Brazil Super Admin employee test expects 422 where ZP-PRIV now answers 403.

  Both belong to the Brazil owner or Rugvedh.
