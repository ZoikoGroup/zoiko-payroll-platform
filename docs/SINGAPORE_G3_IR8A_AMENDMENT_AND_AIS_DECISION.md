# Singapore G3 — IR8A Amendment and AIS API 2.0: Engineering Decision

- **Date:** 2026-09-28 (Phase 6.7; implementation status updated in Phase 6.8). Branch `nikhil` @ `83601eb`, uncommitted.
- **Gate:** ZP-SG-ENG-001 §18 G3 — *"AIS YA2027 data model validated; AIS-API 2.0 onboarding or explicit export-only
  mode; amendment and acknowledgement paths proven."*
- **Certification:** none. No IRAS validation, onboarding or acknowledgement of Zoiko output exists.

## Evidence used

| Ref | Source | Status |
|---|---|---|
| E1 | IRAS, *Quick Guide on using Submit Employment Income Records Digital Service (Revision and Amendment submission methods)*, published 15 Sep 2025. `https://www.iras.gov.sg/media/docs/default-source/uploadedfiles/pdf/quick-guide-on-making-ais-amendments-at-mytax-portal-(online-application).pdf`. SHA-256 `a419da57237d20e0b08aadfe9e96adf37bf38924ba2aee11fde53f82da5f01df`, retrieved 2026-09-28 | Retrieved and read. **Registered in Phase 6.8** as canonical-pack source `iras_ais_modification_guide` (`backend/scripts/seed_singapore_canonical_pack.py`) |
| E2 | IRAS page *Amend Submitted Records* (AIS for Employment Income). Content seen only through a search-result summary; the page body did not render for retrieval | **Unverified:** confirm by direct review before relying on it |
| E3 | Registered sources: `iras_ais`, `iras_ir8a_notes_ya2027`, `iras_ais_file_notes` (canonical pack) | Registered (hashed) |

**E1 states:**
- To modify an earlier filing, choose the year, select **"Modify previously submitted data"** and choose an amendment
  method.
- **Revision submission:** "Enter the full and correct values for all relevant fields, as this will overwrite the
  previous record(s)."
- **Amendment submission:** "Provide only the difference in values (i.e., add the additional amount or subtract the
  over-reported amount). Leave unaffected field blank."
- Prepare Appendix 8A / 8B where necessary.
- "Upon successful submission, you will receive an acknowledgment page with the acknowledgement number."

**E2 (unverified) indicates:**
- amendments are required for errors in employee IDs, income, deductions, or income indicators affecting taxability;
- personal particulars such as an address need no amendment;
- an amendment may use a different AIS mode than the original;
- IRAS offers an "Amendment Checker" workbook.

## A. Already implemented
- **Extract:** `generate_sg_ir8a` builds the IR8A extract for an income year. It is EXPORT_READY, from payslips'
  per-earning IRAS classification (YA2027 notes), with IRAS whole-dollar rounding in `myTaxPortalEntry`.
  - Stored NRIC/FIN is masked (PDPC partial form).
  - It records the payslips' pinned pack version (Phase 6.5).
  - It is tenant-scoped, and uses payroll-operator RBAC on `/api/payroll/singapore/reports/ir8a`.
  - A new extract is refused (409) while a submission is SUBMITTED_MANUALLY or UNKNOWN.
- **Lifecycle:** `transition_sg_ir8a`: EXPORT_READY → SUBMITTED_MANUALLY → ACKNOWLEDGED / REJECTED / UNKNOWN.
  - SUBMITTED_MANUALLY needs an operator distinct from the preparer (maker-checker; refusal audited, 6.5), plus the
    IRAS reference.
  - UNKNOWN is never success, and resolving it needs a note.
  - Every step is audited (`sg_ir8a`).
- **New in 6.7 (guard, not amendment):** once the organisation's IR8A for a year is ACKNOWLEDGED, a further extract can
  be prepared for reference but **cannot be recorded as another submission**. That refusal is audited. It closes a
  defect where a second unlabelled "original" could be recorded for an acknowledged year. A REJECTED filing can still
  be resubmitted. Tests: `backend/tests/test_singapore_phase67_ir8a_guard.py`.
- **Phase 6.8: revision and amendment implemented** (§C). **Not implemented:** AIS-API 2.0.

## B. Required for export-only operational mode
1. **BUSINESS:** a signed product decision that Singapore runs in export-only mode, meaning the employer keys or
   uploads through myTax Portal and Zoiko records the evidence (spec G3 allows it).
