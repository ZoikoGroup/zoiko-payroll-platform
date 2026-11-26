# South Africa (ZA): Gaps and Decisions Register (gate removal)

Master note: `docs/GATE_REMOVAL.md` · Row inventory: `GATE_REMOVAL_INVENTORY.md`

The release-gate documents in this folder (`release-gates/`, `RUNBOOK_GO_LIVE.md`) are superseded by this register.

## Decisions (owner, 2026-11-25)

| ID | Status | Description |
|---|---|---|
| GR-1 | DECIDED | **Go-live like Spain.** No dormancy switch, canary list, release gates (G0–G8), gate evidence, sign-offs, owner-decision records or parallel-run requirement. Registration opens once an Active `ZA-PAYROLL-2027` pack with content exists and no PLANNED registry row blocks it. |
| GR-2 | DECIDED | **No signing.** The `[PENDING G1]` label marker no longer blocks and is never written. A saved value is in force. A source document is optional provenance; a change reason is required. |
| GR-3 | DECIDED | **Missing values.** A value no document gives is never invented. It blocks only the calculation that needs it, with a named reason, until a Super Admin enters it. |
| GR-4 | DECIDED | **Approval.** Only the platform-wide rules apply: approver ≠ the pack's last editor; no overlapping Active packs. |
| GR-5 | DECIDED | **Proposed values.** The owner approved every proposed policy value (P) and statutory value not stated by the spec (S) in `GATE_REMOVAL_INVENTORY.md`. |

## Values written on 2026-11-25

| Item | Value |
|---|---|
| PAYE tax-year date basis, s7B timing | `PAYMENT_DATE` |
| ETI offset | `OFFSET_UP_TO_PAYE` |
| BCEA overtime / Sunday / public-holiday multiplier | 1.5 / 2.0 / 2.0 (S) |
| Damage / loss deduction limit | 25% of net pay (S) |

## Still blocked (a narrow, named block until a source or new logic exists)

- SARS BRS v25.3.0 source-code catalogue (EMP501 / IRP5 exports stay previews)

## Open points

- One Sunday multiplier (2.0) applies to everyone; employees who ordinarily work Sundays are owed 1.5 (BCEA s16).
