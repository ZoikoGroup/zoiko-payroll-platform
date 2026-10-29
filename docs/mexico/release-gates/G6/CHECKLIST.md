# Mexico release gate G6 — External operations

**Definition (spec §22).** PAC, SAT payment, IDSE / SUA / SIPARE, INFONAVIT and bank workflows have unknown / reject / recovery paths.

**Evidence tag.** `MX-GATE-G6`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PILOT-GENERATED.** Signed **during** the pilot (D2). The PAC sandbox and the journal import are produced in the pilot; the restore drill and the Zoiko-side authority and bank lifecycles are produced before it, on staging with synthetic objects. Real filings and payments are go-live checks.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- The PAC's API documentation
- The employer bank's SPEI bulk-file specification (not saved — payments are a worklist until then)

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PILOT-GENERATED]** PAC sandbox end to end from pilot runs, including a REJECT and an UNKNOWN case resolved by the runbook (docs/mexico/MEXICO_UNKNOWN_STATE_RUNBOOK.md)
- [ ] **[PRE-PILOT]** IDSE, SUA / SIPARE, SAT and INFONAVIT lifecycles on staging with synthetic objects: a REJECT and an UNKNOWN case each, resolved by the runbook
- [ ] **[PRE-PILOT]** A database restore drill on staging: in-flight CFDI actions moved to UNKNOWN and reconciled
- [ ] **[PRE-PILOT]** Salary payments on staging with synthetic data: a batch released by a second person, settled, one returned and re-issued
- [ ] **[PILOT-GENERATED]** The pilot's payroll journal exported and imported into the employer's accounting system
- [ ] **[GO-LIVE CHECK]** The first real SAT declaration, IMSS / INFONAVIT payment and salary payment, each resolved to a final outcome (activation runbook §6)

## What Zoiko already provides

Phases 7, 8, 10a, 10b (PAC outbox, authority lifecycle, payments, journal) and the UNKNOWN runbook (10c).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
