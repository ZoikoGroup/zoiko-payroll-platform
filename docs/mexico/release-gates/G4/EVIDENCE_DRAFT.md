# Mexico release gate G4 — State ISN — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G4 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G4` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- `docs/mexico/sources/SOURCES_MANIFEST.csv` (33 rows on 2026-10-27: 31 `ARCHIVE_COPY_VERIFIED`, 1 `VERIFIED` (S22), 1 `WRONG_VERSION`) and `docs/mexico/sources/VERIFICATION_LOG.csv` (1 `MATCH`: S22)
- `docs/mexico/MEXICO_PHASE_1_TRANSCRIPTION_LOG.md` (every transcribed row with its source, page and the blind second transcription), and `python -m scripts.verify_mexico_sources compare` (every number and every quoted rule wording found in its cited file)
- CDMX: the 4% rate (S22 Art. 158, VERIFIED) and the special-pay inclusions (Arts. 156–157) [PENDING G1]; the CDMX filing day (Art. 159)
- Engine and returns: `test_mexico_engine_isn_labor.py`, `test_mexico_isn_registrations.py`, `test_mexico_authorities_sua_isn.py`; payroll BLOCKED in every state without an Active pack (readiness code check `unsupported_states_blocked`)
- ISN return generator for CDMX, NOT AN OFFICIAL FILE (`test_mexico_report_generators.py`)
- Super Admin read-only views (W5-1): Compliance → Mexico → Statutory rules, and each content tab, show every value with its source file, SHA-256, verification status and [PENDING G1]; readiness per gate (W5-3) shows which checklist items code confirms now. Browser evidence: `docs/mexico/completion-evidence/w5/` (39/39 PASS)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- [PRE-PILOT] For each state to be enabled: base, rate, exemptions and return rules transcribed from that state's saved code, in an Approved state pack — code check `isn_pack_approved`
- [PRE-PILOT] Proof that a worker in any state without an Approved pack is blocked — code check `unsupported_states_blocked`
- [PRE-PILOT] CDMX ISN on vacation paid out at termination, the separation payment and the indemnity (D-06): decided and transcribed, or a CDMX finiquito with those lines stays blocked — code check `isn_d06`

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PRE-PILOT] A synthetic ISN return per enabled state drafted and reconciled employee → return → ledger
- [PRE-PILOT] CDMX 2026 micro / small-employer ISN benefit (DECISIONS_PENDING D-10, recorded 2026-10-26). S22, decree of 19-12-2025, Transitorio TRIGÉSIMO SÉPTIMO (PDF p. 815) gives micro employers a benefit "equivalente al 1%" and small employers "al 0.5% respecto de la tasa", under SAF general rules that are not saved. The CDMX pack carries 4% for every employer. Decide the reading, save the SAF rules, and model the benefit (or confirm no pilot employer qualifies) before sign-off
- [GO-LIVE CHECK] The first real ISN return filed and accepted, per enabled state (activation runbook §6)
- The G4 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- D-06 (CDMX ISN on vacation paid out, separation payment, indemnity), D-10 (CDMX micro / small-employer benefit); every other state: no pack

Source of the checklist: `docs/mexico/release-gates/G4/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
