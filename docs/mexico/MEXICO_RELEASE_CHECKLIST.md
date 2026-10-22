# Mexico — release checklist

**For:** the release owner. Every item must be checked, with a reference, before step 4 of `MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md`.

## Gates (spec §22)

- [ ] G1 ISR / CFDI signed
- [ ] G2 IMSS / SUA signed
- [ ] G3 INFONAVIT signed
- [ ] G4 State ISN signed (list the enabled states: ____)
- [ ] G5 Labor signed
- [ ] G6 External operations signed
- [ ] G7 Security / privacy signed
- [ ] G8 Parallel payroll signed

## Legal decisions (open today)

- [ ] Retention period per record category (`MX-DECISION-RETENTION-PERIOD`), then a period approved per category
- [ ] Deletion vs anonymisation at end of retention (`MX-DECISION-RETENTION-END`)
- [ ] **Hosting and cross-border transfers under the 2025 privacy law** (`MX-DECISION-HOSTING`, plan D9). Where Mexican personal data is hosted and which transfers need consent or contract clauses.
- [ ] Privacy notice (aviso de privacidad) and processor terms

## Platform (ZP-PRIV) review — Rugvedh

- [ ] Phase 10c redaction rules reviewed (`app/core/redaction.py`: RFC, CURP and CFDI XML patterns; the new sensitive keys)
- [ ] Any retention purge consults `retention_service.purge_refusal` before deleting a jurisdiction's records (`governance.retention_candidates` does not today; no purge script exists)
- [ ] The deploy workflow deploys production only from `main` (it also deploys on push to `rugvedh`)
- [ ] Post-deploy privacy smoke test configured (its secrets are not set, HP-10)
- [ ] HKID value pattern: optional trailing word boundary (it partly masks IMSS employer numbers; harmless)

## External

- [ ] PAC contracted; credentials and CSDs as secret references
- [ ] Employer bank's SPEI bulk-file specification, or the worklist mode accepted in writing
- [ ] Settlement confirmation (Banxico CEP) process agreed (no integration)

## Engineering

- [ ] `MX_IDENTITY_TOKEN_KEY` in Secret Manager
- [ ] Production database at the release's single alembic head; `alembic current` confirmed on the server
- [ ] The flaky test `test_deactivate_organization_response_precedes_email_send` fixed or quarantined, so CI is reliable
- [ ] Phase 10e built and deployed: the flag alone never opens Mexico. General availability needs the registry AVAILABLE (G1–G8 SIGNED, Q9 RECORDED, `MX_IDENTITY_TOKEN_KEY` configured); a non-binding pilot for named organisations runs the G8 cycles (decided 2026-10-22; plan `MEXICO_PHASE_10E_PLAN.md`, awaiting approval)
- [ ] Q9 (identifiers at rest) recorded by the security lead (`MX-DECISION-Q9`)
