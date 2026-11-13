# Belgium coverage matrix (ZP-BE-ENG-001 BE-001 .. BE-040, gates G1–G7)

Status at the end of Block C (2026-11-13, branch nikhil, local commits only).

- **IMPLEMENTED**: the behaviour is built and proven by tests; it needs no further statutory input.
- **BLOCKED-BY-CONTENT**: the mechanism is built and tested with SYNTHETIC content; it produces a
  production result only after the Belgian specialist signs the content (gate G1). Until then it blocks
  with a named reason — it never estimates.
- **BLOCKED-BY-EXTERNAL**: built and tested, but production use needs something outside the codebase
  (authority schemas / mappings / codes, a certified channel, ONSS rate files).

Test files are under `backend/tests/`.

| ID | Requirement (short) | Status | Proven by |
|----|---------------------|--------|-----------|
| BE-001 | Country package: legal employer, establishment, ONSS category | IMPLEMENTED | test_belgium_scaffold.py, test_belgium_setup.py |
| BE-002 | Worker category separate from contract | BLOCKED-BY-CONTENT (supported categories / contract types signed) | test_belgium_applicability.py, test_belgium_block_b_migration.py |
| BE-003 | Joint Committee and employment line effective-dated | IMPLEMENTED | test_belgium_setup.py, test_belgium_applicability.py |
| BE-004 | Salaried and hourly first; special regimes blocked | BLOCKED-BY-CONTENT (pay bases / frequencies signed) | test_belgium_applicability.py, test_belgium_content.py |
| BE-005 | Calculation readiness separate from declaration / payment | IMPLEMENTED | test_belgium_run_lifecycle.py, test_belgium_filing.py |
| BE-006 | Earning classification per obligation | BLOCKED-BY-CONTENT (every class seeded REVIEW) | test_belgium_engine.py, test_belgium_super_admin.py |
| BE-007 | Separate bases per obligation | BLOCKED-BY-CONTENT (base rules signed) | test_belgium_engine.py |
| BE-008 | BIK, reimbursements, vouchers as governed types | BLOCKED-BY-CONTENT (G-15) | test_belgium_engine.py |
| BE-009 | Source period vs payment date | IMPLEMENTED | test_belgium_engine.py, test_belgium_migrations.py, test_belgium_filing.py (DmfA source quarter) |
| BE-010 | Annex III as signed effective-dated content | BLOCKED-BY-CONTENT (Annex III scale) | test_belgium_engine.py, test_belgium_formula.py |
| BE-011 | Regular vs exceptional withholding | BLOCKED-BY-CONTENT | test_belgium_engine.py |
| BE-012 | Social and fiscal work bonus independent | BLOCKED-BY-CONTENT | test_belgium_engine.py |
| BE-013 | Withholding cadence from the employer / calendar, never assumed | BLOCKED-BY-CONTENT (calendar rows G-32; frequency set G-30) | test_belgium_filing.py |
| BE-014 | Belcotax 281.10 with correction / cancellation lineage | BLOCKED-BY-EXTERNAL (schema, mapping, box codes G-31/G-33) | test_belgium_filing.py |
| BE-015 | ONSS rate files with version / quarter / checksum | BLOCKED-BY-EXTERNAL (ONSS rate files, G-08) | test_belgium_content.py, test_belgium_slab_rows.py |
| BE-016 | 108% base for manual workers only | BLOCKED-BY-CONTENT | test_belgium_engine.py |
| BE-017 | Worker / line / employer accumulators separate | IMPLEMENTED | test_belgium_migrations.py, test_belgium_run_lifecycle.py |
| BE-018 | Advance payments as a separate schedule | IMPLEMENTED (amounts come from the ONSS notice) | test_belgium_filing.py |
| BE-019 | Contribution composition, no "final all-in" claim | IMPLEMENTED | test_belgium_content.py, test_belgium_engine.py |
| BE-020 | Joint Committee / function mandatory where relevant | IMPLEMENTED | test_belgium_wages_working_time.py, test_belgium_applicability.py |
| BE-021 | Sector wage tables / indexation versioned | BLOCKED-BY-CONTENT (wage scales per committee) | test_belgium_wages_working_time.py |
| BE-022 | Effective / average regimes, compensatory rest | BLOCKED-BY-CONTENT (working-time limits) | test_belgium_wages_working_time.py |
| BE-023 | Public holidays and substitute days as content | BLOCKED-BY-CONTENT (holiday rows G-09) | test_belgium_wages_working_time.py |
| BE-024 | Holiday service year vs taking year | IMPLEMENTED | test_belgium_holiday_absence.py, test_belgium_content.py |
| BE-025 | Separate employee / manual-worker holiday strategies | BLOCKED-BY-CONTENT | test_belgium_holiday_absence.py |
| BE-026 | Additional holidays and offset | BLOCKED-BY-CONTENT | test_belgium_holiday_absence.py |
| BE-027 | Holiday certificates as immutable evidence | IMPLEMENTED | test_belgium_holiday_absence.py, test_belgium_block_b_migration.py |
| BE-028 | RMMMG / sector minimum never substitutes holiday pay | IMPLEMENTED | test_belgium_holiday_absence.py |
| BE-029 | Incapacity episodes with day bands | BLOCKED-BY-CONTENT (day bands G-07) | test_belgium_holiday_absence.py |
| BE-030 | Eight-week 2026 relapse rule | BLOCKED-BY-CONTENT (relapse window signed) | test_belgium_holiday_absence.py |
| BE-031 | External allowance never added to net | IMPLEMENTED | test_belgium_holiday_absence.py |
| BE-032 | CBA / employer top-ups as overlays | BLOCKED-BY-CONTENT | test_belgium_holiday_absence.py |
| BE-033 | Dimona event service; no payroll without it | BLOCKED-BY-EXTERNAL (Dimona schema / mapping, G3 channel) | test_belgium_filing.py, test_belgium_run_lifecycle.py |
| BE-034 | DmfA quarter- and schema-versioned | BLOCKED-BY-EXTERNAL (DmfA XSD, mapping, codes) | test_belgium_filing.py, test_belgium_block_c_migration.py |
| BE-035 | Authority calendar separate from formulas | BLOCKED-BY-CONTENT (calendar rows G-32) | test_belgium_filing.py |
| BE-036 | Acceptance separate from settlement | IMPLEMENTED | test_belgium_filing.py, test_belgium_block_c_migration.py |
| BE-037 | Payload hash, rendition, response, actor / mandate | IMPLEMENTED | test_belgium_filing.py |
| BE-038 | Legal-employer / line scope in storage and filings | IMPLEMENTED | test_belgium_setup.py, test_belgium_filing.py |
| BE-039 | Content decisions with source, interval, approval | IMPLEMENTED | test_belgium_super_admin.py, test_belgium_slab_rows.py |
| BE-040 | PII out of logs, metrics, idempotency keys | IMPLEMENTED | test_belgium_identifiers.py, test_belgium_filing.py, test_belgium_parallel_golden_readiness.py |

