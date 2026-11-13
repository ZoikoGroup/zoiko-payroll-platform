# Belgium (BE) — Gaps and Decisions Register

Spec: docs/belgium/Zoiko_Payroll_Belgium_Engineering_Implementation_Wireframe_v1.0.docx (ZP-BE-ENG-001 v1.0, authoritative; file name kept as-is)
Plan: docs/belgium/BELGIUM_IMPLEMENTATION_PLAN.md
Created: Phase 0, 2026-11-11, against commit 1af3d44 (branch nikhil). Alembic head: efc56f3235e2.

This register is authoritative for open gaps and approved decisions. A gap is closed only by recorded evidence (signed content, specialist confirmation or an approved decision), never by an engineering assumption.

## Gaps

| ID | Status | Description |
|---|---|---|
| G-01 | OPEN | Calculation order not consolidated in the spec; the derived order in plan §8 needs Belgian specialist confirmation. |
| G-02 | OPEN | No rounding rules in the spec. |
| G-03 | OPEN | Annex III professional-withholding tables / formulas absent. |
| G-04 | OPEN | Work-bonus (social and fiscal) parameters absent. |
| G-05 | OPEN | Wage-moderation, 1.60% special-contribution threshold and fund rates absent. |
| G-06 | OPEN | Special social security contribution (BSSC) not mentioned in the spec. |
| G-07 | OPEN | Manual-worker guaranteed-salary day bands absent. |
| G-08 | OPEN | ONSS rate files and authority schemas (Dimona, DmfA, FinProf, Belcotax) are external. |
| G-09 | OPEN | Public-holiday dates and substitution rules absent. |
| G-10 | OPEN | Index-centime mechanics unspecified. |
| G-11 | OPEN | Pay-frequency scope not defined. |
| G-12 | OPEN | Definition of "high-risk" change for four-eyes not defined. |
| G-13 | OPEN | Legal language rules (nl/fr/de for employment documents) not defined. |
| G-14 | OPEN | Spec /be/ API paths vs repository route convention (resolved in practice by D4). |
| G-15 | OPEN | Benefit-in-kind, meal-voucher and ecocheque values absent. |
| G-16 | OPEN | KBO/BCE, ONSS and NISS format / check-digit rules unverified. |
| G-17 | OPEN | (D7) BSSC has no spec requirement ID. Its content key must reference "external specialist confirmation, G-06", not a BE-xxx ID. The engine only emits the BE_BSSC_PENDING exception and never computes it. |
| G-18 | DECIDED + DELIVERED (Block B3, user decision 2026-11-12: BE hook, like CH; recorded in Block D1) | The shared run lifecycle (service.advance_payroll_run_status) is untouched; Belgium enforces both controls in its before_run_transition hook (backend/app/modules/payroll/belgium_service.py). **Four-eyes for high-risk changes:** (1) run commit (Review -> APPROVED): approver != run preparer (run.created_by) and != any creator of a Belgian input the payslips use (_input_creators: worker profiles, schedules, classifications, component mappings, absence episodes, holiday certificates, employer registration, approved declarations in force); every BLOCK item of be_run_preflight cleared (incl. accepted Dimona IN since Block C1); engine exceptions need an audited per-employee acknowledgement (acknowledge_be_run_exception); (2) every Belgian statutory record version is approved by a second user via the shared require_four_eyes (approve_* functions) and a DB CHECK (approver <> creator); (3) AUTHORIZED needs a user other than the approver; (4) payment batches, filings, obligation reconciliation, variances and parallel cycles are four-eyes (belgium_payment_service.approve_payment_batch, belgium_filing.approve_be_filing / reconcile_be_obligation / resolve_be_variance, belgium_parallel.accept_be_parallel_difference / accept_be_parallel_import). **Commit idempotency:** be_approval_fingerprint (sha256 over every BE payslip's frozen hashes + net pay) is stored at APPROVED in payroll_runs.be_approval_fingerprint; AUTHORIZED / PAID re-verify it (any change after commit refuses); a retried approval cannot advance the run twice (AUTHORIZED needs another person); post_be_accumulators is idempotent per payslip + accumulator + entry kind (and a DB unique index refuses a second RUN entry). **Tests:** tests/test_belgium_run_lifecycle.py::test_approval_needs_a_clear_preflight_and_acknowledged_exceptions, ::test_a_creator_of_the_inputs_cannot_approve, ::test_a_retried_approval_never_advances_twice_and_the_fingerprint_guards_authorization, ::test_a_non_belgian_run_is_untouched_by_the_belgian_hook, ::test_no_approval_without_an_accepted_dimona_in; tests/test_belgium_filing.py::test_the_filing_state_machine_and_four_eyes, ::test_the_database_refuses_an_approval_by_the_creator. |
| G-19 | OPEN (expected) | (D8) be_rounding_* rows have no published source and stay blocked until a specialist signs them. This is expected. |
| G-20 | OPEN | The spec §3 figures are Draft seed content only, labelled "[PENDING G1]", and are never used as code constants. |
| G-21 | OPEN | Belgian statutory retention periods for payroll/social documents not in spec; BE employee deletion blocked until specialist-approved retention rules exist. |
| G-22 | DECIDED (2026-11-12, Block B) | Pay basis: use an existing salaried-vs-hourly field on payroll_employees / its salary structure if one exists; otherwise add `pay_basis` (CHECK SALARIED / HOURLY, nullable; NULL blocks) to payroll_be_worker_profiles in migration be_absence_holiday_payment. The A3 end-to-end test shortcut is removed once a real source exists. |
| G-23 | DECIDED (2026-11-12, Block B) | Engineering vocabulary for `be_supported_contract_types`: INDEFINITE, FIXED_TERM, SPECIFIC_WORK, REPLACEMENT, STUDENT, FLEXI, OCCASIONAL, APPRENTICESHIP, NOT_SUPPORTED; the specialist signs the supported subset. `contract_type` (CHECK same list, nullable; NULL blocks), `contract_start_date`, `contract_end_date` (end >= start) added to payroll_be_employment_classifications. The resolver blocks a NULL contract type or one outside the signed list (contract type no longer comes from PayrollEmployee.employment_type). Block C Dimona events use the dates. |
| G-24 | DECIDED (2026-11-12) | No change: any non-NULL special_status blocks. |
| G-25 | DECIDED (2026-11-12, Block B) | `onss_special_160_status` (CHECK APPLIES / NOT_APPLICABLE / UNKNOWN, default UNKNOWN) + `special_160_evidence_ref` on payroll_be_employer_registrations, set through the four-eyes registration versioning. UNKNOWN blocks; the 1.60% line is applied only when APPLIES (the rate stays content). The `be_onss_special_160_threshold_rule` vocabulary blocker is removed. |
| G-26 | DECIDED (2026-11-12) | Stays pending content (blocks). No change. |
| G-27 | DECIDED (2026-11-12) | Release-1 scope, all fail-closed with explicit blocking reasons: exactly one Active employment line per employee per pay period (more blocks); residents only (NON_RESIDENT blocks); structural / target-group reductions and company car block whenever applicable; sector minimum and holiday engines are built in Block B. |
| G-28 | DECIDED (2026-11-12, Block B) | Pay components: map through an existing platform component category / code if one is usable; otherwise payroll_be_component_mappings (org-scoped, platform component -> BE component code from the content vocabulary, versioned, four-eyes, RLS) with org CRUD + UI. An unmapped component blocks (BE-008). Dependants only from APPROVED declarations. Exceptional reference pay and pension premium stay pending content. |
| G-29 | DECIDED (2026-11-12, Block B3) | Ledger posting moves to run commit (the approval transition in before_run_transition): entries exist only for committed runs; corrections after commit post CORRECTION entries; generation / regeneration of draft runs posts nothing. The B3 run approval replaces the Phase 1 refusal. |
| G-30 | ENGINEERING DEFAULT (2026-11-13, Block C1) — confirm | Professional-withholding declaration frequency vocabulary: MONTHLY or QUARTERLY on the employer registration; anything else (or empty) blocks the FinProf build (BE-013 never assumed). The specialist confirms the set of frequencies the release supports. |
| G-31 | OPEN (content, Block C1) | Authority schema registry: be_filing_dimona / dmfa / finprof / belcotax_schema_versions (new slab kind "schema-version": one signed row per version, window = SUBMISSION dates). Seeded pending; the DmfA spec proposal (2026/2 to 30 Sep, 2026/3 from 1 Oct) is shown in the label only. A schema is "archived" only when the signed row's reviewed source artifact holds the XSD file with a matching SHA-256. No mapping of the canonical payload onto any official schema exists (belgium_filing.RENDERERS is empty): every filing stays DRAFT ("no mapping") until the specialist supplies the mapping and codes (part of G-08). |
| G-32 | OPEN (content, Block C1) | Authority calendar rows (BE-035) are NOT seeded: payroll_statutory_filing_calendar.due_date cannot hold a pending value, so a seeded row would put a statutory date in code. The Super Admin enters each row (report types BE_DMFA, BE_FINPROF, BE_BELCOTAX, BE_ONSS_ADVANCE, BE_HOLIDAY_FUND; period keys YYYYQn / YYYY-MM / YYYY) with a source and activates it; the spec's 2026/Q3 operational date (30 Oct 2026) is entered that way. Without an Active, sourced row a due date stays "not sourced" (exception queue). |
| G-33 | OPEN (content, Block C1) | DmfA worker / remuneration / contribution codes, FinProf nature-of-income codes and Belcotax box codes: payloads carry "coding": "PENDING_CONTENT"; part of G-08. |

## Decisions

| ID | Status | Description |
|---|---|---|
| D1 | DECIDED | Poland (ZP-PL-ENG-001) generation-2 pattern. |
| D2 | DECIDED | Dedicated payroll_be_* tables (no be_* columns on payroll_employees or payroll_employee_statutory_profiles). |
| D3 | DECIDED | Joint Committee / CBA packs reuse payroll_collective_agreements. |
| D4 | DECIDED | Routes under /api/payroll/belgium and /api/super-admin/compliance/belgium; spec simulate/commit map onto preview_payroll_run and the run lifecycle. |
| D5 | DECIDED | Thin BE frontend files using the shared JP/NZ helpers. |
| D6 | DECIDED | First scope = private-sector ordinary payroll; special regimes and termination block. |
| D7 | DECIDED | BSSC not implemented; pending content key + exception, awaiting specialist confirmation (see G-17). |
| D8 | DECIDED | Rounding as signed pack text rows (be_rounding_*), blocking until signed (see G-19). |
| D9 | DECIDED | Authority transmission adapters stubbed behind gate G3; builders + validation built. |
| D10 | DECIDED | English operator payslip first; nl/fr/de as content keys. |
| D11 | DECIDED | Roadmap P1–P10 (plan §9). |
| D12 | DECIDED | External statutory content supplied by a Belgian specialist. |
| D13 | DECIDED | payroll_be_payment_batches / _items mirroring the Netherlands tables, using bank_export/sepa_pain001.py unchanged. |
| D14 | DECIDED | be_identifiers.py with its own BE_IDENTIFIER_KEYRING / BE_IDENTIFIER_FINGERPRINT_KEY settings. |
| D15 | DECIDED | Employer substitute holidays stored in payroll_holidays with category "Substitute", audited via payroll_tax_configuration_audit. |

## Notes

- (Phase 1) Lowercase "be" resolves to BE through the shared case-insensitive code match in core.jurisdiction.get_jurisdiction_code (same as every country, e.g. "pl" -> PL). There is no bare "be" name alias.
- (Phase 1) The BE schema examples ("0123.456.789", "1234567-89") are input-shape examples required by the shared validator (validate_tax_identifiers quotes them in its format message), not verified formats. G-16 stays open.
- (Phase 1) Frontend production build not verified in Phase 1 (vite build runs out of memory on the development machine). It must be verified before Phase 3.
- (Phase 1) Backend tests ran on Python 3.11. The project requires 3.12+; the environment must be fixed before Phase 5.
- (Phase 2) Phase 2 RLS/PostgreSQL round trip not yet run (Docker unavailable); must pass via CI or native PostgreSQL before Phase 4.
- (Phase 3A, Phase 5 requirement) The shared rate resolver (engine/tax_resolver._resolve_uncached, used by service._resolve_effective_rate_inputs) selects each ContributionRate / TaxSlab row by its OWN effective_from / effective_to at the run's payroll date. Mid-year changes keyed to pay date therefore work through the shared rate map; multi-row access (BePack accepting several dated rows per key) is needed only for source-period rules (BE-009).
- (Phase 3A) Joint Committee CBA packs: agreement_code (BE-PC-<committee>[-<sub>]-<version>) is the single source of truth, validated in a BE-guarded branch of service.upsert_collective_agreement; employee_group keeps its existing meaning. No generic matcher attaches an agreement to an employee (every reader filters by its own country); Belgium links explicitly via payroll_be_employment_classifications.collective_agreement_id.
- (Phase 3A) onss_employer rate / band labels carry the marker "ref. only (BE-015/BE-019)" (the full statement does not fit the 100-character label next to the spec-proposed text); every API view of those rows returns referenceOnly=true and referenceNote = "reference only; resolved by employer category and worker code (BE-015/BE-019)".
- (Phase 3A) Band / formula / table content (TaxSlab rows of each key's rule type, e.g. BE_PUBLIC_HOLIDAY) cannot yet be ENTERED through the console: Phase 3A only edits and signs existing rows. Until a governed "add slab row" action exists (Phase 6 for public holidays), those keys can only be signed NOT_SUPPORTED.
- (Phase 3B) formula_expression for BE keys is stored as specialist-entered text. Phase 5 must define a restricted expression grammar with a parser/whitelist. Python eval/exec on stored text is forbidden (tests/test_belgium_slab_rows.py asserts no belgium*.py / be_*.py file calls eval or exec).
- (Phase 3B) Band dimensions are stored in payroll_tax_slabs.filing_status ONLY for BE_* rule types, as "NAME=value;NAME=value" (EC / WC for ONSS employer bands, validated against the signed be_onss_supported_employer_categories / be_onss_supported_worker_codes lists; CHILDREN for multiple-birth maternity). Every reader of TaxSlab.filing_status was reviewed: none selects or filters BE_* rows (country engines read only their own packs; sync_org_rates_from_canonical copies verbatim and BE is canonical-pack-only; the generic matcher shared._calculate_annual_tax is unreachable for BE). BePack.band() never falls back to a dimensionless row.
- (Phase 3B) Slab-row retire is a hard delete on Draft packs only; the audit before-image keeps every value field, dates, source, signed state and signer.

- (Block B, 2026-11-12, user decision) G-18: the shared run lifecycle enforces neither commit idempotency nor
  four-eyes. Belgium gets both inside its own before_run_transition hook (like Switzerland): approver differs
  from the run preparer and from anyone who created the payslips' inputs; the approval fingerprint is
  re-verified at Authorize / Paid; ledger posting is idempotent per payslip + accumulator (database unique
  index). The shared lifecycle is not changed.
- (Block B, 2026-11-12, user decision) Sector wage scales reuse payroll_collective_agreements.modules (the
  Swiss wage-floor precedent stores a dict there): modules = {"wage_scales": [rows by function class,
  seniority and schedule regime]}, written by a Belgium-only Super Admin route on Draft agreements; the
  existing agreement four-eyes approval / activation applies. No new table.
- (Block B) G-27 reductions: the signed marker of be_red_structural / be_red_target_group decides
  applicability — SLAB_ROWS = applies (blocks: not built), NOT_SUPPORTED = recorded as not applied, unsigned
  blocks as pending. Benefits in kind (incl. company car) block whenever a BENEFIT_IN_KIND component is paid.
- (Block B) G-28: no platform component category exists (payroll_policy_allowance_components.key is a free
  slug), so payroll_be_component_mappings maps PLATFORM_FIELD (basic, hra, special_allowance, overtime,
  additional_compensation) and POLICY_ALLOWANCE (allowance key) to the BE component vocabulary.
- (Block B) G-22: no salaried-vs-hourly field exists on payroll_employees (only HK's hk_pay_basis), so
  pay_basis was added to payroll_be_worker_profiles.
