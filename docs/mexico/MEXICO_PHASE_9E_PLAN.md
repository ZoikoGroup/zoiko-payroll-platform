# Mexico (MX) — Phase 9e Plan: Annual ISR adjustment

Spec ZP-MX-ENG-001 v1.0 §4 MX-010 · Phase 9 plan B8, D9, X6 · implementation plan v1.1 §12 (`payroll_mx_annual_isr_adjustments`, `engine/jurisdictions/mexico/annual_adjustment.py`, `MXAnnualIsrAdjustmentTab.jsx`).

**Base.** `main` = `46d26fa` (PR #116). Production is at `c6e1a9d4f2b7`: deploy `39568307882` was green, including the head check and schema drift. `nikhil` = `61826a4`.

**Status.** Approved by the user on 2026-10-21, before this text was written ("start working i have approved"), as recommended. Build follows directly. Any decision below can still be changed.

## 1. What it is, and what Zoiko decides

Once a fiscal year has ended, the employer computes each eligible worker's **annual** ISR on the year's income and compares it with what was withheld (net of the employment subsidy). The **difference** is charged or refunded in a later payroll (LISR Art. 97).

Everything legal comes from transcribed content (**S24** Arts. 97 and 152, the annual tariff; S1 / S2):
- who is eligible and why someone is excluded;
- the annual tariff;
- how a difference is applied in a run (limits, refunds, carry-forward).

Nothing is saved, so 9e builds the **mechanics**: blocked with a named code, proved with SYNTHETIC rules. **A historical payslip or CFDI is never edited** (MX-010).

## 2. Scope

| # | Item | What it does |
|---|---|---|
| A1 | **Computation** | Per legal employer and **ended** fiscal year, per worker paid by that employer, from **committed** runs only (corrections replace their originals; special runs included and labelled):<br>• taxable income by run type;<br>• ISR withheld;<br>• subsidy applied;<br>• employment dates.<br>The transcribed rule decides eligibility (with a reason) and the annual ISR. Stored per worker with every input, the rule source and an input fingerprint. Status: COMPUTED. |
| A2 | **Operator exclusions** | Only a catalog reason (e.g. the worker gave written notice that they file their own return), with evidence, approved by a second person. Excluded → WAIVED with the reason. |
| A3 | **Approval** | A second person approves the employer-year. It is refused if the inputs changed since computing (stale), as in 9d. Status: APPROVED. |
| A4 | **Application (D9)** | The operator picks a **later, uncommitted ORDINARY run** of the same organisation. Each approved worker in it gets the difference applied to that payslip's withholding by the transcribed rule (charge, refund within the period's withholding, carry-forward), as a separate **annual adjustment** section of the payslip.<br>Commit marks the row APPLIED, linked to the payslip; a reset reverts it to APPROVED. |
| A5 | **UI** | An "Annual ISR adjustment" panel in the Compliance Centre (compute → exclusions → approve → apply to a run) and a per-worker view on the employee screen. |

**Out of scope (named):**
- applying a carried-forward balance in a further run;
- a refund larger than the period's withholding being paid out of other workers' ISR (LISR Art. 97 offset);
- the annual information return (DIM / CFDI 4.0 annual data).

## 3. Data model — migration `mx_annual_adjustment_m11` (one new table, no shared column)

`payroll_mx_annual_isr_adjustments` holds:
- **keys:** id, organization_id, employer_profile_id, fiscal_year, employee_id;
- **outcome:** status (COMPUTED / APPROVED / APPLIED / WAIVED), eligible, exclusion_reason, exclusion_evidence_ref, exclusion_recorded_by_id, exclusion_approved_by_id;
- **inputs:** income_by_run_type (JSON), annual_taxable, withheld_total, subsidy_applied_total, annual_isr, difference, inputs_fingerprint, rule_source;
- **people:** computed_by_id, approved_by_id;
- **application:** applied_run_id (SET NULL), applied_item_id (RESTRICT), applied_withheld_change, carry_forward;
- **timestamps.**

Unique on (employer_profile_id, fiscal_year, employee_id). It gets the ZP-PRIV RLS policy on this table only (a worker table, "org"), as in 9c / 9d.

## 4. Content seams (empty)

`MX_ANNUAL_ADJUSTMENT_RULE` provides three methods:

| Method | Returns |
|---|---|
| `eligibility(worker, fiscal_year)` | `(eligible, reason)` |
| `annual_isr(annual_taxable, fiscal_year, facts)` | Decimal ≥ 0 |
| `apply_in_run(period_withheld, difference, facts)` | `{withheld, carry_forward}` |

The engine enforces `withheld ≥ 0` and `(withheld − period_withheld) + carry_forward == difference`.

`MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS` is the operator catalog.

| Missing | Code |
|---|---|
| Rule | `MX_ANNUAL_ADJUSTMENT_RULE_MISSING` |
| Catalog | `MX_ANNUAL_ADJUSTMENT_EXCLUSION_RULE_MISSING` |

## 5. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration | One new, empty table with its RLS policy. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s. |
| Routes | Refused while Mexico is dormant. |
| Engine | The ordinary path changes only when an approved adjustment is attached to the payslip, which cannot happen (empty content, dormant). |
| Screens | Dormancy refusal only. |

**Net:** additive, no behaviour change for any jurisdiction.

## 6. Decisions (approved as recommended)

| # | Decision | Choice |
|---|---|---|
| D1 | Unit | Per legal employer and ended fiscal year (as PTU). |
| D2 | Inputs | Committed runs only, frozen by fingerprint, stale-checked at approval. |
| D3 | Income | By run type (ordinary, correction, aguinaldo, PTU, finiquito); the rule decides what counts. |
| D4 | Eligibility and tariff | Entirely the transcribed rule; empty → block. |
| D5 | Operator exclusions | Catalog reason + evidence + a second approver only. |
| D6 | Application | A separate section of a later, operator-chosen ORDINARY run's payslip. Historical payslips and CFDIs are never edited (MX-010). |
| D7 | Refunds | Only within the period's withholding (never negative withholding); the rest is recorded as carry-forward. |
| D8 | Approval | Four-eyes per employer-year. |
| D9 | Super Admin view | None (worker data, ZP-PRIV). |
| D10 | Out of scope | As listed in §2. |
