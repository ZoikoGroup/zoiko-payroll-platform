# Singapore — Final Implementation Status (authoritative)

**Date:** 2026-09-29 · **Branch:** `nikhil` (HEAD `264c585`) plus the uncommitted working tree in §25 · **Live `origin/main`:** `4ed8125` (head `998877665544`).

This document is the single source of truth for Singapore (SG). It supersedes every `SINGAPORE_PHASE_*` document, which remain as history.

It covers three passes on 2026-09-29:
- the **completion programme** (23 fixes);
- the **final closure programme** (15 further closures — §24.2);
- the **activation-readiness pass** (re-verification on the final tree, plus one closure: the consolidated pending-decisions / external-dependencies view);
- the **final execution pass**: one activation-safety closure (§7a). Everything else was re-verified; the shared DB was re-checked read-only (§16).

All rehearsals in §1 were re-run on the final tree.

Zoiko holds **no** CPF Board, IRAS, MOM or PDPC approval, certification or acknowledgement. `officialCertification` is `false` everywhere. "Engineering complete" never means "gate complete".

---

## 1. Executive status

**Classification: A — ENGINEERING + CONFIGURATION COMPLETE. External activation pending.**

Every requirement that can be closed inside the repository is closed, tested and rehearsed on PostgreSQL. What remains is one of:
- **external evidence or data** — G1–G8; unpublished MOM values; AIS-API specification and credentials;
- **an owner decision** — D1 AIS submission mode, D2 hotfix policy, D3 scope of the Singapore-only controls;
- **a deploy-owner action** — merge, then the migration runbook in §17.

Singapore is **not** "production ready":
- the service registry keeps it `PLANNED`;
- no gate is evidenced.

