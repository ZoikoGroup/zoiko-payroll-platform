# Mexico release gate G6 — External operations

**Definition (spec §22).** PAC, SAT payment, IDSE / SUA / SIPARE, INFONAVIT and bank workflows have unknown / reject / recovery paths.

**Evidence tag.** `MX-GATE-G6`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- The PAC's API documentation
- The employer bank's SPEI bulk-file specification (not saved — payments are a worklist until then)

## Evidence checklist

- [ ] Each channel exercised end to end in a test environment, including a REJECT and an UNKNOWN case, resolved by the runbook (docs/mexico/MEXICO_UNKNOWN_STATE_RUNBOOK.md)
- [ ] A database restore drill: in-flight CFDI actions moved to UNKNOWN and reconciled
- [ ] Salary payments: a batch released by a second person, settled, one returned and re-issued
- [ ] The payroll journal exported and imported into the employer's accounting system

## What Zoiko already provides

Phases 7, 8, 10a, 10b (PAC outbox, authority lifecycle, payments, journal) and the UNKNOWN runbook (10c).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
