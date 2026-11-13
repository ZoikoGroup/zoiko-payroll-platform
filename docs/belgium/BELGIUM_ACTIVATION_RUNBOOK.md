# Belgium activation runbook (ZP-BE-ENG-001 §15 / §17)

Audience: payroll operations, the Belgian statutory-content owner, platform engineering on call.
Engineering completion is not production authorisation: Belgian payroll stays dormant until every
release gate G1–G7 is green for the legal-employer scope being activated.

## 0. Where the gates are read

- Super Admin › Compliance › Belgium › Overview shows G1–G7 with every failing check
  (computed by `belgium_readiness.be_readiness`; API `GET /api/super-admin/compliance/belgium/readiness`).
- `service_registry_transition` refuses PLANNED → AVAILABLE while any gate is red or a
  launch-blocking owner decision is open (the refusal is audited).
- A Belgian pack can be activated only when every row is signed, the authority examples replay exactly
  and the latest Belgian golden-vector certification run is PASS (`belgium_golden`).

Evidence tags (a reviewed source artefact, uploader ≠ reviewer, with a file):

| Gate | Evidence / data the gate reads |
|------|--------------------------------|
| G1 | Signed Active pack; authority examples with replayable cases; certification run PASS |
| G2 | `BE_CANARY_ORG_IDS` names the launch employers; their employment lines carry a Joint Committee and an Active agreement with wage scales; no special regime |
| G3 | A certified transmission adapter (none today, D9); signed + archived schema per form; `BE-CONNECTIVITY-DIMONA`, `-DMFA`, `-FINPROF`, `-BELCOTAX` |
| G4 | Two accepted parallel cycles (distinct pay months) per launch employer |
| G5 | Accepted Dimona and DmfA, a reconciled obligation for launch employers; `BE-FILING-E2E` (incl. outage / retry) |
| G6 | `BE_IDENTIFIER_KEYRING`, `BE_IDENTIFIER_FINGERPRINT_KEY`; `BE-SIGNOFF-SECURITY`, `BE-SIGNOFF-PRIVACY`; owner decision G-21 (retention) |
| G7 | `BE-OWNER-CONTENT`, `BE-OWNER-PAYROLL-OPS`, `BE-OWNER-INCIDENT`, `BE-OWNER-CHANGE-CALENDAR`, `BE-OWNER-SPECIALIST` |

## 1. Canary

1. Name the launch design partners: set `BE_CANARY_ORG_IDS` (comma-separated organisation ids) in the
   environment. Leave `BE_TENANT_ONBOARDING_ENABLED=false`. Only the listed organisations reach the
   Belgium API (every other one gets 404).
2. With the canary organisations, run at least two representative payroll cycles in parallel with an
   independent Belgian payroll (Compliance › Belgium › Parallel cycles). Every difference is explained and
   accepted by a second person; each cycle is accepted by someone other than its importer.
3. Enter the authority calendar rows (Super Admin › filing calendar; report types `BE_DMFA`,
   `BE_FINPROF`, `BE_BELCOTAX`, `BE_ONSS_ADVANCE`, `BE_HOLIDAY_FUND`) with their source, and activate them.
4. Run Dimona, DmfA, FinProf and Belcotax end to end for the canary employers through the authority
   channel once G3 is certified, recording the receipts.
5. When the Overview shows G1–G7 green and no launch-blocking decision is open, move the Belgium
   registry row PLANNED → AVAILABLE (Super Admin; reason required; audited).

## 2. Opening registration (manual, after the gates are green)

Belgium is **not** in `REGISTRATION_COUNTRIES` (`backend/app/core/jurisdiction.py`). Adding `"BE"` there is
a separate, reviewed code change made only after step 1.5, through the normal pull request and the
CI PostgreSQL / Python 3.12 / frontend-build gates. It is not part of the Belgium blocks.

After that change: set `BE_TENANT_ONBOARDING_ENABLED=true` only when every customer organisation may onboard;
until then keep using `BE_CANARY_ORG_IDS`.

## 3. Rollback

1. Move the Belgium registry row back to PLANNED (Super Admin; reason; audited).
2. Set `BE_TENANT_ONBOARDING_ENABLED=false` and remove the organisation from `BE_CANARY_ORG_IDS` (the
   Belgium API answers 404 again; stored records are untouched).
3. If a pack is at fault, supersede it with a corrected Draft pack signed again (never edit an Active row).
4. Committed payroll is never rewritten: corrections go through `POST /payslips/{id}/corrections` and the
   ledger's CORRECTION entries; filings already transmitted are corrected by a linked CORRECTION filing.
5. No migration downgrade is needed to roll back (all Belgium tables are additive); a downgrade of
   `8a1f5ef9fa5d` drops only the five Block C tables and is reserved for a failed deploy before any use.

## 4. Incident categories (spec §15)

| Category | Typical signal | First action | Blocks |
|----------|----------------|--------------|--------|
| Calculation defect | parallel-run difference, payslip exception, golden FAIL | stop approvals for the affected runs; certification run; correction runs | payroll |
| Content defect | wrong signed value, wrong schema-version window | supersede the pack / row with a signed correction; re-run golden certification | payroll, filing |
| Filing outage | authority channel unavailable, transmission failure | keep filings APPROVED; submit through the authority portal and record submission / response; exception queue | filing |
| Authority rejection | REJECTED filing (error codes) | fix the cause; rebuild → new version / correction; payroll and payments unchanged | filing |
| Payment failure | REJECTED / RETURNED / UNKNOWN batch or item | bank result + returns; re-issue through a new batch | salary payment |

Every incident record names the worker / employer affected, the statutory source involved, the action
required and whether payroll, filing or payment is blocked (spec §14 operator rule). The exception queue
(Compliance › Belgium › Filing centre) lists rejected filings, late Dimona, filings not validated,
overdue or unsourced obligations, open variances and payment failures.
