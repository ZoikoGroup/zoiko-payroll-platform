# Malaysia (MY): Gaps and Decisions Register (gate removal)

Master note: `docs/GATE_REMOVAL.md` · Row inventory: `GATE_REMOVAL_INVENTORY.md`

The release-gate documents in this folder (`release-gates/`, `RUNBOOK_GO_LIVE.md`) are superseded by this register.

## Decisions (owner, 2026-11-25)

| ID | Status | Description |
|---|---|---|
| GR-1 | DECIDED | **Go-live like Spain.** No dormancy switch, canary list, release gates (G0–G8), gate evidence, sign-offs, owner-decision records or parallel-run requirement. Registration opens once an Active `MY-PAYROLL-2026` pack with content exists and no PLANNED registry row blocks it. |
| GR-2 | DECIDED | **No signing.** The `[PENDING G1]` label marker no longer blocks and is never written. A saved value is in force. A source document is optional provenance; a change reason is required. |
| GR-3 | DECIDED | **Missing values.** A value no document gives is never invented. It blocks only the calculation that needs it, with a named reason, until a Super Admin enters it. |
| GR-4 | DECIDED | **Approval.** Only the platform-wide rules apply: approver ≠ the pack's last editor; no overlapping Active packs. |
| GR-5 | DECIDED | **Proposed values.** The owner approved every proposed policy value (P) and statutory value not stated by the spec (S) in `GATE_REMOVAL_INVENTORY.md`. |

## Values written on 2026-11-25

| Item | Value |
|---|---|
| EPF direct-calculation rounding | `RINGGIT_UP` |
| PERKESO / EIS / HRD rounding | `SEN_HALF_UP` |
| EPF age-60 transition, EIS age rule | `FROM_MONTH_AFTER_BIRTHDAY`, `AGE_AT_WAGE_MONTH_START` |
| HRD levy on | `MALAYSIAN_EMPLOYEES_ONLY` |
| Overtime multipliers: workday / rest day / public holiday | 1.5 / 2.0 / 3.0 (S, all territories) |
| Ordinary-rate divisor | 26 days (S) |
| Sick leave / annual leave tiers | `0:14,2:18,5:22` / `0:8,2:12,5:16` |
| Hospitalisation leave, record retention | 60 days / 7 years (S) |

## Still blocked (a narrow, named block until a source or new logic exists)

- PCB — stub until the HASiL computerised MTD specification is archived
- Minimum-wage daily / hourly rules, HRD levy base, EPF / SOCSO / HRD due rules, leave-pay rule
- LINDUNG 24 JAM phase rule

## Open points

- Sabah and Sarawak use the Peninsular figures (as approved); the inventory flagged them to confirm.
