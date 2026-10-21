# Mexico (MX) — Phase 9e Implementation Report: Annual ISR adjustment

Spec ZP-MX-ENG-001 v1.0 §4 MX-010 · plan `MEXICO_PHASE_9E_PLAN.md` (approved by the user on 2026-10-21, in advance, as recommended, D1–D10).

**Base.** `main` = `46d26fa` (PR #116). Production is at `c6e1a9d4f2b7`: deploy `39568307882` was green. `nikhil` = `61826a4` (the production-state note).

**Alembic.**
- Before: a single head, `c6e1a9d4f2b7` (213 revisions).
- Now: a single head, **`e7a2c4f9b1d6`** (214 revisions).

**Git.** Committed on `nikhil`, **not pushed**.

**The constraint.** Nothing from S24 is saved, so in production:
- nothing is computed (`MX_ANNUAL_ADJUSTMENT_RULE_MISSING`);
- no operator exclusion is recorded (`MX_ANNUAL_ADJUSTMENT_EXCLUSION_RULE_MISSING`).

The mechanics are proved with SYNTHETIC rules.

With 9e, **every Phase 9 run type and module is built** (9a–9e).

## 1. Result

| Check | Result |
|---|---|
| Full backend suite (5 chunks, 349 files) | **7,036 passed, 5 failed, 96 skipped, 2 xfailed.** No Mexico failure: 1 fixed, 4 local-only (§6). |
| Phase 9e tests | `test_mexico_annual_adjustment.py` (10) and `test_mexico_annual_adjustment_migrations.py` (6, of which 4 run on PostgreSQL). All pass. |
| Production upgrade path on PostgreSQL 17 | `test_privacy_mexico_merge_migration.py` 2/2: from `e1a3c5e7f9b2`, with a live reader on `users`, through to `e7a2c4f9b1d6`. Every new table is protected and there is no drift. |
| Tests updated for the intended change | Dormancy (8 new routes), head pins, migration tables, the pending-objects check. |
| Migration on PostgreSQL 17 | 6/6, three runs. |
| Browser | **off 7/7, on 3/3, rules 9/9** (§6). |
| ESLint / `check:undefined` / `vite build` | 0 errors in new or changed files; 559 files clean; the build passes. |

## 2. What was built

**Content seams (empty).**
- `MX_ANNUAL_ADJUSTMENT_RULE`: `eligibility`, `annual_isr`, `apply_in_run`.
- `MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS`: the operator exclusion catalog.

**Engine (`engine/jurisdictions/mexico/annual_adjustment.py`).**
- An operator exclusion always excludes, with its reason.
- A rule exclusion needs a reason, and the annual ISR must be ≥ 0.
- **Difference** = annual ISR − ISR withheld (withholding is already net of the subsidy applied each period; how the subsidy enters the annual figure is the rule's decision).
- `apply_in_run` must keep withholding ≥ 0 and `(withheld − period) + carry_forward == difference`. Otherwise it refuses with `MX_ANNUAL_ADJUSTMENT_RULE_INVALID`.

The ordinary orchestrator applies an attached approved adjustment **after** the period's own withholding, as a separate `annual_adjustment` section of the result.

**Migration `e7a2c4f9b1d6` (mx_annual_adjustment_m11).**
- **One new table,** `payroll_mx_annual_isr_adjustments` (unique per employer, year and worker). No shared column.
- **RLS:** its ZP-PRIV policy is on this table only, with a fixed worker "org" predicate. The lesson from deploy `39561229230`: never re-run `apply_rls()` over existing tables.

**`mexico_annual_service.py`**
- **Compute:**
  - per legal employer and **ended** fiscal year;
  - from **committed** payslips paid in the year (all run types, labelled; superseded originals left out);
  - an earlier year's adjustment applied this year is taken out of this year's withholding;
  - re-computable until approved; approved operator exclusions survive a re-compute;
  - each row keeps its inputs, the rule source and a fingerprint.
- **Exclusions:** a catalog reason + evidence, approved by another person. A pending one blocks approval.
- **Approve:** by someone other than the computer. Refused if any input changed since computing (`MX_ANNUAL_ADJUSTMENT_STALE`). Rule-excluded or operator-excluded rows become WAIVED.
- **Apply:**
  - assigned to an **open, later ORDINARY** run of the organisation (a committed run or one paid within the year is refused);
  - generating the run attaches each worker's difference to their payslip;
  - commit → APPLIED, linked to the payslip, with the change and any carry-forward; reset → APPROVED.

**Routes (8, behind the Phase 4a guard, in the ZP-PRIV registry).**
- Exclusion catalog.
- List.
- Compute.
- Approve.
- Apply.
- Exclusion record / approve.
- The employee's adjustments.

**Frontend.**
- `MXAnnualAdjustmentPanel` in the Compliance Centre.
- `MXAnnualAdjustmentView` on the employee screen.
- A new **"Annual ISR adjustment {year}"** section in the payslip trace (`MXRunCalculationTrace`).

## 3. Migration `e7a2c4f9b1d6` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE (FKs to `payroll_runs` / `payroll_employees` / `payslip_items` / `users` / `organizations` / employer profiles) | **59–70 ms** over three runs (59.09, 70.25 and 63.60 ms). |
| In flight | Reads continue; a writer waits; no existing table is locked exclusively. |
| A writer holding `payroll_runs` | Gives up after **5.11–5.17 s** with nothing created. |
| RLS | ENABLE + FORCE plus `zoiko_rls` on the new table; `classify()` agrees. |
| CLI path and drift | Clean. |

## 4. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `e7a2c4f9b1d6` | One new, empty table with its RLS policy. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s. |
| Routes | Refused while Mexico is dormant. |
| Engine | The ordinary path changes only when an approved adjustment is attached, which cannot happen (empty content, dormant). |
| Screens | Dormancy refusal; the new trace section appears only on a payslip that carries an adjustment. |

**Net:** additive, and no behaviour change for any jurisdiction.

## 5. Deviations and findings

1. **The plan was approved before it was written** (the user's instruction). The decisions are the recommended ones and remain open to change.
2. **The carry-forward is recorded but not applied** in a further run (out of scope, plan §2). An adjustment with a carry-forward is APPLIED with the remainder shown.
3. **"Ended fiscal year"** uses the server date (`_today()`, set to 2027-03-01 in tests and the harness), as in 9d.

## 6. Full suite and browser

**Full backend suite** (5 chunks, 349 files, scratch SQLite, sequential, on the finished tree): **7,036 passed, 5 failed, 96 skipped, 2 xfailed.**

| Failures | Test(s) | Cause |
|---|---|---|
| 1 | `test_communications_dispatch::test_deactivate_organization_response_precedes_email_send` | Timing: with ZP-PRIV's middleware layers, a background task can start before the final body chunk reaches the test's outer recorder. The test now records the response **start** (status and headers). Passes alone and after the polluting module. **Fixed.** |
| 3 | `tests/privacy/test_route_registry.py` | The user's uncommitted `/health/*` routes in `main.py`. **Local only.** |
| 1 | `test_hong_kong_configuration.py` | The untracked local HK owner pack. **Local only.** |

**Found by an earlier full run, and fixed before this one: a route-registry name collision.** The ZP-PRIV call graph matches calls by simple name. A helper called `_row` in `mexico_annual_service` (which queries the new worker table) was matched from `Content._field`'s `_row(...)`, which sits on the login → audit → security-event path. Regenerating the registry therefore re-classified `/api/auth/login`, logout and MFA as worker routes: 41 failures, and it **would have denied login in production**. The helpers were renamed (`_adjustment_row`, `_employer_year_rows`). The regenerated registry now changes only Mexico payroll routes (8 new routes, plus scan-list additions on routes already classed "worker").

**Browser** (installed Chrome, vite preview of this build, scratch SQLite):
- **off 7/7:** all routes refused; dormancy refusal on the panel; NL unchanged.
- **on 3/3:** computing blocks with `MX_ANNUAL_ADJUSTMENT_RULE_MISSING` and nothing is written.
- **rules 9/9:**
  - computed for 2 workers from committed runs;
  - four-eyes on approval;
  - assigned to the open January 2027 run;
  - the January payslip shows **"Annual ISR adjustment 2026"**: difference 4,500.00 = 30% × 18,000 − 900, applied on top of the period's 450.00 → 4,950.00 withheld, no carry-forward;
  - commit → APPLIED, linked to payslips #4 and #5 (worker 2: 30% × 7,500 − 170 = 2,080.00);
  - the employee screen shows it.

There were no 5xx responses and no page errors. Screenshots were inspected.

## 7. Open / next

- **Sources:** S24 (Art. 97 eligibility, Art. 152 annual tariff, application rules).
- **Phase 9 is complete in mechanics** (9a–9e). Every legal rule still needs its source transcribed (S21, S24, S25, S26, S28).
- **Next phase per the implementation plan:** Phase 10 (bank / payments and the G1–G8 release gates).
