# Mexico (MX) — Phase 9d Plan: PTU (employee profit sharing)

Spec ZP-MX-ENG-001 v1.0 §17 MX-054–MX-056 · Phase 9 plan B7, D7, D8, X5 · implementation plan v1.1 §12 (`payroll_mx_ptu_cycles`, `payroll_mx_ptu_allocations`, `engine/jurisdictions/mexico/ptu.py`, `MXPtuCycleWizard.jsx`).

**Base.** `nikhil` = `d63e2df`: Phase 9c `f256b81` and the Brazil ZP-PRIV fix, on top of the ZP-PRIV merge `5ff6d17`. Nothing is pushed.

**Alembic.** A single head, `b4d8f2c6a9e3`. 9d adds one revision as its child.

**Production.** The database is at Rugvedh's `e1a3c5e7f9b2`. `main`'s last two deploys refused, correctly. The next deploy that succeeds is the integration of `nikhil` (see `PRODUCTION_STATE.md`).

**Status.** Plan only. **Waiting for approval.**

## 1. What PTU is, and what Zoiko does and does not decide

The employer shares a percentage of its taxable profit with its workers once a year:
- half by days worked in the fiscal year;
- half by salary earned in it;
- per-worker caps;
- eligibility and exclusions;
- a legal payment window.

**The profit is the employer's figure, from its own annual tax return.** Zoiko never computes it (MX-054). The employer enters the distributable amount with evidence, and a second person approves it.

**Every rule** (the split, which days and which salary count, eligibility, the caps, rounding, the payment window, the withholding) **comes from transcribed content:**
- LFT Arts. 117–131 → **S26**;
- the windows → **S21**;
- the exempt part and the ISR method → **S24** / **S25**.

None is saved, so, as in 9a–9c, 9d builds the **mechanics**. Every calculation blocks with a named code until its rule is transcribed, and is proved with SYNTHETIC rules.

## 2. Scope

