# Belgium authority onboarding (ZP-BE-ENG-001)

Audience: the integration lead, payroll operations and the Belgian payroll specialist. This lists everything
the platform needs from or about the Belgian authorities (ONSS / RSZ and SPF Finance / FOD Financiën) before
Belgian payroll can go live, with the owner role and the release gate each item unblocks. Engineering for
all of it is built and tested with synthetic content; none of it can be produced from code.

## 1. Authority schemas and payload mappings (G-31, part of G-08) — owner: Integration lead + Belgian specialist — unblocks G3 (and G5)

| Form | Needed | Where it goes | Today |
|------|--------|---------------|-------|
| Dimona (IN / OUT / UPDATE / CANCEL) | the current XSD per version, archived as a reviewed source (file + SHA-256); the version name and submission window | `be_filing_dimona_schema_versions` row (Filing schema versions sheet) with that source | every Dimona stays DRAFT: "schema version content pending" |
| DmfA (quarterly) | XSD per version; the spec proposes 2026/2 until 30 Sep 2026 and 2026/3 from 1 Oct 2026 (to be confirmed and signed) | `be_filing_dmfa_schema_versions` | DRAFT |
| FinProf (withholding) | current technical specification / XSD | `be_filing_finprof_schema_versions` | DRAFT |
| Belcotax 281.10 | income-year XSD | `be_filing_belcotax_schema_versions` | DRAFT |
| All four | the mapping of the canonical Zoiko payload onto each schema version (a reviewed engineering task once the XSD is archived; registered in `belgium_filing.RENDERERS`) | code review + tests per version | "no mapping of the canonical payload" |

A filing is VALIDATED only when the schema of its SUBMISSION date is signed, archived and mapped and the
rendered XML passes the XSD; approval and recorded submission re-check the schema of their own date.

## 2. Authority codes (G-33, G-08) — owner: Belgian specialist — unblocks G1 / G3

- DmfA worker codes, remuneration codes, contribution codes, working-time codes per employment line.
- FinProf nature-of-income / declaration codes.
- Belcotax 281.10 box codes.
- ONSS quarterly rate files (TechLib XML) with their source version, quarter and checksum (BE-015); the
  supported employer categories and worker codes signed as code lists, and the employer base / fund rates as
  band rows per EC x WC.

Payloads carry `"coding": "PENDING_CONTENT"` until these are signed.

## 3. Channel certification and credentials (gate G3, decision D9) — owner: Integration lead + Security — unblocks G3

- A certified channel for Dimona and DmfA (ONSS web services / batch channel), with test submissions accepted
  against the approved schema. Until then the only adapter refuses (`BE_TRANSMISSION_NOT_CERTIFIED`) and
  submissions are made in the authority portal and recorded by hand.
- FinProf and Belcotax-on-web operational specifications and credentials for the contracted scope.
- Credentials live only in the managed secret store (never in configuration or the repository); rotation and
  environment separation documented (spec §15).
- Evidence: `BE-CONNECTIVITY-DIMONA`, `BE-CONNECTIVITY-DMFA`, `BE-CONNECTIVITY-FINPROF`,
  `BE-CONNECTIVITY-BELCOTAX` (reviewed source artifacts).

## 4. Mandates — owner: Payroll operations + each launch employer — unblocks G3 / G5

- Each launch employer's mandate for Zoiko (or its service provider) to declare on its behalf with ONSS and
  SPF Finance; the mandate REFERENCE is recorded on the employer registration and on every recorded submission
  (`mandateRef`, BE-037). No mandate secret is stored.
- The employer ONSS number (vault, masked) and enterprise number on the registration; the withholding
  declaration frequency (G-30); the 1.60% special-contribution status with evidence (G-25); the holiday-fund
  reference for manual workers.

## 5. Calendar rows with sources (G-32, BE-035) — owner: Payroll operations — unblocks G5

- Enter every operational deadline as a calendar row (Calendar rows sheet or the filing calendar): report
  types `BE_DMFA` (quarters YYYYQn), `BE_FINPROF` (YYYY-MM or YYYYQn per frequency), `BE_BELCOTAX` (YYYY),
  `BE_ONSS_ADVANCE` (YYYY-MM), `BE_HOLIDAY_FUND`; each with its published source; imported rows are Draft and a
  Super Admin activates them. Only Active, sourced rows are used: the spec's 2026/Q3 DmfA operational date
  (30 Oct 2026) must be entered this way — the platform never assumes a date.

## 6. End-to-end evidence — owner: Integration + Payroll operations — unblocks G5

- With the canary employers: an accepted Dimona IN and OUT, an accepted DmfA quarter (and a correction), a
  FinProf period, a Belcotax batch; payments recorded and obligations reconciled; a rejection handled; an outage
  / retry exercised. Evidence tag `BE-FILING-E2E`.

## Summary

| Item | Owner | Gate |
|------|-------|------|
| Archived XSDs + payload mappings (Dimona, DmfA, FinProf, Belcotax) | Integration + specialist | G3 |
| DmfA / FinProf / Belcotax codes, ONSS rate files | Specialist | G1 / G3 |
| Certified channel + credentials | Integration + Security | G3 |
| Mandates per launch employer | Payroll ops + employers | G3 / G5 |
| Calendar rows with sources | Payroll ops | G5 |
| End-to-end filing evidence | Integration + Payroll ops | G5 |
