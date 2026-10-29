# Mexico release gate G8 — Parallel payroll

**Definition (spec §22).** At least two consecutive payroll cycles plus one IMSS / INFONAVIT and one tax-period reconciliation show zero unexplained material differences.

**Evidence tag.** `MX-GATE-G8`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PILOT-GENERATED.** Signed **after** the pilot: G8 *is* the pilot's parallel payroll.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- The employer's current payroll provider's output for the same periods

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PILOT-GENERATED]** Two consecutive cycles run in the pilot organisation in parallel with the current provider; every difference explained
- [ ] **[PILOT-GENERATED]** One IMSS / INFONAVIT bimester reconciled (SUA figures entered and compared) and one ISR tax period reconciled
- [ ] **[PILOT-GENERATED]** Sign-off by the employer's payroll owner and by Zoiko

## What Zoiko already provides

Every phase. Run in an EVALUATION workspace only.

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
