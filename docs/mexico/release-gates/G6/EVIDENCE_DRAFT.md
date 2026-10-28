# Mexico release gate G6 — External operations — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G6 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G6` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- CFDI lifecycle with the SYNTHETIC mock PAC: stamp, timeout, UNKNOWN, reconcile, cancel and replace (`test_mexico_cfdi_lifecycle.py`, `test_mexico_cfdi_unknown.py`, `test_mexico_cfdi_lineage.py`); the stamped XML is kept (W4-3b)
- Authority lifecycles with UNKNOWN handling (`test_mexico_authorities_unknown.py`, `test_mexico_authorities_liabilities.py`, `test_mexico_authorities_reset.py`), the runbook `docs/mexico/MEXICO_UNKNOWN_STATE_RUNBOOK.md`
- Salary payments released four-eyes (`test_mexico_payments.py`); the payroll journal (`test_mexico_journal.py`)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

**Final mile (2026-10-28) — what the new tooling now produces for this gate:**

- Report MX-PAYMENT-WORKLIST (NOT A BANK FILE)
- Intake templates: `intake/SPEI_INTAKE.md`, IDSE / SUA / SIPARE
- PAC conformance kit and checklist; durable XML store contract (`CFDI_XML_STORAGE_CONTRACT.md`, write-once, hash-checked, retention field)
- "Reconcile after restore" on the run's CFDI stage (the UNKNOWN-state runbook's restore step; X8)

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- None: every item of this gate needs a person or an external party.

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PILOT-GENERATED] PAC sandbox end to end from pilot runs, including a REJECT and an UNKNOWN case resolved by the runbook (docs/mexico/MEXICO_UNKNOWN_STATE_RUNBOOK.md)
- [PRE-PILOT] IDSE, SUA / SIPARE, SAT and INFONAVIT lifecycles on staging with synthetic objects: a REJECT and an UNKNOWN case each, resolved by the runbook
- [PRE-PILOT] A database restore drill on staging: in-flight CFDI actions moved to UNKNOWN and reconciled
- [PRE-PILOT] Salary payments on staging with synthetic data: a batch released by a second person, settled, one returned and re-issued
- [PILOT-GENERATED] The pilot's payroll journal exported and imported into the employer's accounting system
- [GO-LIVE CHECK] The first real SAT declaration, IMSS / INFONAVIT payment and salary payment, each resolved to a final outcome (activation runbook §6)
- The G6 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- Gap register C1 (PAC), C3 (CSD), C7 (bank / SPEI); A12 (runs stop at Approved)

Source of the checklist: `docs/mexico/release-gates/G6/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
