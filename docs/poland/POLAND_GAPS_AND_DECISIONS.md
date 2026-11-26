# Poland (PL): Gaps and Decisions Register (gate removal)

Master note: `docs/GATE_REMOVAL.md` · Row inventory: `GATE_REMOVAL_INVENTORY.md`

The release-gate documents in this folder (`release-gates/`, `RUNBOOK_GO_LIVE.md`) are superseded by this register.

## Decisions (owner, 2026-11-25)

| ID | Status | Description |
|---|---|---|
| GR-1 | DECIDED | **Go-live like Spain.** No dormancy switch, canary list, release gates (G0–G8), gate evidence, sign-offs, owner-decision records or parallel-run requirement. Registration opens once an Active `PL-PAYROLL-2026` pack with content exists and no PLANNED registry row blocks it. |
| GR-2 | DECIDED | **No signing.** The `[PENDING G1]` label marker no longer blocks and is never written. A saved value is in force. A source document is optional provenance; a change reason is required. |
| GR-3 | DECIDED | **Missing values.** A value no document gives is never invented. It blocks only the calculation that needs it, with a named reason, until a Super Admin enters it. |
| GR-4 | DECIDED | **Approval.** Only the platform-wide rules apply: approver ≠ the pack's last editor; no overlapping Active packs. |
| GR-5 | DECIDED | **Proposed values.** The owner approved every proposed policy value (P) and statutory value not stated by the spec (S) in `GATE_REMOVAL_INVENTORY.md`. |

## Values written on 2026-11-25

| Item | Value |
|---|---|
| Rounding: PIT / ZUS / health / PPK | `FULL_PLN_HALF_UP` / `GROSZ_HALF_UP` ×3 |
| Cost caps: standard / multi / commuter / multi-commuter | PLN 3,000 / 4,500 / 3,600 / 5,400 (S) |
| PIT-0 shared annual limit | PLN 85,528 (S) |
| FP/FS minimum base, fund cap | `BASE_AT_LEAST_MIN_WAGE`, `CAPPED_WITH_PENSION_BASE` |
| Employer PPK PIT treatment | `TAXABLE_EMPLOYEE_INCOME` |
| Overtime premiums | `LABOUR_CODE_151_1` (daily 50%, otherwise 100%) |
| Night supplement basis | `MIN_WAGE_HOURLY_20PCT` |
| Part-time leave rounding, sick-pay age rule | `ROUND_UP_FULL_DAY`, `FROM_YEAR_AFTER_REACHING_AGE` |
| PPK re-enrolment, benefit reference, retention | 4 years / 12 months / 10 years (S) |

## Still blocked (a narrow, named block until a source or new logic exists)

- Employer-fund exemption periods (age, return to work, under-30 hire) — engine logic not built
- PIT advance due date (`DAY_20_NEXT_MONTH` stored; not computed)
- Leave pay (REVIEW earning class)
- ZUS / PIT form schemas (filings stay previews)
