# Mexico release gate G2 — IMSS / SUA

**Definition (spec §22).** SBC and every launch IMSS branch including 2026 CEAV reconcile to current SUA on signed cases.

**Evidence tag.** `MX-GATE-G2`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PRE-PILOT.** Signed **before** a pilot grant (D2). The SUA cases are synthetic workers computed in the SUA program; the real first IDSE filing is a go-live check, not gate evidence (the pilot never files).

**State today.** OPEN. Nothing is signed.

## Sources it needs

- S6 (INEGI — UMA 2026)
- S10 (IMSS — Social Security Law)
- S11 (2020 pension-reform decree: CEAV)
- S12 (IMSS — SUA)
- S13 (IMSS — affiliation movements)
- S14 (IMSS — work-risk premium)
- S29 (RACERF — risk premium window)

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PRE-PILOT]** Every IMSS branch rate, ceiling and the 2026 CEAV band transcribed, in an Approved pack <!-- code: national_pack_approved -->
- [ ] **[PRE-PILOT]** Signed cases with synthetic workers: SBC (fixed, variable, mixed) and each branch per worker reconcile to the same cases computed in the SUA program, with zero difference (Phase 8 SUA reconciliation)
- [ ] **[PRE-PILOT]** An approved work-risk premium with its validity window from S29, from the employer's own IMSS determination
- [ ] **[PRE-PILOT]** IDSE movements (alta, baja, modificación) for synthetic workers: the worklist matches IDSE's capture fields
- [ ] **[GO-LIVE CHECK]** The first real IDSE filing, accepted (activation runbook §6; not gate evidence)

## What Zoiko already provides

Phases 3, 6, 8 (SBC, branch ledger, IMSS movements, SUA reconciliation).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
