# Mexico (MX) — Phase 9d Implementation Report: PTU (employee profit sharing)

Spec ZP-MX-ENG-001 v1.0 §17 MX-054–MX-056 · plan `MEXICO_PHASE_9D_PLAN.md` (approved 2026-10-21 as recommended, D1–D10).

**Base.** `nikhil` = `4c34b8a`:
- the 9d plan;
- the Brazil ZP-PRIV fix `d63e2df`;
- Phase 9c `f256b81`;
- the ZP-PRIV merge `5ff6d17`.

**Alembic.**
- Before: a single head, `b4d8f2c6a9e3` (212 revisions).
- Now: a single head, **`c6e1a9d4f2b7`** (213 revisions).

**Git.** Committed on `nikhil`, **not pushed**.

**The constraint (unchanged).** No PTU source is saved (S21 / S24 / S25 / S26), so in production:
- a cycle can be recorded and its amount approved;
- nothing can be allocated (`MX_PTU_RULE_MISSING`);
- no operator exclusion can be recorded (`MX_PTU_EXCLUSION_RULE_MISSING`);
- no PTU payslip can be withheld (`MX_SPECIAL_PAY_RULE_MISSING`).

Everything is proved with SYNTHETIC rules.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite (5 chunks, 346 files) | **7,013 passed, 8 failed, 91 skipped, 2 xfailed.** No open Mexico failure: 1 was fixed and re-run; the other 7 are local-only or order-dependent (§6). |
| Phase 9d tests | `test_mexico_ptu.py` (9) and `test_mexico_ptu_migrations.py` (6, of which 4 run on PostgreSQL). All pass. |
| Tests updated for the intended change | Dormancy lists the 12 new routes (and treats the exclusion-approve route like other employee-naming routes); "every Phase 9 run type is built" replaces "PTU is still refused"; head pins; migration tables; the pending-objects check. |
| Migration on PostgreSQL 17 | 6/6, three runs (real CLI, current = head, schema drift clean). |
| Browser | **off 8/8, on 7/7, rules 12/12** (§6). |
| ESLint / `check:undefined` / `vite build` | 0 errors in new or changed files; 557 files clean; the build passes. |

## 2. What was built

**Content seams (empty).**
- `MX_PTU_RULE`: `allocate(pool, workers, fiscal_year)` and `payment_deadline(fiscal_year, employer)`.
- `MX_PTU_EXCLUSION_REASONS`: the catalog of exclusions an operator may assert.
- The withholding is the existing special-pay rule for the concept `PTU`.

**Engine (`engine/jurisdictions/mexico/ptu.py`).** It fixes the interface and refuses (`MX_PTU_RULE_INVALID`) any allocation where:
- a worker is missing or duplicated;
- a share or amount is negative;
- an excluded worker has no reason, or still gets money;
- an approved operator exclusion is ignored;
- the final amounts plus the residue do not equal the pool exactly.

`special_pay.RUN_CONCEPTS["PTU"]` makes PTU a special run (no IMSS / CEAV / INFONAVIT, no subsidy, never in ordinary accumulators — MX-056).

**Migration `c6e1a9d4f2b7` (mx_ptu_m10).**
- **Two new tables:** `payroll_mx_ptu_cycles` (a partial unique index on employer + fiscal year while live) and `payroll_mx_ptu_allocations` (unique per cycle and worker). No shared column.
- **RLS, the 9c pattern:** each table gets its ZP-PRIV policy with a fixed predicate (cycles: tenant; allocations: worker, "org"), on these tables only. The PostgreSQL test proves `classify()` agrees.

**`mexico_ptu_service.py`**
- **Cycle:**
  - per legal employer (root profile) and **ended** fiscal year (D1);
  - the employer's distributable amount (> 0) with an evidence reference (D2);
  - one live cycle per employer and year;
  - amount approved by another person.

  The pay-by date comes from the rule, or is "unsourced" (D8).
- **Operator exclusions (D6):**
  - only a catalog reason, with evidence;
  - approved by another person;
  - a pending one blocks allocation (`MX_PTU_EXCLUSION_PENDING`).
