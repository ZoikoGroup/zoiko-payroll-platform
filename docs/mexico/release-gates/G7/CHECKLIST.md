# Mexico release gate G7 — Security / privacy

**Definition (spec §22).** Certificates / secrets, personal identifiers, 2025 privacy-law controls and restore procedures signed.

**Evidence tag.** `MX-GATE-G7`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PRE-PILOT.** Signed **before** a pilot grant (D2): real Mexican personal data enters for the first time in the pilot, so the privacy controls, Q9 and the hosting decision come first.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- S23 (DOF — 2025 Federal Personal Data Protection Law)
- S31 (RENAPO — CURP)
- S32 (IMSS — NSS)
- S33 (Banxico / ABM — CLABE)

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PRE-PILOT]** CSD and PAC credentials held only as secret references; rotation procedure tested
- [ ] **[PRE-PILOT]** RFC / CURP / NSS / CLABE and CFDI XML masked in logs and error reports (Phase 10c, reviewed by the ZP-PRIV owner)
- [ ] **[PRE-PILOT]** Q9 (identifiers at rest) recorded by the security lead (`MX-DECISION-Q9`)
- [ ] **[PRE-PILOT]** Hosting and cross-border transfers recorded (`MX-DECISION-HOSTING`); the pilot organisation's data region set accordingly (organisations default to EU)
- [ ] **[PRE-PILOT]** Retention decisions recorded (`MX-DECISION-RETENTION-PERIOD`, `MX-DECISION-RETENTION-END`) or explicitly deferred past the pilot
- [ ] **[PRE-PILOT]** Privacy notice (aviso de privacidad) and processor terms in place
- [ ] **[PRE-PILOT]** Backup and restore procedure tested for a Mexican tenant

## What Zoiko already provides

ZP-PRIV, Phase 10c (redaction, retention categories, legal holds).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