Totals: IMPLEMENTED 17, BLOCKED-BY-CONTENT 19, BLOCKED-BY-EXTERNAL 4.

## Release gates — evidence still needed

| Gate | Computed today | Still needed |
|------|----------------|--------------|
| G1 Statutory content | red | the specialist signs every pack row (Annex III, ONSS, wages, holiday, absence, schema registry, tolerances); authority examples with replayable cases; a PASS certification run |
| G2 Sector coverage | red | launch employers named in `BE_CANARY_ORG_IDS`; certified Joint Committee agreements with wage scales for every employment line |
| G3 Connectivity | red | a certified Dimona / DmfA channel (adapter; D9), archived XSDs + payload mappings (G-31), FinProf / Belcotax specifications and credentials; `BE-CONNECTIVITY-*` evidence |
| G4 Payroll accuracy | red | two accepted parallel cycles in distinct months per launch employer, against an independent Belgian payroll |
| G5 Filing and settlement | red | accepted Dimona and DmfA and a reconciled obligation for launch employers; `BE-FILING-E2E` (incl. outage / retry) |
| G6 Security / privacy | red | identifier keys configured in production; `BE-SIGNOFF-SECURITY`, `BE-SIGNOFF-PRIVACY` (DPIA); retention decision G-21 |
| G7 Ownership | red | `BE-OWNER-CONTENT`, `-PAYROLL-OPS`, `-INCIDENT`, `-CHANGE-CALENDAR`, `-SPECIALIST` |