- **Qualifying facts (D3 / D4):** from **committed** ORDINARY / CORRECTION payslips of the fiscal year under that employer's IMSS registration. A payslip superseded by a committed correction is left out, and its correction counts.
  - Each worker gets days and salary by concept kind (plus the classification's PTU wage-base flag).
  - A finiquito's lines are kept apart.
  - The facts are frozen by fingerprint at allocation. Approval (by someone other than the allocator) re-computes them and blocks if anything committed since has changed them (`MX_PTU_ALLOCATION_STALE`).
- **PTU run (D7):**
  - one per approved cycle, period = the fiscal year, paid after it;
  - pays each eligible worker's final amount, **leavers included** (an MX-only selection hook);
  - atomic;
  - commit links each allocation to its payslip and marks the cycle **DISTRIBUTED**; reset reverses it;
  - a cycle cannot be cancelled once a run exists.

**Routes (12, behind the Phase 4a guard, in the ZP-PRIV registry).**
- Cycles: list, create, detail.
- Approve amount.
- Exclusions: record, approve.
- Allocate; approve allocation.
- PTU run; cancel.
- Exclusion catalog.
- The employee's PTU.

**Frontend.**
- `MXPtuCyclePanel` in the Mexico Compliance Centre:
  - record;
  - approve amount;
  - exclusions (catalog only);
  - allocate (allocation table with shares, cap, exclusion and evidence, residue);
  - approve;
  - open the PTU run;
  - cancel.
- `MXPtuPanel` on the employee's statutory panel.

## 3. Migration `c6e1a9d4f2b7` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payroll_runs` / `payroll_employees` / `payslip_items` / `users` / `organizations` | **106–133 ms** over three runs (106.29, 109.54 and 133.19 ms). |
| In flight | Reads continue; a writer's `ROW EXCLUSIVE NOWAIT` is refused; no existing table is locked exclusively. |
| A writer holding `payroll_runs` | Gives up after **5.12–5.25 s** with nothing created. |
| Row-level security | ENABLE + FORCE plus `zoiko_rls` on both new tables; `classify()` agrees (cycles tenant, allocations worker "org"). |
| CLI path | `alembic upgrade head`, current = head, schema drift clean. |

## 4. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `c6e1a9d4f2b7` | **Two new, empty tables** with their RLS policies, no shared column. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s with nothing created if a writer holds a table. |
| Routes | **Unreachable** while dormant (all 12 refused). |
| Engine / run | `RUN_CONCEPTS["PTU"]`; `BUILT_RUN_TYPES` now includes PTU; an MX-only selection hook for PTU runs. Nothing changes for other run types or countries. |
| Content | Empty: no allocation, no exclusion, no PTU withholding. |
| Screens | The PTU panel shows only the dormancy refusal; other countries are unchanged. |

**Net effect:** additive, and no behaviour change for any jurisdiction.

## 5. Deviations and findings

1. **Operator exclusions are stored on the cycle** (a JSON list with reason, evidence, recorder and approver) until allocation, then copied onto each allocation row. The plan put them only on the allocation rows, but an exclusion has to exist before the allocation does.
2. **The pay-by date is shown on the cycle only.** Listing it in Phase 8's due-date view (plan P6) is left for when S21 is transcribed, because today it is always "unsourced".
3. **"Ended fiscal year"** uses the server date. The tests and the browser harness set it to 2027-03-01 so the synthetic 2026 world qualifies.
4. **A finiquito's lines** reach the rule separately (`finiquito_by_kind`): whether termination pay counts toward PTU salary is the rule's decision (S26).

## 6. Full suite and browser

**Full backend suite** — 5 chunks (346 files) on scratch SQLite, run sequentially on the finished tree: **7,013 passed, 8 failed, 91 skipped, 2 xfailed.**

| Failures | Test(s) | Cause |
|---|---|---|
| 1 | `test_mexico_run_dormancy::test_guard_codes_directly` | Used PTU as the "not yet built" run type. Every Phase 9 type is now built, so it uses an unknown type. Re-run: 10/10. **Fixed.** |
| 3 | `tests/privacy/test_route_registry.py` | The user's **uncommitted** `/health/version` and `/health/ready` routes in `backend/app/main.py`. The committed registry (1,137 entries) equals a fresh generation without them. **Local only.** |
| 1 | `test_hong_kong_configuration.py` | Reads the untracked local HK owner pack. **Local only.** |
| 3 | `test_outbound_delivery_guard`, `test_payroll_email_templates`, `test_payroll_email_templates_batch2` | Order-dependent: they pass on their own. Changed by the ZP-PRIV merge. **Rugvedh.** |

The raw-query ratchet and the Brazil test now pass (Brazil fix `d63e2df`).

**Browser** (installed Chrome, vite preview of this build, scratch SQLite):
- **off 8/8:** all PTU routes refused; the panel shows the dormancy refusal; NL unchanged.
- **on 7/7:** a cycle is recorded and its amount approved by a second person; the pay-by date is "unsourced"; exclusions and allocation are blocked with `MX_PTU_EXCLUSION_RULE_MISSING` / `MX_PTU_RULE_MISSING`.
- **rules 12/12:**
  - four-eyes on the amount and on the allocation;
  - a catalog exclusion with evidence;
  - the allocation from committed runs (worker 1 is paid 10,000.00 and worker 2 is excluded, `SYN_DIRECTOR (SYN-BOARD-MINUTES)`);
  - the PTU run: one `MX_PTU` line, 100 exempt, 10% withholding = 990.00, no IMSS, ISN 300.00;
  - commit → DISTRIBUTED;
  - the employee screen shows the allocation.

There were no 5xx responses and no page errors. The only 4xx are the deliberate refusals. Screenshots were inspected.

## 7. Open / next

- **Sources:** S26 (PTU rule, exclusion catalog), S21 (window), S24 / S25 (PTU withholding).
- **9e** (annual ISR adjustment).
- **Integration:** see `PRODUCTION_STATE.md`. Pushing `nikhil` and opening a PR lets CI run both jobs without deploying.