| # | Item | What it does |
|---|---|---|
| P1 | **PTU cycle** | One per **legal employer** (D1) and fiscal year:<br>• the distributable amount and an evidence reference (the employer's annual declaration);<br>• recorded by one person, approved by another (`MX_FOUR_EYES_REQUIRED`).<br>Status: DRAFT → AMOUNT_APPROVED → ALLOCATED → APPROVED → DISTRIBUTED, or CANCELLED (only before its PTU run commits). |
| P2 | **Qualifying facts** | Per worker of that employer in the fiscal year, from **committed** runs only (D3): days, and salary by concept kind (the classification's `ptu_wage_base_included` flag and the line kind). Correction deltas (9a) are included. A finiquito's lines are kept separate so the rule can decide. |
| P3 | **Allocation** | The transcribed PTU rule allocates the pool:<br>• the days half and the salary half;<br>• eligibility with an exclusion reason;<br>• the per-worker cap comparison (both references kept);<br>• the rounding residue.<br>The engine only validates: every amount ≥ 0; the sum ≤ pool and equal to it after the content's residue rule; every exclusion carries a reason. Inputs are frozen at ALLOCATED. A later committed change to that fiscal year makes the allocation **stale**: approval blocks until it is re-allocated. |
| P4 | **Operator exclusions** | Only a reason from the content's exclusion catalog, with evidence, approved by a second person (D6). The rule's automatic exclusions are recorded with their reason. |
| P5 | **PTU run** | A special run type (Phase 9b path):<br>• one per cycle, paying each eligible worker's final amount;<br>• workers whose employment ended are included (the 9c "PTU right preserved");<br>• ISR by the special-pay rule (concept `PTU`, S24 / S25);<br>• never added to ordinary pay or ordinary accumulators (MX-056).<br>Commit marks the cycle DISTRIBUTED and links each allocation to its payslip; a reset reverses it. |
| P6 | **Payment window** | From content (S21); none → the Phase 8 "unsourced" deadline, never guessed. Shown on the cycle; Phase 8's due-date view lists it. |
| P7 | **UI** | A PTU cycle wizard in the Compliance Centre: amount + evidence → approve → allocate (preview table with every exclusion, cap and residue) → approve → open the PTU run. A per-worker view sits on the employee screen. |

**Out of scope (named, not built):**
- unclaimed PTU and its addition to the next year's pool (LFT Art. 122);
- an employer's objection / SAT adjustment of the profit;
- paying (Phase 10, bank).

## 3. Data model — migration `mx_ptu_m10` (two new tables, no shared column)

| Table | Columns |
|---|---|
| `payroll_mx_ptu_cycles` | id, organization_id, employer_profile_id, fiscal_year, distributable_amount, evidence_ref, note, status, recorded_by_id, approved_by_id, amount_approved_at, allocated_at, allocation_fingerprint (hash of the frozen inputs), allocation_approved_by_id, ptu_run_id (SET NULL), payment_deadline, deadline_rule_ref, rule_source, cancelled_reason, timestamps. Partial unique index (employer_profile_id, fiscal_year) WHERE status ≠ CANCELLED. |
| `payroll_mx_ptu_allocations` | id, cycle_id, employee_id, eligible, exclusion_reason, exclusion_evidence_ref, exclusion_approved_by_id, qualifying_days, qualifying_salary, salary_by_kind (JSON), days_share, salary_share, cap_reference (JSON: each cap and its basis), cap_applied, final_amount, payslip_item_id (RESTRICT), rule refs. |

Both are worker / tenant tables: the ZP-PRIV RLS policy goes on **these two tables only**, with a fixed predicate (the 9c pattern, no `classify()` at migration time). lock_timeout 5 s. Measured on PostgreSQL 17.

## 4. Content seams (empty)

`MX_PTU_RULE` is a rule object with its own source:

| Method | Returns |
|---|---|
| `allocate(pool, workers, fiscal_year)` | Per-worker days share, salary share, cap references, cap applied, final amount and exclusion reason, plus the residue. `workers` carries each worker's days, salary by kind, employment dates and history facts. |
| `payment_deadline(fiscal_year, employer)` | A date, or None. |

`MX_PTU_EXCLUSION_REASONS` is the catalog of operator exclusions (code → label, source).

The withholding uses the existing `MX_SPECIAL_PAY_RULES["PTU"]`.

| Missing | Code |
|---|---|
| PTU rule | `MX_PTU_RULE_MISSING` |
| Exclusion catalog | `MX_PTU_EXCLUSION_RULE_MISSING` |
| Withholding | `MX_SPECIAL_PAY_RULE_MISSING` |

## 5. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `mx_ptu_m10` | Two new, empty tables with their RLS policies. About 0.1 s of SHARE ROW EXCLUSIVE on `payroll_runs` / `payroll_employees` / `payslip_items`; fails fast after about 5 s with nothing created if a writer holds a table. |
| Routes | Behind the Phase 4a guard: refused while Mexico is dormant. |
| Engine / run | `RUN_CONCEPTS["PTU"]` and an MX-only run selection hook for PTU runs. No other path changes. |
| Content | Empty: no allocation can be made, no PTU run calculated. |
| Screens | The wizard shows only the dormancy refusal. Nothing changes for other countries. |

**Net:** additive, no behaviour change for any jurisdiction.

## 6. Tests (SYNTHETIC rules, labelled)

- **Four-eyes:** the amount needs evidence and a second person; an exclusion needs a catalog reason, evidence and a second person.
- **Inputs:** days and salary come only from **committed** runs (a draft run changes nothing); correction deltas are included.
- **Allocation:**
  - every exclusion carries a reason;
  - the cap comparison is stored;
  - allocations sum to the pool exactly;
  - rule output that breaks these is refused.
- **Directional:** more days → a larger days share; a higher salary → a larger salary share.
- **Stale inputs:** a committed change after allocation blocks approval until re-allocation.
- **The run:**
  - one per cycle;
  - a leaver is paid;
  - never in ordinary accumulators (MX-056);
  - commit / reset;
  - the cycle cannot be cancelled after the run commits.
- **Dormancy:** every route 403s with the flag off.
- **Migration:** SQLite idempotent; PostgreSQL lock measurement, fail-fast, RLS on the new tables only, CLI path and schema drift.
- **Browser:** off / on / rules, screenshots inspected.

## 7. Decisions needed from you (recommendation first)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Cycle unit | **Per legal employer (RFC) and fiscal year.** The profit is the employer's, from its own return; an organisation can hold several employers. (Plan v1.1 keyed it per organisation.) |
| D2 | The pool | **Employer-entered distributable amount + evidence reference + four-eyes.** Never derived from payroll (MX-054). |
| D3 | Qualifying data | **Committed runs only, frozen at ALLOCATED, stale-checked at approval.** Correction deltas included. |
| D4 | Salary base | The engine supplies **salary by line kind and classification flag**; the transcribed rule decides what counts. Nothing is hard-coded. |
| D5 | Split, caps, residue, eligibility | **Entirely the transcribed rule** (S26); empty → `MX_PTU_RULE_MISSING`. |
| D6 | Operator exclusions | **Only a content catalog reason, with evidence and a second approver.** No free-text exclusion. |
| D7 | Payment | **Its own PTU run** (special run, one per cycle), leavers included; never a line in an ordinary run (Phase 9 D8). |
| D8 | Payment window | **From content (S21); none → unsourced deadline**, never guessed. |
| D9 | Super Admin view | **None in 9d.** Allocations are worker data (ZP-PRIV); a cycle-level aggregate can come later through Rugvedh's aggregate path. |
| D10 | Unclaimed PTU / Art. 122 | **Out of scope**, named in the report. |

## 8. Order of work

Content seams and engine (`ptu.py`) → migration → service (cycle, inputs, allocation, exclusions, run hooks) → routes and registry → UI → tests → PostgreSQL → browser → report → commit on `nikhil` (no push).