2. **EXTERNAL:** IRAS-side validation that the extract's items map correctly to the myTax Portal fields for YA2027, for
   a real employer.
3. **ENGINEERING:** the revision/amendment capability (C). Without it, an acknowledged year's corrections are filed
   outside Zoiko with no Zoiko evidence, which the 6.7 guard makes explicit rather than silently wrong.

## C. IR8A revision/amendment — IMPLEMENTED in Phase 6.8 (design below, as built)

**Built (Phase 6.8):**
- **Model:** `models.SgpIr8aModification`.
- **Service:**
  - `create_sg_ir8a_modification` and `list_sg_ir8a_modifications`;
  - helpers `_sg_ir8a_extract` (the shared extract builder), `_sg_ir8a_position`, `_sg_ir8a_cumulative_position`,
    `_sg_ir8a_delta`, `_sg_ir8a_apply_delta`;
  - `transition_sg_ir8a` hooks: a registered modification is exempt from the 6.7 guard, a modification is filed only
    against the position it was computed from, and the filing operator is recorded.
- **API:** `POST` / `GET /api/payroll/singapore/reports/ir8a/{report_id}/modifications` (payroll-operator access
  control, the caller's organisation).
- **Tests:** `tests/test_singapore_phase68_ir8a_modifications.py` (17; all fail on the pre-6.8 code).
- **Migration:** `445abd6a9083_create_sgp_ir8a_modifications.py`, **down_revision `6247da96d605`**. It is applied at the
  release-line merge together with the merge revision, never on the nikhil-only lineage.
- **PostgreSQL rehearsal:** 16/16 on the migrated shared-schema copy.

**Why it was not implemented in Phase 6.7 (history):**
**Why not implemented in 6.7:**
- **Architecture:** `payroll_generated_reports` has no column linking a report to the submission it modifies. An
  explicit, enforced relationship needs a new migration, and a new migration can only be anchored after the venu merge
  (integration head `6247da96d605`). Adding one on `nikhil` now would create a second head / lineage risk (the
  "speculative migration" case).
- **Statutory:** E1 was only retrieved in this phase; E2 is unverified. The method choice and delta rules should be
  implemented against registered, reviewed sources.

**Proposed data model** (additive, Singapore-only, same pattern as `sgp_ir21_cases`; migration on top of
`6247da96d605` after the merge). New table `sgp_ir8a_modifications`:

| Column | Notes |
|---|---|
| `id` | |
| `organization_id` | FK, indexed |
| `reporting_year` | |
| `base_report_id` | FK → `payroll_generated_reports`: the ACKNOWLEDGED original it modifies |
| `report_id` | FK: the new extract row |
| `method` | `REVISION` \| `AMENDMENT` |
| `sequence` | 1..n per base |
| `reason` | |
| `prepared_by_id`, `recorded_by_id` | |
| `created_at` | |

Constraints: `UNIQUE(base_report_id, sequence)` and `UNIQUE(report_id)`. The shared `GeneratedReport` table is not
altered.

**Lifecycle** (reuses `transition_sg_ir8a` states and gates):
1. **Precondition:** the base is ACKNOWLEDGED, and there is no open (SUBMITTED_MANUALLY / UNKNOWN) modification for the
   organisation and year.
2. **Revision:** a full current extract for the affected employees (E1: overwrites).
3. **Amendment:** a per-employee, per-field delta: *current values − cumulative acknowledged position*. The position is
   the base plus every later ACKNOWLEDGED modification (a revision resets it to its own values). Only non-zero deltas
   are kept; unaffected fields stay blank (E1).
4. **Appendix 8A / 8B:** follow the same method (E1). Scope to be confirmed against IRAS sources.
5. **States:** EXPORT_READY → SUBMITTED_MANUALLY (distinct operator + IRAS reference) → ACKNOWLEDGED / REJECTED /
   UNKNOWN (reference required; UNKNOWN never success).
6. **Outcomes:**
   - **REJECTED:** the cumulative position is unchanged, and a new modification may follow.
   - **Multiple amendments:** they chain by `sequence`, each delta against the position acknowledged before it.
   - **Regeneration:** only an EXPORT_READY modification may be regenerated (it supersedes itself). Acknowledged rows
     are immutable.

**Answers to the design questions:**
1. **Original:** the ACKNOWLEDGED `GeneratedReport` with no `sgp_ir8a_modifications` row as `report_id`.
2. **Link:** `base_report_id` and `sequence`.
3. **New immutable version:** yes, a new row; nothing is edited in place.
4. **Original immutable:** acknowledged rows are never regenerated or transitioned (existing transition table), and
   the 6.7 guard blocks a duplicate submission.
5. **Amended data:** built from current payslips, including SG-044 append-only correction payslips, by the same
   classification as the original.
6–7. **Maker-checker:** the existing distinct-operator rule on SUBMITTED_MANUALLY, audited.
8. **Pack version:** from the payslips (the `_sg_pinned_pack` rule).
9. **Tenant isolation:** every query is filtered by `organization_id`, as today.
10. **Masking:** stored rows masked, as today.
11. **Audit:** `sg_ir8a` status_change / refused rows, plus the modification row itself.
12. **Status:** as the lifecycle above.
13. **Rejected:** see lifecycle.
14. **Multiple:** chained.
15. **Regeneration:** EXPORT_READY only.
16. **Amendment vs correction:** a correction or recalculation changes **payroll** data (new payslips, never edits); an
    IR8A modification **reports** acknowledged-year changes to IRAS.
17. **Manual myTax submission:** recorded with the IRAS reference and acknowledgement number, as today.
18. **AIS-API 2.0 later:** see D.

**Proposed API** (payroll-operator RBAC, tenant-scoped):
- `POST /api/payroll/singapore/reports/ir8a/{report_id}/modifications {method, reason}` → EXPORT_READY modification.
- `GET /api/payroll/singapore/reports/ir8a/{report_id}/modifications`.
- Transitions via the existing `/ir8a/{id}/transition`.

## D. Required for AIS API 2.0 (not in scope — separate implementation phase)
- IRAS APEX API onboarding.
- Corppass authorisation for the employer and any tax-agent arrangement.
- Registered application credentials and certificates in a secrets store.
- IRAS test (sandbox) access.
- The submission payload per the IRAS AIS-API 2.0 specification (original / revision / amendment indicators).
- Validation-error handling and acknowledgement retrieval.
- Retry and idempotency, and outage fallback to export-only.

**No speculative integration has been written.**

## E. External IRAS dependencies
- API onboarding and credentials (D).
- Confirmation of E2 and IRAS's Amendment Checker rules.
- Validation of the YA2027 field mapping for a real employer.
- A real acknowledgement for an original and for a modification (proves G3's "amendment and acknowledgement paths").

## F. Business decisions
- Export-only vs AIS-API 2.0 for go-live.
- Whether revision, amendment or both are offered; E1 lets the employer choose.
- Who (which role) may record modifications.

## G. Engineering decisions
- The dedicated `sgp_ir8a_modifications` table, not new shared `GeneratedReport` columns (cross-jurisdiction safety).
- The migration is anchored post-merge on `6247da96d605`.
- Register E1 (and E2 once verified) as `SourceArtifact`s.
- Keep the 6.7 guard until the modification flow replaces it for the ACKNOWLEDGED case.

## H. Security / privacy
- Stored extracts stay masked; full identifiers are used only where IRAS entry requires them, keyed by the operator
  from the employee record.
- Maker-checker on recording; tenant isolation on every query; audit on success and refusal.
- API credentials (D) must never be stored in code or the database in clear text.

## I. Testing requirements (for the implementation phase)
- Revision equals the full current values.
- Amendment deltas: positive, negative, zero omitted, across chained amendments and after a revision reset.
- Refusal when the base isn't ACKNOWLEDGED, when a modification is open, and for preparer self-recording.
- REJECTED keeps the position.
- Tenant isolation, masking, pack version, audit rows.
- Migration round trip on PostgreSQL.
- Directional tests against the pre-feature code.

## J. Production acceptance criteria for G3
1. A signed export-only (or API) decision.
2. IRAS-validated YA2027 mapping for a real employer.
3. An original submission and at least one modification **acknowledged by IRAS** and recorded in Zoiko with their
   acknowledgement numbers.
4. The modification flow (C) implemented and tested — **engineering done in Phase 6.8**; the IRAS-acknowledged modification (criterion 3) is still outstanding.
5. (If API mode) IRAS onboarding complete and sandbox acceptance evidenced.

Until then G3 is **EXTERNAL EVIDENCE REQUIRED + BUSINESS APPROVAL REQUIRED**. The Phase 6.7 implementation gap (C) is
closed at engineering level in Phase 6.8.
