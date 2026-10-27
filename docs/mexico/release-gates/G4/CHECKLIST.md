# Mexico release gate G4 — State ISN

**Definition (spec §22).** Each enabled work state has signed current base / rate / exemption / return content; unsupported states are hard-blocked.

**Evidence tag.** `MX-GATE-G4`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PRE-PILOT.** Signed **before** a pilot grant (D2). Returns are drafted and reconciled with synthetic data; the real first filing is a go-live check.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- S22 (Mexico City Fiscal Code 2026). The saved file is the WRONG VERSION (2022 text, 3%, vs the spec's 4%); the current consolidated text is still needed
- Every other state: no source is in the register yet. A state stays blocked until its code is saved

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PRE-PILOT]** For each state to be enabled: base, rate, exemptions and return rules transcribed from that state's saved code, in an Approved state pack
- [ ] **[PRE-PILOT]** A synthetic ISN return per enabled state drafted and reconciled employee → return → ledger
- [ ] **[PRE-PILOT]** Proof that a worker in any state without an Approved pack is blocked
- [ ] **[PRE-PILOT]** **CDMX 2026 micro / small-employer ISN benefit (DECISIONS_PENDING D-10, recorded 2026-10-26).** S22, decree of 19-12-2025, Transitorio TRIGÉSIMO SÉPTIMO (PDF p. 815) gives micro employers a benefit "equivalente al 1%" and small employers "al 0.5% respecto de la tasa", under SAF general rules that are not saved. The CDMX pack carries 4% for every employer. Decide the reading, save the SAF rules, and model the benefit (or confirm no pilot employer qualifies) before sign-off
- [ ] **[PRE-PILOT]** CDMX ISN on vacation paid out at termination, the separation payment and the indemnity (D-06): decided and transcribed, or a CDMX finiquito with those lines stays blocked
- [ ] **[GO-LIVE CHECK]** The first real ISN return filed and accepted, per enabled state (activation runbook §6)

## What Zoiko already provides

Phases 2, 6, 8 (ISN state packs, ISN ledger and returns).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
