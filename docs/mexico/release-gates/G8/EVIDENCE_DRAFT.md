# Mexico release gate G8 — Parallel payroll — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G8 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G8` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- Pilot machinery: four-eyes pilot grants, the PILOT watermark, no payments or filings in the pilot (`test_mexico_pilot.py`), the onboarding pause (`test_mexico_onboarding_pause.py`), the payroll journal for reconciliation (`test_mexico_journal.py`)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- None: every item of this gate needs a person or an external party.

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PILOT-GENERATED] Two consecutive cycles run in the pilot organisation in parallel with the current provider; every difference explained
- [PILOT-GENERATED] One IMSS / INFONAVIT bimester reconciled (SUA figures entered and compared) and one ISR tax period reconciled
- [PILOT-GENERATED] Sign-off by the employer's payroll owner and by Zoiko
- The G8 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- None by engineering: every G8 item is produced by the pilot organisation with the employer

Source of the checklist: `docs/mexico/release-gates/G8/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
