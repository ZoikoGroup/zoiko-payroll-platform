# Mexico release gate G3 — INFONAVIT — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G3 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G3` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- `docs/mexico/sources/SOURCES_MANIFEST.csv` (33 rows on 2026-10-27: 31 `ARCHIVE_COPY_VERIFIED`, 1 `VERIFIED` (S22), 1 `WRONG_VERSION`) and `docs/mexico/sources/VERIFICATION_LOG.csv` (1 `MATCH`: S22)
- `docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md` (every transcribed row with its source, page and the blind second transcription), and `python -m scripts.verify_mexico_sources compare` (every number and every quoted rule wording found in its cited file)
- Content transcribed [PENDING G1]: the 5% employer contribution, the percentage credit basis (SBC × days), the bimonthly payment calendar (Ley INFONAVIT Art. 35, S27)
- Engine and notices: `test_mexico_engine_imss_ceav_infonavit.py`, `test_mexico_infonavit_notices.py`
- INFONAVIT report, NOT AN OFFICIAL FILE (`test_mexico_report_generators.py`)
- Super Admin read-only views (W5-1): Compliance → Mexico → Statutory rules, and each content tab, show every value with its source file, SHA-256, verification status and [PENDING G1]; readiness per gate (W5-3) shows which checklist items code confirms now. Browser evidence: `docs/mexico/completion-evidence/w5/` (39/39 PASS)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- [PRE-PILOT] The 5% employer contribution transcribed from S27, in an Approved pack — code check `national_pack_approved`

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PILOT-GENERATED] Credit notices (retention, suspension, modification) of the pilot's real workers applied, and reconciled against INFONAVIT's own figures
- [GO-LIVE CHECK] The first INFONAVIT liability filed and paid through SUA / SIPARE (activation runbook §6; the pilot never files)
- The G3 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- D-01; gap register B9 (fixed-amount credit basis, BLOCKED-ON-SOURCE), INFONAVIT partial-period proration (BLOCKED-ON-SOURCE)

Source of the checklist: `docs/mexico/release-gates/G3/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
