# Japan (JP): Gaps and Decisions Register (gate removal)

Master note: `docs/GATE_REMOVAL.md` · Row inventory: `GATE_REMOVAL_INVENTORY.md`

The release-gate documents in this folder (`release-gates/`, `RUNBOOK_GO_LIVE.md`) are superseded by this register.

## Decisions (owner, 2026-11-25)

| ID | Status | Description |
|---|---|---|
| GR-1 | DECIDED | **Go-live like Spain.** No dormancy switch, canary list, release gates (G0–G8), gate evidence, sign-offs, owner-decision records or parallel-run requirement. Registration opens once an Active `JP-PAYROLL-2026` pack with content exists and no PLANNED registry row blocks it. |
| GR-2 | DECIDED | **No signing.** The `[PENDING G1]` label marker no longer blocks and is never written. A saved value is in force. A source document is optional provenance; a change reason is required. |
| GR-3 | DECIDED | **Missing values.** A value no document gives is never invented. It blocks only the calculation that needs it, with a named reason, until a Super Admin enters it. |
| GR-4 | DECIDED | **Approval.** Only the platform-wide rules apply: approver ≠ the pack's last editor; no overlapping Active packs. |
| GR-5 | DECIDED | **Proposed values.** The owner approved every proposed policy value (P) and statutory value not stated by the spec (S) in `GATE_REMOVAL_INVENTORY.md`. |

## Values written on 2026-11-25

| Item | Value |
|---|---|
| Correction policy | `DELTA_PAYSLIP` |
| Social / employment insurance employee-share rounding | `HALF_DOWN` (≤ 0.50 yen down, > 0.50 up) |
| Care insurance split | `EQUAL` |
| Overtime / holiday / night premium combination | `ADDITIVE` |
| YEA taxable income / annual tax rounding | `DOWN_1000` / `DOWN_100` |
| YEA earliest month | 12 |
| Special reconstruction income tax | 2.1% (S) |
| Resident tax special collection due day | 10th of the following month (S) |

## Still blocked (a narrow, named block until a source or new logic exists)

- NTA monthly, bonus and computer-method withholding tables; YEA tables and income limit
- Prefectural health rates, SMR grade tables, minimum wages, public holidays, workers' compensation
- Withholding due date on a non-business day (needs a holiday calendar)
- Withholding rounding; statutory-holiday substitution rule

## Open points

- Employer share of social / employment insurance also rounds `HALF_DOWN` (the engine uses one rule for both shares).
- No salary bank-routing fields for Japanese employees yet.
