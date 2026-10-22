# Mexico release gate G7 — Security / privacy

**Definition (spec §22).** Certificates / secrets, personal identifiers, 2025 privacy-law controls and restore procedures signed.

**Evidence tag.** `MX-GATE-G7`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- S23 (DOF — 2025 Federal Personal Data Protection Law)
- S31 (RENAPO — CURP)
- S32 (IMSS — NSS)
- S33 (Banxico / ABM — CLABE)

## Evidence checklist

- [ ] CSD and PAC credentials held only as secret references; rotation procedure tested
- [ ] RFC / CURP / NSS / CLABE and CFDI XML masked in logs and error reports (Phase 10c, reviewed by the ZP-PRIV owner)
- [ ] Legal decisions recorded: retention periods per category (MX-D-RETENTION-PERIOD), deletion vs anonymisation (MX-D-RETENTION-END), hosting and cross-border transfers (MX-D-HOSTING)
- [ ] Privacy notice (aviso de privacidad) and processor terms in place
- [ ] Backup and restore procedure tested for a Mexican tenant

## What Zoiko already provides

ZP-PRIV, Phase 10c (redaction, retention categories, legal holds).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