| Evidence (2026-09-29) | Result |
|---|---|
| Full backend `pytest tests/` | see §21 (final run) |
| New regression tests, closure passes | 19 closure + 3 deploy-script. **16/19 and 2/3 fail on the pre-change code**; the passing ones are deliberate preservation checks. |
| New regression tests, completion pass | 36 + 2. **31/36 fail on the pre-change code.** |
| PostgreSQL activation rehearsal (throwaway DB built from the **shared DB's schema** + fixed deploy script) | **172 PASS / 0 FAIL / 0 BLOCKED / 1 INFO** |
| PostgreSQL end-to-end product scenario (two payroll cycles, YTD, correction, supersession, registry PLANNED → AVAILABLE, readiness dashboard, evidence registry) | **42 PASS / 0 FAIL** (adds per-month PWM classification capture on every calculated payslip; earlier: the evidence lifecycle — SUBMITTED → UNDER_REVIEW → REJECTED / PASS → EXPIRED — a structured D1 decision, and the sixteen-category four-status dashboard; earlier: the cancelled S Pass — 19 × S$21.37 = S$406.03 — the evidence-integrity refusals, and evidence supersession → pending → PASS on review of the replacement) |
| Production seed CLIs run twice (disposable DB) | **second run changes nothing**: PostgreSQL row-version (`xmin`) fingerprints of SG packs, rates, slabs, PWM, sources, templates, components, fields and the registry are identical across runs 1 and 2 (before this pass the Draft pack's 596 rates + 336 slabs were deleted and re-inserted on every run — found by this check, fixed in `_reconcile_pack_rows`). Identical counts both runs: 2 Draft packs, 596 rates (592 + 2 MOM cancellation rules × 2 packs), PWM 6,132 / 84 / 73 / 6, 11 Draft templates, registry `PLANNED`, other countries' registry rows untouched |
| Upgrade rehearsal from the shared DB revision (exact schema copy) | 7 migrations, +2 tables, +11 columns, +8 indexes, 0 removed, no drift, re-run no-op |
| Deploy-script rehearsal (fixed vs main's original, 3 scenarios) | Fixed: never mutates before refusing. Original: a refused deploy added 11 columns. |
| Frontend | ESLint 15 Singapore files: 0 problems. `vite build`: 2,703 modules, exit 0. |

## 2. Architecture

| Layer | Location |
|---|---|
| Engine | `engine/countries/singapore.py`. Fail-closed; `SG` is the only country in `_VALIDATION_ENABLED_COUNTRIES`. Results: CPF → `employee_pension` / `employer_pension`; SHG → `professional_tax`; SDL → `employer_payroll_tax`; FWL → `employer_eht`. |
| Jurisdiction helpers | `engine/jurisdictions/singapore/`: `labour.py` (PWM, LQS, Employment Act), `preflight.py`, `readiness.py`, `statutory/ezpay.py`, `statutory_summary.py` (Super Admin summary, template catalogue, production gates) |
| Service / routes | `payroll/service.py`. Org routes `/api/payroll/singapore/*` use `get_current_payroll_operator` with the org taken from the token. Super Admin routes `/api/super-admin/*` use `get_current_super_admin`. |
| Data | `payroll_employees.sgp_*` (10 columns), `payslip_items.sgp_calculation_trace`, `sgp_ir21_cases`, `sgp_pwm_overtime_schedules`, `sgp_ir8a_modifications`. Shared: `payroll_generated_reports`, `payroll_tax_configuration_audit`. |
| Super Admin UI | `pages/JurisdictionCompliance/SGCompliancePage.jsx` + `components/jurisdiction/singapore/*`, on the shared `JurisdictionLayout` |
| Org UI | `modules/payroll/Compliances/SG*.jsx`, `PayRollRuns/SGRunPreflightPanel.jsx` |

## 3. Statutory configuration

**One canonical source per domain:**

| Domain | Canonical source |
|---|---|
| Statutory values (CPF, SDL, SHG, FWL, LQS, PWM floors, IRAS/IR21 parameters) | JurisdictionPack `SG-PAYROLL-2026` rows, seeded by `scripts/seed_singapore_canonical_pack.py` (Draft; 592 rates, 336 slabs, 53 SHA-256-hashed SourceArtifacts) |
| PWM overtime gross table | `sgp_pwm_overtime_schedules` (§8) |
| Report templates | `ReportTemplate` rows, seeded by `scripts/seed_statutory_report_templates.py`; classification catalogue in `statutory_summary.SG_REPORT_TEMPLATES` |
| Org statutory settings (UEN, CSN, AIS participation / mode, Corppass, MOM sector) | `app/core/jurisdiction.py` schema, stored in `CompanyComplianceDetails.tax_identifiers` |
| Service availability | `jurisdiction_service_registry` (SG = `PLANNED`) |
| Production gates | `statutory_summary.SG_PRODUCTION_GATES` (the UI renders it; no longer duplicated in React) |
| Governance policy switches | `service.py`: `_PACK_TRANSITION_GRAPH_COUNTRIES`, `_SELF_APPROVAL_REFUSED_COUNTRIES`, `_REFUSAL_AUDIT_COUNTRIES`, `_HOTFIX_DISTINCT_REVIEWER_COUNTRIES`, `SG_HOTFIX_POLICY` |

- **No environment variable changes Singapore statutory behaviour.**
- **No statutory value is hard-coded in React.** This pass removed the last case: the CPF wage-band S$ thresholds used in grid headers and band-form defaults. They are now read from the pack's TaxSlab rows.
- Every statutory row carries `effective_from/to`, `source_document_id`, the pack version, and the lifecycle / validation state.
- Values MOM has not published are **not configured**, never defaulted (§19).

## 4. Super Admin configuration (Compliance → Singapore)

**Tabs:**
- Overview
- Statutory Components
- Statutory Summary
- **Readiness & Operations** — new in this pass
- Source Evidence
- PWM Schedules
- Report Templates
- Golden Vectors
- shared: Versions / Organizations / Audit

| Requirement | Where | State |
|---|---|---|
| Enabled / disabled | Readiness → Service availability (registry `PLANNED`; filing/payment/remittance responsibilities) | IMPLEMENTED (this pass) |
| Pack version, effective from/to, source + SHA-256, retrieval, lifecycle, validation, approver, last editor, activation | Readiness → Activation readiness | VERIFIED |
| Distinct-approver / source / effective-date / golden-vector gates | Same | VERIFIED |
| Audit history | Same: entries, refusals, last entry, hotfix activations / awaiting review | VERIFIED |
| CPF (OW / annual ceilings, cohorts × age bands × wage bands, rounding sequence, sources) | Statutory Components → CPF (band ranges now from pack rows) | VERIFIED |
| SDL / SHG | Components + Summary | VERIFIED |
| FWL | Components: S Pass **and every Work Permit levy row in the pack** (was a stale "not configured" note) | FIXED (this pass) |
| LQS (FT/PT floors) and quota status | Summary capability `NOT_IMPLEMENTED`; Readiness operation `lqs_quota` = **EXTERNAL_DATA_REQUIRED** | IMPLEMENTED |
| PWM | PWM Schedules: rows / schedules / OT range / sources + hashes / retrieval / seed date; sector, group, level, **exact role**, in-force date, OT hours, status, search; server pagination (≤ 200/page); no stale rows while loading | VERIFIED + FIXED |
| IR8A / IR21 / EZPay | Readiness → Statutory operations: template state, generator, lifecycle (the service's own transition maps), controls, channel, external dependency | IMPLEMENTED |
| AIS | Operation `ais_api` = **EXTERNAL_INTEGRATION_REQUIRED**; the org setting's options and states (`EXPORT_ONLY` READY, `DIRECT_API` EXTERNAL_INTEGRATION_REQUIRED) | IMPLEMENTED (this pass) |
| Hotfix policy | Readiness → current policy, options, awaiting review | IMPLEMENTED (this pass) |
| G1–G8 | Overview + Readiness table from the backend; none shown as passed | IMPLEMENTED (this pass) |
| Pending decisions / external dependencies | Readiness → D1–D3 with the value in force; external dependencies derived from the configuration (an item disappears once its data is recorded) | IMPLEMENTED (activation-readiness pass) |

The Super Admin summary **carries no organisation data.** A Phase 5.6 test enforces this, and this pass kept it: per-org AIS counts were removed in favour of the setting definition.

## 5. Report templates

The catalogue has **11 Singapore templates.** All exist and are seeded **Draft**.

| Code | Type | Classification | Generator |
|---|---|---|---|
| SG-PAYROLL-REGISTER / -SUMMARY | SG_PAYROLL_* | INTERNAL_REPORT | generic |
| SG-CPF-CONTRIBUTION | SG_CPF_CONTRIBUTION | SUBMISSION_SUPPORT | generic |
| SG-SHG-MONTHLY | SG_SHG_MONTHLY | SUBMISSION_SUPPORT | generic |
| SG-FWL-MONTHLY | SG_FWL_MONTHLY | INTERNAL_REPORT | generic |
| SG-PWM-COMPLIANCE / SG-IR21-REGISTER / SG-LQS-COMPLIANCE | … | STATUTORY_WORKSPACE | dedicated |
| SG-IR8A / SG-CPF-EZPAY | … | EXPORT_READY | dedicated |
| SG-SDL-MONTHLY | SG_SDL_MONTHLY | SUBMISSION_SUPPORT | dedicated |

**The Report Templates tab shows, for each template:**
- code, name, description and classification;
- status, and the **Active version** when the listed latest version is a Draft correction;
- whether it is generatable, and the allowed next statuses;
- version and previous version;
- effective from–to;
- source (agency / title / SHA-256 / reviewed);
- approver and approval date;
- audit count and version count;
- editable lock, output scope, generator;
- **official certification — always "No"**.

**Lifecycle** (shared `REPORT_TEMPLATE_TRANSITIONS`, unchanged): Draft → Review → Approved → Published → Active → Superseded.
- Superseded is final. Published and Active never return to an editable state; no arbitrary status is accepted.
- The last editor's self-approval is refused at Approve (SG) and again at Publish.
- A released approval is never replaced. An edit clears a pre-release approval.
- A correction is a new version with a `previous_version_id` link.
- A Superseded SG template cannot be deleted, and deletes are audited.

**Seeding** is idempotent. It only refreshes Draft rows and **never** demotes, re-approves or rewrites an Approved, Published, Active or Superseded template. This is tested (`test_reseeding_never_demotes_…`) and rehearsed on PostgreSQL.

## 6. Report generators

All 12 generators share these properties:
- tenant-scoped (org from the token);
- Active template only;
- the **payslips' pinned pack**, never "the pack Active today";
- template version pinned;
- regeneration supersedes every live report of that type and scope, across template versions;
- a "create" audit row listing the superseded ids;
- NRIC/FIN masked.

| Generator | Maker-checker / special rules |
|---|---|
| Payroll register / summary, CPF contribution, SHG, FWL (generic) | Active SG template only |
| SDL monthly | Employer total rounded down |
| PWM / LQS compliance | `packBasis` = PINNED / PINNED_MULTIPLE / RESOLVED_FOR_WAGE_MONTH (legacy rows only) |
| IR21 register | Case maker-checker shown |
| IR8A | A distinct, identified operator records the filing. One acknowledged original per year. **200-record myTax Portal batches** (this pass). Filed or acknowledged extracts cannot be voided; the refusal is audited. |
| IR8A revision / amendment | Rendered from the **Active** template version of the key. Filed through the same lifecycle. |
| CPF EZPay | A distinct, identified approver. 150-byte ASCII records. The file is never stored; it is rebuilt on download against its SHA-256, and every download is audited. Submitted or accepted files cannot be voided; the refusal is audited. |

**Authority rejection capture** (this pass): IRAS / CPF Board error messages are recorded verbatim with a REJECTED / UNKNOWN outcome, via the `errors` field on both transition routes. They are refused on any other step.

## 7. Pack governance

**Singapore tax pack graph** (`TAX_PACK_TRANSITIONS`):

| From | To |
|---|---|
| Draft / In Review / QA / Approved | each other, and → Active (gated) |
| Active | Active (idempotent), Deprecated, Retired, Superseded |
| Deprecated | Retired, Superseded |
| Retired, Superseded | none — **final** |

- Unknown status strings are refused. Active never returns to a pre-Active state.
- The codebase's pack vocabulary has no "Published" state; In Review / QA / Approved are the review stages.

**Activation gates:**
- linked source evidence;
- effective-from date;
- latest SG golden run PASS;
- approver ≠ last editor, refused already at Approve;
- approver ≠ activator;
- no overlap;
- the graph.

**Other rules:**
- A released pack's approval is never replaced.
- The status-change reason is audited.
- An organisation account can never edit a tax pack. This is a security fix for all countries: the pack type can never change.
- Every SG governance refusal writes exactly one "refused" audit row, with no pending changes left behind.

**Hotfix — owner decision D2, made explicit** (`SG_HOTFIX_POLICY`):

| Policy | Behaviour |
|---|---|
| `RESTRICTED` (**default = the behaviour in force**) | Hotfix bypasses only the approver checks; all other gates, including the graph, apply. A distinct Super Admin's retrospective review is required, is final, and is audited. |
| `PROHIBITED` | Every SG hotfix is refused (audited) |
| `FOLLOW_UP_REQUIRED` | While an SG hotfix awaits review, every further SG activation (normal or hotfix) is refused (audited) |

The Super Admin sees the current policy and the number of hotfixes awaiting review. Changing the value is the decision: a reviewed one-line change.

## 7a. Service registry — pack activation never opens onboarding (final execution pass)

The onboarding gate (`engine/tax_resolver.get_jurisdiction_onboarding_block_reason`) blocks a `PLANNED` / `NOT_AVAILABLE` registry row. With **no** row, however, it fell through to the canonical-pack check alone. The shared DB has **no Singapore registry row**, so activating the Singapore pack would have opened Singapore onboarding by itself, bypassing the owner's `PLANNED → AVAILABLE` step.

**Closed:**
- **Singapore opt-in (`_REGISTRY_ROW_REQUIRED_COUNTRIES = ("SG",)`):** a missing row now blocks onboarding. Other countries keep the fall-through; this is tested.
- **The canonical Singapore seed** creates the row as `PLANNED` only if it is missing, and never changes an existing row. The shared `seed_jurisdiction_service_registry.py` overwrites every country's row and is **not** for production.
- **Readiness** shows the registry state as a blocker until it is `AVAILABLE`.
- **PostgreSQL E2E:** the row is `PLANNED` after seeding, and onboarding stays closed after pack activation.

## 7b. Evidence registry and activation readiness dashboard (production-closure pass)

### Evidence registry (G1–G8, D1–D3)
Evidence is an ordinary **Source Evidence** artifact (`SourceArtifact`), created in Super Admin → Compliance → Singapore → Source Evidence. **No new table.**

**How to record it:**
- Give the artifact the form number **`SG-GATE-G1` … `SG-GATE-G8`** or **`SG-DECISION-D1` … `SG-DECISION-D3`**.
- Upload the signed file; its SHA-256 is recorded.
- A **different** Super Admin records the outcome: **ACCEPTED** (optional notes and *valid until* date) or **REJECTED** (notes required). Use `review_sg_gate_evidence` / `PUT /api/super-admin/compliance/source-artifacts/{id}/sg-review`. The generic review action still accepts, with the same rules.
- Decisions D1–D3 are recorded with `record_sg_decision` / `POST /api/super-admin/compliance/singapore/decisions`: the selected option, the decision maker and the reason. They count only after the memo is uploaded and a different Super Admin accepts it.

**How it is scored (final completion programme, derived and never typed in):**

| State | When |
|---|---|
| `EVIDENCE_REQUIRED` | No current (non-superseded) artifact |
| `SUBMITTED` | Registered, no document uploaded |
| `UNDER_REVIEW` | Document uploaded (server SHA-256), awaiting a distinct reviewer |
| `PASS` (gate) / `DECISION_RECORDED` (decision) | Creator on record, a different user accepted it, server SHA-256, not superseded, within its validity date, and for a decision a selected option on record |
| `REJECTED` | Rejected by its reviewer (notes shown). Final for that artifact: it can't be accepted, reviewed again or re-uploaded |
| `EXPIRED` | Accepted, but past its *valid until* date |

- Outcomes and decision values are immutable `payroll_tax_configuration_audit` rows on the artifact. There is **no new table, column or migration**; the head stays `445abd6a9083`.
- Each gate reports its required artifact, acceptance criterion, submitted artifact, reviewer, review date, expiry date, notes, blocking reason and next action.
- Each decision reports its options, the value in force (the product default), the recorded value, the decision maker, the date, the reason, the reviewer and the review status. If the recorded value differs from the value in force, it shows `inForceDiffers` and the effect. Recording never changes behaviour.
- Recording D1 moves G3 from `BUSINESS_DECISION_REQUIRED` to `EVIDENCE_REQUIRED`: the IRAS evidence is still needed.
- **Nothing is scored from engineering results.** An internal report is not a gate artifact.
- **Evidence integrity (final closure pass):**
  - A gate / decision artifact is accepted only with an **uploaded** document (server-computed SHA-256); a hand-typed hash never counts.
  - It cannot be reviewed before the document is uploaded.
  - Once reviewed, its document **cannot be replaced**. Before this fix an upload replaced it and deleted the reviewed file. Record a new artifact and supersede the old one instead.
  - **Supersession (final closure pass, new):** `supersede_sg_gate_evidence` / `PUT /api/super-admin/compliance/source-artifacts/{id}/supersede` (Super Admin only; Readiness tab "Supersede with #n"). The old artifact, file and review are kept and shown `SUPERSEDED`; the replacement must carry the same form number and not itself be superseded; self-supersession, re-supersession and non-SG artifacts are refused; audited. Supersession only withdraws acceptance: the gate returns to pending until a different Super Admin reviews the replacement. Before this pass `superseded_by_id` could not be set by any route, so a corrected document had no path.
  - Owner handoff (G1–G8, D1–D3, MOM data, deploy checklist): `docs/SINGAPORE_EXTERNAL_EVIDENCE_HANDOFF.md`.
  - This applies to `SG-GATE-*` / `SG-DECISION-*` artifacts only; other Source Evidence is unchanged.

### Readiness dashboard (Readiness & Operations tab)
Sixteen categories, each `PASS` / `BLOCKED` / `EXTERNAL_REQUIRED` / `BUSINESS_DECISION_REQUIRED`, with its basis. External evidence, external data, **external integrations** (IRAS AIS-API 2.0, new this pass) and deployment show `EXTERNAL_REQUIRED`; business decisions shows `BUSINESS_DECISION_REQUIRED`; a local state that isn't ready (generators without an Active template, no golden run) shows `BLOCKED`:

| Basis | Categories |
|---|---|
| **Observed now** | configuration, report templates, generators (Active templates), **database** (every `sgp_*` object present), **migration** (the DB's Alembic revision equals the code head, read-only), testing (latest golden run), external evidence, business decisions, external data, external integrations |
| **Internal engineering evidence** | engineering, security, tenant isolation |
| **Owner action** | deployment |

**Production activation** is `PASS` only when every category passes, a Singapore pack is Active **and** the registry is `AVAILABLE`. Otherwise it lists every blocker.

**Each template row** also states `externalValidation = EXTERNAL_VALIDATION_REQUIRED`.

## 8. PWM

- **6,132 rows = 84 schedules × 73 overtime-hour values (0–72)**, from 6 hashed MOM PDFs.
- Tenant-independent and read-only (write methods return 405).
- Never copied into a payslip snapshot.
- Filters: sector, group, level, exact role, in-force date, OT hours, status, and search.
- **PostgreSQL:**
  - The lookup (sector + group + level + OT hours + date) uses the unique index `uq_sgp_pwm_ot_schedule_row`: 0.04 ms execution.
  - Pages take 3–34 ms with 2 statements each.
  - The summary takes about 49 ms with a fixed 22 statements, no N+1.
  - **No index added.**

## 9. IR8A

The IR8A flow:
- An EXPORT_READY extract, with IRAS rounding (income down, deductions up), masked NRIC, and each row's myTax Portal batch.
- The manual submission lifecycle: EXPORT_READY → SUBMITTED_MANUALLY (distinct operator + IRAS reference) → ACKNOWLEDGED / REJECTED (+ IRAS errors) / UNKNOWN.
- One acknowledged original per year.
- A **Revision** (full values) or **Amendment** (delta) of an acknowledged original. The stale-position guard applies.
- The organisation UI can prepare an extract and a revision/amendment.
- This pass corrected the 6.7 guard's message, which still claimed the modification workflow was unimplemented.

**Limitations:**
- Appendix 8B is BLOCKED (share-plan data is not captured).
- The AIS record fields beyond the myTax Portal entry are pending the AIS-API specification (§12).

## 10. IR21

- **Case lifecycle:** DRAFT → FILED → CLEARED → RELEASED, with EXEMPT / CANCELLED / EXCEPTION / RECONCILE_FIRST.
- **Money hold:** pay is held while DRAFT / FILED / CLEARED / EXCEPTION / RECONCILE_FIRST, and held payslips are excluded from the bank file.
- **Maker-checker:** a distinct, identified approver is required for RELEASED / EXEMPT / CANCELLED. Transitions are row-locked.
- **Knock-on effects:** filed cases are excluded from IR8A. A correction after filing moves the case to EXCEPTION. The disaster-recovery freeze moves DRAFT cases to RECONCILE_FIRST.
- **Audit:** under `sgp_ir21_case`. The freeze now uses the same entity type.
- **Access:** the case view carries no NRIC / bank data, the register masks NRIC, and cases are tenant-scoped (IDOR-tested).
- **Not built:** a Form IR21 content extract. Filing is manual on myTax Portal.

## 11. CPF EZPay

- Built to CPF Board "EZPay (FTP) File Specifications" (16 Jan 2025): header, summaries, details and trailer, as fixed 150-byte **ASCII** records.
- Non-ASCII names are refused as validation errors (previously an HTTP 500).
- Lifecycle: PREPARED → APPROVED (distinct, identified approver) → SUBMITTED → ACCEPTED / REJECTED (+ CPF Board errors) / UNKNOWN.
- Download from APPROVED onward: rebuilt, verified against its SHA-256, and audited.
- Codes 07 (late-payment interest) and 10 (Community Chest) are not computed (§19).

## 12. AIS

| Capability | State |
|---|---|
| Export (extract) | IMPLEMENTED |
| Validation (per-row readiness, issues) | IMPLEMENTED |
| Submission readiness (per-org readiness, Super Admin operations) | IMPLEMENTED |
| Submission status / acknowledgement | IMPLEMENTED (manual lifecycle) |
| Error capture | IMPLEMENTED (this pass) |
| Audit trail | IMPLEMENTED |
| Per-org mode setting `EXPORT_ONLY` / `DIRECT_API` | IMPLEMENTED (readiness marks `DIRECT_API` BLOCKED) |
| **AIS-API 2.0 direct submission** | **EXTERNAL_INTEGRATION_REQUIRED** + **BUSINESS DECISION (D1)** |

What the direct submission needs:
- IRAS APEX onboarding;
- Corppass authorisation;
- credentials and certificates in a secrets store;
- sandbox access;
- the **AIS-API 2.0 specification**, which is not retrieved or registered.

No payload or client was written, because that would invent a format.

## 13. LQS

- The per-employee floor (full-time monthly / part-time hourly) is evaluated by the engine and reported by SG-LQS-COMPLIANCE.
- The **foreign-worker quota** (dependency-ratio ceilings, local qualifying headcount, part-time weighting) is **not computed anywhere**.
- Readiness reports it as `EXTERNAL_DATA_REQUIRED`. It would become `NOT_IMPLEMENTED` once sourced `lqs_quota__*` pack rows exist.
- It **fails safe**: no quota figure is ever produced.
- The part-time LQS rate **before 1 July 2026 is sourced**: MOM COS 2024 factsheet, $10.50/h from 1 July 2024, seeded for Jan–Jun 2026. Earlier documents that called it unpublished were stale; corrected in the final pass.

## 14. Security

- **Super Admin governance routes:** `get_current_super_admin` requires role `super_admin` **and** no organisation. Org admins, payroll admins, tenant-bound super admins and assisted access are refused (HTTP matrix in the rehearsal).
- **Organisation operators** can never edit a tax pack. Test: `test_org_operator_cannot_edit_a_tax_pack_through_the_policy_route`.
- **Self-approval** is refused and audited for packs, templates, IR8A, IR21 and EZPay.
- **Released immutability:**
  - released templates can't be edited, approved again, or deleted (Superseded);
  - released packs: the graph applies, the approval is never replaced, and edits are refused.
- **NRIC/FIN** is PDPC-partial (last 4) in every stored report and view. The full values appear only in the EZPay file, which the CPF spec requires; it is audited on download.
- **Report download and void** are payroll-operator only, and tenant-owned via `get_generated_report(org_id)`.
- There is no Auditor role and none was invented.

## 15. Tenant isolation

The organisation always comes from the token.

Evidence:
- The rehearsal: "tenant B cannot read it" for all 11 generators.
- The E2E scenario: the other tenant cannot read the report and sees no IR8A.
- IR21 / IR8A / EZPay IDOR tests (cross-org read, transition and create refused).

## 16. Database migrations

**This tree:** single head **`445abd6a9083`**, 153 revisions. Branch points are identical to `origin/main`.

**R2 is now applied in-tree** (this pass). Main's `d4e5f6a7c8b9 → e7f1a2b3c4d5 → f0b1c2d3e4f5 → 998877665544` are carried **byte-identically** (same git blobs as `origin/main`), and `c3d9e1f4a7b2` now sits on `998877665544`:

```
… a5f6e7d8c9b0 → d4e5f6a7c8b9 → e7f1a2b3c4d5 → f0b1c2d3e4f5 → 998877665544
  → c3d9e1f4a7b2 → d4e8f2a6b9c1 → e5f9a3b7c2d4 → f6a1b4c8d3e5 → a7c2e9f4b1d6 → b8e3d5f2a9c7 → 445abd6a9083
```

Why this is safe:
- main's `f0b1` drops the `sgp_*` columns. As a parallel branch it could run *after* the Singapore chain; that was rehearsed, and 0 of 11 columns were left.
- A linear chain always adds them last.
- The identical migration files merge as no-ops. Only `test_alembic_metadata.py` will need the usual conflict resolution.
- Before this, the branch could not even upgrade the shared DB: it did not know revision `998877665544`.

**Guards:**
- Every `sgp_*` table and column must have a migration (`test_singapore_model_migrations.py`).
- Every Singapore migration is additive and inspector-guarded, so upgrade and downgrade are idempotent.

**From-zero PostgreSQL** (`alembic upgrade head` on an empty DB) **fails at US migration `71d815f06d78`**, which drops an index that only `create_all` bootstraps create. This is pre-existing, on main too, and outside Singapore; left for the US owner. Every real environment was bootstrapped with `create_all` and upgrades from its revision, which is what was rehearsed.

**Shared DB** (read-only, re-checked in the final execution pass; a brief that described it at `5ae06cfda828` / venu lineage is **stale**):
- revision `998877665544`;
- 146 tables;
- an orphan `sgp_ir21_cases` (0 rows, identical to the model);
- 0 `sgp_*` columns;
- `communication_events` present;
- **no Singapore service-registry row** (§7a).

**Rehearsed upgrade** on an exact schema copy:

| Item | Result |
|---|---|
| Migrations run | exactly 7 Singapore migrations (`f6a1` skips the existing table) |
| Tables added | `sgp_pwm_overtime_schedules`, `sgp_ir8a_modifications` |
| Columns added | 11 `sgp_*` |
| Indexes added | 8 |
| Removed | nothing |
| Drift | none |
| Head | `445abd6a9083` |
| Second run | no-op |

## 17. Deployment runbook

**The step-by-step production procedure is `docs/SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md`.**

It includes the verified constraint that no Singapore organisation — not even a Super Admin test tenant — can be created while the registry is `PLANNED`. The deploy owner therefore chooses between J-1 (verify on the restored copy) and J-2 (verify in the window right after `AVAILABLE`).

**`scripts/deploy_migrate.sh`** is main's current version (`75caa48`) plus a **safety fix**. It is shared deploy infrastructure, clearly marked in the file header, and needs deploy-owner review.
- **Defect (still on main):** in the orphan-revision path it "checked" drift by calling `migrations.sync_schema`, which runs `ALTER TABLE … ADD COLUMN` **before** refusing.
  - Rehearsal: main's script **refused yet added 11 columns**.
  - The next run then saw no drift and re-stamped over migrations that never ran.
  - It also ran `sync_schema` as a post-upgrade "safety-net", which can only hide a missing migration.
- **Fix:** both calls are replaced by the read-only `scripts.check_schema_drift`. The rest of main's logic is untouched, including the stamp-ancestor walk.
- **Rehearsal (fixed script):**
  - upgrade from `998877665544`: 7 migrations, exit 0;
  - orphan row + drift: refused, **schema unchanged**;
  - orphan row + matching schema: re-stamped, at head, no drift.
- **Tests:** `tests/test_deploy_migrate_script.py` (2 of 3 fail on main's script).

**Owner procedure** (never `alembic stamp`, never manual DDL):
1. **Backup / PITR point** of the target DB.
2. **Restore** it to a scratch instance.
3. On the copy, run `scripts/deploy_migrate.sh` from the merged tree. Expect exactly the 7 Singapore migrations, `Database is at the Alembic head.`, `No schema drift detected.`, and the §16 deltas.
4. Verify the application on the copy.
5. **Maintenance window** → run the same script on the real DB.
6. Verify: `alembic current` = `445abd6a9083`; drift check clean.
7. Seed the Singapore Draft data: `python -m scripts.seed_singapore_canonical_pack`, `python -m scripts.seed_statutory_report_templates`. Everything stays Draft.
8. **Rollback:** restore the backup. The Singapore migrations also have guarded downgrades, but the backup is the recovery path.

## 18. G1–G8

| Gate | Requirement | Authority | Evidence required | Current evidence | Missing | Owner | Status | Next action |
|---|---|---|---|---|---|---|---|---|
| G1 | CPF content certified | Independent reviewer; CPF Board sources | Signed comparison report | 37/37 golden; hashed sources; comparison pack doc | Reviewer + report | Statutory compliance owner | EVIDENCE_REQUIRED | Send the input pack to a reviewer |
| G2 | CPF operations | CPF Board (EZPay / Corppass) | Acknowledgement + payment reconciliation | Spec sample byte-exact; lifecycle; E2E file | Live submission | Employer payroll ops | EVIDENCE_REQUIRED | Run with the G8 partner |
| G3 | IRAS AIS | IRAS | Mode decision; acknowledged original + modification | Extract, lifecycle, revision/amendment, error capture | D1; IRAS acknowledgement; APEX if API | Product owner | BUSINESS_DECISION_REQUIRED | Decide D1 |
| G4 | IR21 | IRAS | Guidance review; acknowledged filing | Lifecycle, hold, register | Review + filing | Statutory compliance owner | EVIDENCE_REQUIRED | Review against IRAS guidance |
| G5 | Foreign workforce | MOM | Levy-bill reconciliation; published values | PWM 6,132 cells; levy / LQS / PWM tests | Real levy bill; unpublished values; quota data | Statutory compliance owner | EVIDENCE_REQUIRED (partly BLOCKED) | Obtain values or a signed scope-out |
| G6 | Labour pay | MOM / counsel | Legal memo | Employment Act rules | Legal review | Legal + compliance | EVIDENCE_REQUIRED | Commission a review |
| G7 | Security / privacy | PDPC (DPO) | DPO sign-off; security review; recovery test | §14 controls + tests | Reviews + recovery test | DPO + security | EVIDENCE_REQUIRED | Schedule the reviews |
| G8 | Parallel payroll | Design-partner employer | Reconciliation report | Rehearsal 172/0; E2E 32/0 | Partner + DPA | Implementation lead | EVIDENCE_REQUIRED | Select a partner |

## 19. Remaining external dependencies

- **G1–G8 evidence** (§18).
- **AIS-API 2.0:** specification, APEX onboarding, Corppass, credentials, sandbox.
- **Unpublished MOM values** — each stays BLOCKED, not invented:
  - the Work Permit levy before 24 Sep 2026 outside construction (MOM's sector pages state no effective date for the current rates);
  - the pass **expiry** end-day basis (`fwl_s_pass_end_day_basis` / `fwl_work_permit_end_day_basis`). The **cancellation** rule is sourced — see §24.3.
- **MOM quota data** for the LQS quota. Public MOM material exists (sector quota ceilings; a guide on computing quota balance) but has not been registered or verified, and quota computation is not a payroll duty. It stays `EXTERNAL_DATA_REQUIRED`, with a scope decision needed.
- **Retail PWM 3-month averaging:** **IMPLEMENTED (final closure)**. SG-PWM-COMPLIANCE evaluates a retail shortfall against Annex D (§1–4, footnote 2). It reads each month's own payslip, which now records its PWM classification (`pwmClassification`): job level, gross wages paid including overtime, and the MOM Gross Wage Requirement for the month's overtime hours (0 hours = the retail PWM wage). The result is `MET_BY_AVERAGING` when the 3-month totals meet the requirement. Months 1–2 of employment are never averaged; an incomplete first month is pro-rated by the MOM incomplete-month formula. The monthly check itself now also uses the payslip's own classification, so regenerating a report after a role change is deterministic. Not evaluated (the shortfall stays flagged, never assumed met): part-time months, incomplete months other than the first, and payslips calculated before this release. Tests: `test_singapore_pwm_retail_averaging.py` (14).
- **Not implemented, pending an external specification or data:**
  - AIS record fields beyond myTax Portal entry;
  - Appendix 8B;
  - Form IR21 content extract;
  - EZPay codes 07 / 10;
  - voluntary / excess CPF.

## 20. Business decisions

| # | Decision | Options | Current |
|---|---|---|---|
| D1 | IR8A / AIS submission mode offered by the product | EXPORT_ONLY · API_SUBMISSION · BOTH | Export built; nothing chosen |
| D2 | Singapore hotfix policy | RESTRICTED · PROHIBITED · FOLLOW_UP_REQUIRED (all enforced) | `RESTRICTED` = the behaviour in force; not chosen |
| D3 | Scope of the Singapore-only governance controls | SG only · all countries | SG only. Phase 6.0 showed that a universal rule broke 52 Germany/shared tests. |

The deploy-script fix (§17) is a **deploy-owner review item**, not a business choice.

## 21. Test evidence (commands run 2026-09-29)

| Command | Result |
|---|---|
| `python -m pytest tests/ -q` (baseline, start of the completion programme) | 3,188 passed, 7 skipped |
| `python -m pytest tests/ -q` (end of the completion programme) | 3,226 passed, 7 skipped |
| `python -m pytest tests/ -q` (**final**, final closure + real-organization validation) | **3,308 passed, 7 skipped, 0 failed**. Adds 3 pack-clone tests and 2 evidence-refusal-audit tests; Singapore group 823 passed, 2 skipped. |
| Real-organization functional validation (disposable PostgreSQL, 3 tenants, 4 payroll cycles, 11 reports, HTTP isolation) | **44 PASS / 0 FAIL**. See `SINGAPORE_REAL_ORGANIZATION_VALIDATION.md` |
| Real-browser UI check (Chrome/Playwright, real login, every Singapore tab, 11 templates + lifecycle, server-refused illegal transition) | **20 PASS / 0 FAIL**. Same document |
| Earlier: final closure | 3,303 passed, 7 skipped, 0 failed. Adds 14 retail-averaging tests and 1 AIS-boundary test; every averaging test reads a row key or helper that did not exist before (the pre-change report had no `averaging`). Singapore group: 818 passed, 2 skipped. |
| Earlier: release-closure pass | 3,288 passed, 7 skipped, 0 failed. Adds 9 evidence-lifecycle / decision / route-sweep tests; the 8 lifecycle and decision tests call functions and routes that did not exist before this pass. Singapore group: 803 passed, 2 skipped (the PostgreSQL-only Phase 6.0 check, run separately on a disposable DB: pass; the intentionally empty golden sample slot). |
| Earlier: final completion programme | 3,279 passed, 7 skipped, 0 failed (+9 multi-pack report tests, +2 seed-idempotency tests; 7 of the 11 fail on the pre-change code) |
| Earlier: evidence-gate closure pass | 3,268 passed, 7 skipped, 0 failed (+3 evidence-supersession tests; all 3 fail with the change removed) |
| Earlier: final closure pass | 3,265 passed, 7 skipped, 0 failed (+2 evidence-integrity tests; both fail with the fix removed) |
| Earlier: evidence & activation pass | 3,263 passed, 7 skipped, 0 failed (+7 pass-cancellation tests + 1 golden vector) |
| Earlier: production-closure pass | 3,255 passed, 7 skipped, 0 failed (+7 evidence-registry tests) |
| New closure tests on the pre-pass code | 11 of 13 fail |
| `test_deploy_migrate_script.py` on main's script | 2 of 3 fail |
| PostgreSQL activation rehearsal (shared-schema copy + fixed deploy) | 172 PASS / 0 FAIL / 0 BLOCKED / 1 INFO |
| PostgreSQL end-to-end product scenario | 32 PASS / 0 FAIL |
| Upgrade from the shared DB revision | §16 |
| Deploy-script rehearsal | §17 |
| From-zero `alembic upgrade head` | fails at US `71d815f06d78` (pre-existing, non-Singapore) |
| ESLint, 15 Singapore frontend files | exit 0 |
| `vite build` | exit 0, 2,703 modules |

Singapore suites:
- `test_singapore.py` 476
- golden 37
- phase 5.6 / 5.7 / 5.8 / 6.0: 34 / 23 / 21 / 15
- phase 6.3 / 6.4 / 6.5 / 6.6 / 6.7 / 6.8: 25 / 3 / 22 / 12 / 4 / 17
- completion 36
- **final closure 19**
- **evidence registry 12** (7 + 2 integrity + 3 supersession)
- **retail PWM averaging 14** (`test_singapore_pwm_retail_averaging.py`)
- **AIS-API boundary 1** (`test_the_ais_api_boundary_is_an_explicit_checklist_and_nothing_can_submit`: six prerequisites, none claimed, no credential configured, no submit path)
- **pack version clone 3** (`test_singapore_pack_version_clone.py`)
- **evidence lifecycle 11**: adds refused-review audit rows for Singapore evidence (self-review on both review paths, review or upload after a rejection, replacing a completed review), with other countries' Source Evidence unchanged (`test_singapore_evidence_lifecycle.py`: full lifecycle and fields, expiry, rejection is final, review refusals, structured decision, memo without option, 2 new routes Super Admin-only, sweep of every SG governance route)
- **seed idempotency 2** (`test_singapore_seed_idempotency.py`: a re-run keeps every row id; an edited Draft row is restored by replacing only that row)
- **multi-pack reports 9** (`test_singapore_multi_pack_reports.py`: generic generator × 5 SG report types, single-pack control, PWM, LQS, IR21 register; the 5 generic cases fail on the pre-change code)
- model ↔ migration 2
- **deploy script 3**
- alembic metadata 6

## 22. Production readiness

**Classification: A — ENGINEERING + CONFIGURATION COMPLETE, external activation pending.**

**Ready / verified:**
- engine;
- configuration;
- PWM;
- the 11 templates and 12 generators;
- governance;
- security and isolation;
- replay;
- seeds;
- migrations (in-tree R2);
- deploy safety fix;
- Super Admin UI.

**Configuration required at deployment:**
- per-organisation UEN, CSN, AIS participation / mode, Corppass flag and MOM sector (Company compliance);
- the Singapore Draft seeds, followed by governed activation.

**External evidence required:** G1–G8.

**Business decision required:** D1, D2, D3.

**External data required:**
- unpublished MOM values;
- quota data.

**Not implemented:** §19's pending-specification items.

## 23. Exact deployment sequence

1. Review this working tree (§25). Commit and push `nikhil`.
2. Open the PR `nikhil` → `main`.
   - Resolve conflicts in `payroll/service.py`, `payroll/router.py`, `super_admin/router.py`, `tests/test_alembic_metadata.py` (keep head `445abd6a9083`, 153 revisions) and `scripts/deploy_migrate.sh` (keep this branch's version).
   - The 4 carried migration files are identical to main's, so they won't conflict.
3. On the merge result, run `python -m alembic heads` (one head, `445abd6a9083`) and the full suite.
4. Complete deploy-owner review of the `deploy_migrate.sh` safety fix.
5. **A merge to `main` auto-deploys:** complete §17 steps 1–4 on a restored copy *before* merging.
6. Merge in the maintenance window, then §17 steps 5–7.
7. Keep Singapore `PLANNED` in the service registry until G1–G8 and D1–D3 are satisfied. Then:
   - governed pack activation (B approves, C activates);
   - template promotion.

## 24. Definition of Done

### 24.1 Checklist

**Engineering items — all met:**
- statutory engine;
- canonical configuration;
- CPF, SDL, SHG, FWL (published values), LQS floor, PWM;
- IR8A, IR21, EZPay;
- AIS architecture;
- replay and snapshots;
- the 11 templates and 12 generators;
- template and pack lifecycle;
- maker-checker, refusal audit, hotfix switch;
- Super Admin configuration, readiness and template UI, and the PWM view;
- RBAC, isolation, masking;
- seeds idempotent, never demoting;
- alembic single head with R2 in-tree;
- deploy safety;
- PostgreSQL rehearsals;
- lint and build;
- full regression;
- documentation and manifest;
- G1–G8 documented.

**Not met, by design (external / decision):**
- LQS quota (external data);
- AIS-API (external + D1);
- hotfix policy choice (D2);
- G1–G8 evidence.

**Safety:** no production or shared DB modified (read-only inspection and schema-only dump only); no commit, push, merge or deploy.

### 24.2 Gap closure — this pass

| # | Initial gap | Result |
|---|---|---|
| 1 | Branch unaware of `998877665544`; R2 was a manual merge step | CLOSED — carried byte-identically, re-parented in-tree |
| 2 | Deploy script mutates the schema before refusing (still on main) | CLOSED — fixed + rehearsed + tested (deploy-owner review) |
| 3 | Hotfix policy implicit | CLOSED — explicit switch, all options enforced; choice = BUSINESS DECISION |
| 4 | AIS mode not visible to Super Admin | CLOSED — setting + option states (no tenant data) |
| 5 | Authority rejection errors not captured | CLOSED |
| 6 | 200-record batching count-only | CLOSED |
| 7 | Stale IR8A guard message | CLOSED |
| 8 | Void refusals unaudited | CLOSED |
| 9 | LQS quota only a text flag | CLOSED as fail-safe readiness; the computation is EXTERNAL DEPENDENCY |
| 10 | CPF wage thresholds hard-coded in React | CLOSED |
| 11 | FWL tab said Work Permit rows not configured | CLOSED |
| 12 | G1–G8 duplicated in React | CLOSED — backend single source |
| 13 | No unified readiness view; service availability not shown | CLOSED — Readiness & Operations tab |
| 14 | PWM stale rows while loading; no exact-role filter | CLOSED |
| 15 | No end-to-end correction → regeneration → historical rehearsal on PostgreSQL | CLOSED (16/0) |
| — | From-zero migration | EXTERNAL (US migration, pre-existing) — documented |
| — | AIS-API, quota data, G1–G8, D1–D3 | EXTERNAL DEPENDENCY / BUSINESS DECISION |

## 25. File manifest (working tree vs HEAD `264c585`)

### A. Singapore production files

| File | Change |
|---|---|
| `backend/alembic/versions/445abd6a9083_create_sgp_ir8a_modifications.py` | **new** |
| `backend/alembic/versions/c3d9e1f4a7b2_add_singapore_cpf_employee_columns.py` | R2 re-parent |
| `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory/ezpay.py` | ASCII / 150-byte check |
| `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory_summary.py` | operations, gates, capabilities, template evidence |
| `frontend/src/components/jurisdiction/singapore/SGReadinessTab.jsx` | **new** |
| `frontend/src/components/jurisdiction/singapore/SGOverviewDashboard.jsx`, `SGStatutorySummaryTab.jsx`, `SGReportTemplatesTab.jsx`, `SGStatutoryComponentsTab.jsx`, `SGBandFormModal.jsx`, `SGPwmSchedulesTab.jsx`, `sgComponentConfig.js` | — |
| `frontend/src/pages/JurisdictionCompliance/SGCompliancePage.jsx` | — |
| `frontend/src/modules/payroll/Compliances/SGOperationsCards.jsx` | — |

### B. Shared files with Singapore / cross-jurisdiction hunks (review hunk by hunk)

- **`backend/app/modules/payroll/service.py`**
  - SG-scoped: pack graph; released approval; hotfix review audit; hotfix policy; template approve / delete guards; SG report helpers; PWM / LQS pinned pack; supersession / audit / void; EZPay / IR21 / IR8A fixes; summary facts.
  - **Cross-jurisdiction:** `find_jurisdiction_pack_upsert_target` + pack-type immutability (security); optional status `reason` (additive; hotfix now records its incident as the reason for all countries); `list_report_templates` id tie-breaker; **`_clone_pack_rates` copies every value column** (final closure, found by the real-organization validation). Before this fix, a new pack version, which is the documented correction path, dropped `effective_from` / `effective_to`, `source_document_id` and `TaxSlab.assessment_basis`. The effect for every country was that effective-dated rows became open-ended and sources were lost. For Singapore, every CPF band was also blocked, so there was no payroll under a new version. Tests: `test_singapore_pack_version_clone.py` (3, including a US pack; all 3 fail on the pre-change code). **`generate_report_from_template` `taxPacksUsed` is now `sorted(...)`** (was `list(set)` — its order followed insertion when pack ids collide in the set's hash table, e.g. 1001 / 1009, so a regenerated multi-pack report was not deterministic; the list's contents are unchanged, only its order; no other country's test depends on it).
- **`backend/app/modules/payroll/router.py`** — org pack-route tax guard (all countries); `errors` passed to the SG transition routes.
- **`backend/app/modules/payroll/engine/tax_resolver.py`** — SG opt-in: a missing registry row blocks onboarding (§7a); other countries unchanged.
- **`backend/scripts/seed_singapore_canonical_pack.py`** — SG registry row, insert-if-missing only; **`_reconcile_pack_rows`** (final completion programme): the Draft pack's rates / slabs are no longer bulk-deleted and re-inserted on every run — existing rows holding the canonical values are kept (same id, no UPDATE), only differing rows are replaced, and the seed's audit row records `rowChanges`. SG-only script.
- **`backend/app/modules/payroll/schemas.py`** — optional `errors` on the SG transition request.
- **`backend/app/modules/super_admin/router.py`, `schemas.py`** — `reason`, `actor_id` (additive); `PUT /compliance/source-artifacts/{id}/supersede` + `SourceArtifactSupersede` (new route; refuses anything that is not `SG-GATE-*` / `SG-DECISION-*` evidence).
- **`frontend/src/service/payrollService.js`** — `generateSgIr8a`, `createSgIr8aModification` only.
- **Frontend: shared, additive, opt-in (final closure, from the real-browser check):**
  - `components/jurisdiction/JurisdictionLayout.jsx`: `autoSelectPack` prop, unset for every other country;
  - `components/reportTemplates/ReportTemplateLayout.jsx`: `embedded` prop (hides the page header only);
  - `App.jsx`: two `/super-admin/report-templates/singapore` routes;
  - `pages/ReportTemplates/index.js`: the `SG` map entry and export.
  - Lint error counts in these files equal HEAD's, so no new problem was introduced.
- **Carried byte-identically from `origin/main`:**
  - `backend/alembic/versions/d4e5f6a7c8b9_create_auth_email_events_table.py`
  - `backend/alembic/versions/e7f1a2b3c4d5_create_communication_events_table.py`
  - `backend/alembic/versions/f0b1c2d3e4f5_drop_orphan_sgp_columns.py`
  - `backend/alembic/versions/998877665544_drop_orphan_ie_fr_columns.py`
- **`scripts/deploy_migrate.sh`** — main's version + the safety fix. **Deploy infrastructure.**

### C. Tests

- **New:**
  - `test_singapore_completion_programme.py`
  - `test_singapore_final_closure.py`
  - `test_singapore_model_migrations.py`
  - `test_deploy_migrate_script.py`
- **Updated:**
  - `test_alembic_metadata.py`
  - `test_singapore_phase56_admin.py`
  - `test_singapore_phase58_lifecycle.py`
  - `test_singapore_phase63_hardening.py`

### D. Documentation

This file.

### E. Unrelated — exclude

Pre-existing, not made by either programme:
- `backend/.env.example` and `backend/app/config.py` (CORS);
- `frontend/src/components/Modal.jsx`, `SuperAdminShell.jsx` and `frontend/src/modules/payroll/index.jsx` (shared a11y);
- untracked `docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md`.

### F. Germany — exclude

- `backend/scripts/seed_statutory_report_templates.py` — 3 Lohnsteuer + Soli label hunks; no Singapore hunk.
- `backend/tests/test_germany_report_templates.py`.
- Untracked `docs/GERMANY_*.md` and the Germany `.docx`.

### G. Other jurisdictions

None changed. The only non-SG code touched is the cross-jurisdiction security / ordering listed in B, and the 4 migrations carried from main.

### 24.3 MOM statutory-data closure (evidence & activation pass, 2026-09-29)
Official MOM sources were re-checked. Everything was retrieved 2026-09-29, and each SHA-256 is of the retrieved file.

| Item | Status | Source | Change |
|---|---|---|---|
| Pass end day on **cancellation** | **AVAILABLE** | MOM "Cancel an S Pass" (last updated 15 Sep 2025, `5c71ac70…`): "When levy stops: 1 day before cancellation". MOM "Cancel a Work Permit" (last updated 5 Aug 2026, `2bc8e148…`): "Your worker's levy will be charged until 1 day before the pass cancellation". | Two sources registered. Draft rows `fwl_s_pass_cancellation_end_day_basis` and `fwl_work_permit_cancellation_end_day_basis` = `EXCLUSIVE`. New employee field `work_pass_end_reason` (`CANCELLED` / `EXPIRED`, stored in compliance fields, no migration). Engine `SG-2026.10` applies the rule only to `CANCELLED`. New golden vector `wp_services_tier2_cancelled_mid_month` (14 × S$19.73 = S$276.22). |
| Pass end day on **expiry** | EXTERNAL_DATA_REQUIRED | Not stated on either page | None — an expiry, or no recorded reason, mid-month still BLOCKS |
| Part-time LQS before 1 Jul 2026 | **AVAILABLE** (already sourced) | MOM COS 2024 factsheet (`mom_cos2024_foreign_workforce`) | Stale "unpublished" wording removed from the seed docstring, change summary and readiness list |
| Work Permit levy before 24 Sep 2026, outside construction | EXTERNAL_DATA_REQUIRED | The MOM services sector page (re-read) states **no effective date** for the current rates; a future merge "from 2028" is noted | None |
| MOM quota tables | EXTERNAL_DATA_REQUIRED | Public material exists but has not been registered or verified; computing quota is not a payroll duty (MOM computes it) | None — needs a scope decision |
| Retail PWM 3-month averaging | **AVAILABLE, IMPLEMENTED** | MOM Tripartite Cluster for Retail report (PDF metadata 15 Aug 2025, `4931930b…`), Annex D, paras 1–4 and footnote 2 | **IMPLEMENTED (final closure)**. SG-PWM-COMPLIANCE evaluates a retail shortfall against Annex D (§1–4, footnote 2). It reads each month's own payslip, which now records its PWM classification (`pwmClassification`): job level, gross wages paid including overtime, and the MOM Gross Wage Requirement for the month's overtime hours (0 hours = the retail PWM wage). The result is `MET_BY_AVERAGING` when the 3-month totals meet the requirement. Months 1–2 of employment are never averaged; an incomplete first month is pro-rated by the MOM incomplete-month formula. The monthly check itself now also uses the payslip's own classification, so regenerating a report after a role change is deterministic. Not evaluated (the shortfall stays flagged, never assumed met): part-time months, incomplete months other than the first, and payslips calculated before this release. Tests: `test_singapore_pwm_retail_averaging.py` (14). |

**Resulting counts:**
- 55 source artifacts (was 53);
- 596 SG contribution rates (592 + 2 rows × 2 packs);
- **37 golden vectors** (was 36).

## Final completion programme — PWM query evidence (2026-09-29, disposable PostgreSQL, 6,132 rows)

| Query (`list_sg_pwm_schedules`) | SQL statements | Median | Plan |
|---|---|---|---|
| First page (50) | 2 (count + page) | 8.6 ms | bitmap index scan |
| Sector RETAIL + OT 10 | 2 | 2.5 ms | index scan `uq_sgp_pwm_ot_schedule_row` |
| Search 'cashier' | 2 | 11.0 ms | bitmap index scan |
| In force on 2026-09-25 | 2 | 7.0 ms | bitmap index scan |
| Last page (skip 6,100) | 2 | 26.0 ms | bitmap index scan (offset cost) |

No per-row lookups; no new index is justified by this evidence, so none was added.
