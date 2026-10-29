# Mexico release gate G2 — IMSS / SUA — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G2 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G2` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- `docs/mexico/sources/SOURCES_MANIFEST.csv` (33 rows on 2026-10-27: 31 `ARCHIVE_COPY_VERIFIED`, 1 `VERIFIED` (S22), 1 `WRONG_VERSION`) and `docs/mexico/sources/VERIFICATION_LOG.csv` (1 `MATCH`: S22)
- `docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md` (every transcribed row with its source, page and the blind second transcription), and `python -m scripts.verify_mexico_sources compare` (every number and every quoted rule wording found in its cited file)
- Content transcribed [PENDING G1]: every IMSS branch and side, the SBC ceiling, CEAV 2023–2030 (seeded 2026 bands), the SBC floor at the zone minimum wage, contribution days for absences and incapacity (LSS Art. 31), the risk-premium period (RACERF Art. 32 III), the five-business-day movement deadline (LSS Art. 15 I)
- Engine and services: `test_mexico_engine_imss_ceav_infonavit.py`, `test_mexico_engine_sbc.py`, `test_mexico_imss_registrations.py`, `test_mexico_risk_premiums.py`, `test_mexico_authorities_movements.py`, `test_mexico_authorities_sua_isn.py`
- IMSS-branch report and the SUA / SIPARE / IDSE generators, each labelled NOT AN OFFICIAL FILE (`test_mexico_report_generators.py`)
- Super Admin read-only views (W5-1): Compliance → Mexico → Statutory rules, and each content tab, show every value with its source file, SHA-256, verification status and [PENDING G1]; readiness per gate (W5-3) shows which checklist items code confirms now. Browser evidence: `docs/mexico/completion-evidence/w5/` (39/39 PASS)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

**Final mile (2026-10-28) — what the new tooling now produces for this gate:**

- Decision register: D-03 (CEAV lowest band — blocks every calculation), D-16, D-18
- Sandbox fixtures F1–F3 (UMA boundary, first-year SBC factor, CEAV high band) reproduce with candidate answers (`test_mexico_sandbox.py`)
- Reports: MX-SBC-MOVEMENTS, MX-WORK-RISK-ANNUAL (NOT AN OFFICIAL FILE)
- Intake templates for the official layouts: `intake/IDSE_INTAKE.md`, `intake/SUA_INTAKE.md`, `intake/SIPARE_INTAKE.md`

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- [PRE-PILOT] Every IMSS branch rate, ceiling and the 2026 CEAV band transcribed, in an Approved pack — code check `national_pack_approved`

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PRE-PILOT] Signed cases with synthetic workers: SBC (fixed, variable, mixed) and each branch per worker reconcile to the same cases computed in the SUA program, with zero difference (Phase 8 SUA reconciliation)
- [PRE-PILOT] An approved work-risk premium with its validity window from S29, from the employer's own IMSS determination
- [PRE-PILOT] IDSE movements (alta, baja, modificación) for synthetic workers: the worklist matches IDSE's capture fields
- [GO-LIVE CHECK] The first real IDSE filing, accepted (activation runbook §6; not gate evidence)
- The G2 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- D-01, D-16 (business days), D-18 (FIXED SBC items); gap register A18 (monthly vs bimonthly IMSS liability), C8 (official SUA / IDSE layouts not saved)

Source of the checklist: `docs/mexico/release-gates/G2/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
