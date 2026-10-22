# Mexico release gate G8 — Parallel payroll

**Definition (spec §22).** At least two consecutive payroll cycles plus one IMSS / INFONAVIT and one tax-period reconciliation show zero unexplained material differences.

**Evidence tag.** `MX-GATE-G8`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- The employer's current payroll provider's output for the same periods

## Evidence checklist

- [ ] Two consecutive cycles run in Zoiko in parallel with the current provider; every difference explained
- [ ] One IMSS / INFONAVIT bimester reconciled (SUA) and one ISR tax period (declaration) reconciled
- [ ] Sign-off by the employer's payroll owner and by Zoiko

## What Zoiko already provides

Every phase. Run in an EVALUATION workspace only.

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
