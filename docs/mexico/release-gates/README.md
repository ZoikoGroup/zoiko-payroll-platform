# Mexico release gates — evidence register (G1–G8)

**For:** the Super Admins who prepare and sign Mexico's go-live evidence, and whoever approves the launch.

Mexican payroll stays **off** until all eight gates are signed (spec §22). Signing a gate is a human decision on real evidence. Building the software does not sign anything.

## How a gate is signed

1. Complete the gate's checklist (`G1/CHECKLIST.md` … `G8/CHECKLIST.md`) and assemble the evidence pack (PDF).
2. A Super Admin opens Super Admin → Mexico compliance → **Sources**, adds a source with **Form/Publication #** `MX-GATE-Gn`, then uses **Upload File** for the evidence pack (Zoiko computes its SHA-256).
3. **A different Super Admin** clicks **Mark reviewed** on it. The uploader cannot review it, and an entry with no uploaded file never counts.
4. The gate then shows **SIGNED** on the **Readiness G1–G8** tab. Created or uploaded but not yet reviewed shows **SUBMITTED**.
5. A superseded artifact no longer counts. Upload the replacement and review it again.

Even with all eight gates signed, Mexico stays off until the activation runbook (`docs/mexico/MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md`) is followed. That includes the `MX_TENANT_ONBOARDING_ENABLED` deployment flag, which only a deployment change sets.

## The gates

| Gate | Area | Definition | Checklist |
|---|---|---|---|
| G1 | ISR / CFDI | 2026 Annex 8, subsidy, special-pay tax treatment and CFDI 4.0 / Nómina 1.2 reconciled to SAT / PAC validation. | [G1/CHECKLIST.md](G1/CHECKLIST.md) |
| G2 | IMSS / SUA | SBC and every launch IMSS branch including 2026 CEAV reconcile to current SUA on signed cases. | [G2/CHECKLIST.md](G2/CHECKLIST.md) |
| G3 | INFONAVIT | 5% employer contribution and credit-withholding / reconciliation flow proven. | [G3/CHECKLIST.md](G3/CHECKLIST.md) |
| G4 | State ISN | Each enabled work state has signed current base / rate / exemption / return content; unsupported states are hard-blocked. | [G4/CHECKLIST.md](G4/CHECKLIST.md) |
| G5 | Labor | Minimum wage zones / professions, 2026 workweek / overtime, vacations, aguinaldo and PTU validated. | [G5/CHECKLIST.md](G5/CHECKLIST.md) |
| G6 | External operations | PAC, SAT payment, IDSE / SUA / SIPARE, INFONAVIT and bank workflows have unknown / reject / recovery paths. | [G6/CHECKLIST.md](G6/CHECKLIST.md) |
| G7 | Security / privacy | Certificates / secrets, personal identifiers, 2025 privacy-law controls and restore procedures signed. | [G7/CHECKLIST.md](G7/CHECKLIST.md) |
| G8 | Parallel payroll | At least two consecutive payroll cycles plus one IMSS / INFONAVIT and one tax-period reconciliation show zero unexplained material differences. | [G8/CHECKLIST.md](G8/CHECKLIST.md) |

## Owner decisions (legal)

Recorded the same way, as a source artifact reviewed by a second Super Admin:

| Decision | Tag | Unblocks |
|---|---|---|
| Retention period per record category | `MX-DECISION-RETENTION-PERIOD` | Proposing a retention period (then a second Super Admin approves it) |
| Deletion vs anonymisation at end of retention | `MX-DECISION-RETENTION-END` | The end-of-retention choice |
| Hosting and cross-border transfers (2025 privacy law) | `MX-DECISION-HOSTING` | G7 |
