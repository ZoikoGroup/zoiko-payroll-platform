# New Zealand (NZ): Gaps and Decisions Register (gate removal)

Master note: `docs/GATE_REMOVAL.md` · Row inventory: `GATE_REMOVAL_INVENTORY.md`

The release-gate documents in this folder (`release-gates/`, `RUNBOOK_GO_LIVE.md`) are superseded by this register.

## Decisions (owner, 2026-11-25)

| ID | Status | Description |
|---|---|---|
| GR-1 | DECIDED | **Go-live like Spain.** No dormancy switch, canary list, release gates (G0–G8), gate evidence, sign-offs, owner-decision records or parallel-run requirement. Registration opens once an Active `NZ-PAYROLL-2026-27` pack with content exists and no PLANNED registry row blocks it. |
| GR-2 | DECIDED | **No signing.** The `[PENDING G1]` label marker no longer blocks and is never written. A saved value is in force. A source document is optional provenance; a change reason is required. |
| GR-3 | DECIDED | **Missing values.** A value no document gives is never invented. It blocks only the calculation that needs it, with a named reason, until a Super Admin enters it. |
| GR-4 | DECIDED | **Approval.** Only the platform-wide rules apply: approver ≠ the pack's last editor; no overlapping Active packs. |
| GR-5 | DECIDED | **Proposed values.** The owner approved every proposed policy value (P) and statutory value not stated by the spec (S) in `GATE_REMOVAL_INVENTORY.md`. |

## Values written on 2026-11-25

| Item | Value |
|---|---|
| PAYE / ACC / SL / KiwiSaver / ESCT / child support / holiday pay rounding | `NEAREST_CENT_HALF_UP` |
| KiwiSaver employer contributions up to age | 65 (S) |
| Holidays Act AWE lookback / divisor, OWP fallback, ADP lookback | 12 months / 52 weeks / 4 weeks / 52 weeks (S) |
| OWP / RDP / ADP / final-pay methods | `AGREEMENT_THEN_FALLBACK` / `AGREEMENT_DAILY` / `RDP_UNDETERMINABLE_OR_VARIES` / `PCT_OF_GROSS_SINCE_ANNIVERSARY` |
| Out-of-cycle / lump-sum PAYE method | `EXTRA_PAY` / `EXTRA_PAY_FOUR_WEEK_ANNUALISE` |
| Correction policy | `COMPENSATING_DELTA` (to confirm) |
| Deduction precedence | `PAYE,ACC_LEVY,STUDENT_LOAN,KS_EMPLOYEE,CHILD_SUPPORT` (to confirm) |

## Still blocked (a narrow, named block until a source or new logic exists)

- PAYE main-method, secondary and ND tables; IETC; child-support variation codes; lump-sum method table; IRD examples; public holidays; ACC classifications
- Payday-filing working-day rule and payload version

## Open points

- Confirm `COMPENSATING_DELTA` as the correction policy and the deduction order above.
- No salary bank-routing fields for New Zealand employees yet.
