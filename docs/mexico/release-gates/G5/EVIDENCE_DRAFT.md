# Mexico release gate G5 — Labor — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G5 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G5` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- `docs/mexico/sources/SOURCES_MANIFEST.csv` (33 rows on 2026-10-27: 31 `ARCHIVE_COPY_VERIFIED`, 1 `VERIFIED` (S22), 1 `WRONG_VERSION`) and `docs/mexico/sources/VERIFICATION_LOG.csv` (1 `MATCH`: S22)
- `docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md` (every transcribed row with its source, page and the blind second transcription), and `python -m scripts.verify_mexico_sources compare` (every number and every quoted rule wording found in its cited file)
- Content transcribed [PENDING G1]: minimum wages (two zones, 61 professions, 45 ZLFN municipalities), the 2026 workweek and overtime tiers, vacations and the vacation premium, aguinaldo (LFT Art. 87), termination reasons and the finiquito, PTU and its exclusions, rest-day work, working-day lengths (LFT Art. 61)
- Engine and services: `test_mexico_engine_isn_labor.py`, `test_mexico_labor_policy.py`, `test_mexico_benefits.py`, `test_mexico_termination.py`, `test_mexico_ptu.py`, `test_mexico_rules.py`
- Aguinaldo, finiquito, vacation-accrual and PTU reports (`test_mexico_report_generators.py`)
- Super Admin read-only views (W5-1): Compliance → Mexico → Statutory rules, and each content tab, show every value with its source file, SHA-256, verification status and [PENDING G1]; readiness per gate (W5-3) shows which checklist items code confirms now. Browser evidence: `docs/mexico/completion-evidence/w5/` (39/39 PASS)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- [PRE-PILOT] Minimum wage zones and professional minimums, the 2026 workweek and overtime rules, vacations and the vacation premium, aguinaldo and PTU transcribed from S8, S9, S17, S18, S21 and S26 — code check `national_pack_approved`
- [PRE-PILOT] Golden cases for overtime (double / triple), Sunday premium, rest days, vacations, aguinaldo, PTU and finiquito — code check `golden_pass`

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PRE-PILOT] Each employer's labour policy passes its floor check (from its policy documents; re-confirmed in the pilot)
- [PRE-PILOT] PTU trusted-worker salary cap (LFT Art. 127 II), recorded 2026-10-26 (W1-4). The PTU rule cannot apply it: the engine knows neither who is a trusted worker nor the highest unionised salary. Before a pilot PTU cycle, the employer confirms that no trusted worker exceeds that cap, or the cap is modelled
- The G5 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- D-01, D-11, D-12, D-13, D-14 (PTU cap), D-17 (hourly rate — blocks every overtime line), D-19; the trusted-worker PTU cap (LFT Art. 127 II)

Source of the checklist: `docs/mexico/release-gates/G5/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
