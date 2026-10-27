# Mexico release gate G3 — INFONAVIT

**Definition (spec §22).** 5% employer contribution and credit-withholding / reconciliation flow proven.

**Evidence tag.** `MX-GATE-G3`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PILOT-GENERATED.** Signed **during** the pilot, so it is **not** required for a pilot grant (D2 adjusted). The credit reconciliation needs INFONAVIT's own figures for real workers with real credits, which exist only once real employer data is in the pilot.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- S27 (Ley del INFONAVIT Art. 29, primary)
- S15 (INFONAVIT — employer contribution, cross-check)
- S16 (INFONAVIT — SUA)

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PRE-PILOT]** The 5% employer contribution transcribed from S27, in an Approved pack <!-- code: national_pack_approved -->
- [ ] **[PILOT-GENERATED]** Credit notices (retention, suspension, modification) of the pilot's real workers applied, and reconciled against INFONAVIT's own figures
- [ ] **[GO-LIVE CHECK]** The first INFONAVIT liability filed and paid through SUA / SIPARE (activation runbook §6; the pilot never files)

## What Zoiko already provides

Phases 6, 8 (housing contribution, credit notices, INFONAVIT liability).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
