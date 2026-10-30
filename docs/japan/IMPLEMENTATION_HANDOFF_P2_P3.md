# Japan (JP) — Implementation Handoff: Phase 2 and Phase 3

Spec: `Jur_doc/Zoiko_Payroll_Japan_Engineering_Implementation_Wireframe_v1.0.docx` (ZP-JP-ENG-001 v1.0).
Reference jurisdiction: **South Africa (ZA)** — copy its patterns, not its legal rules.
Status at handoff (2026-10-29, branch `venu`): P0 (scaffold triage) and P1 (content, seed script, dormancy) are
done. P2 (database) and P3 (engine core) are specified below. Phases P4–P9 follow later.

---

## 0. Rules every agent must follow

| Rule | Why |
|---|---|
| Never read `.env` files; never import `app.database` / `app.config` in ad-hoc scripts; never run a seed or `alembic upgrade` against any database. Tests only (`pytest`, SQLite, via `tests/conftest.py`). | The configured database is the **real remote Postgres**. |
| Never edit an applied migration. Production is at `3880223bfaa0`; `67c8d7454716` (ZA P10) is the current single head and is pushed — treat it as frozen too. | Applied migrations are immutable. |
| Exactly **one** Alembic head after your change. Before committing, `git fetch` and check `git log venu..origin/main -- backend/alembic/versions`; if main added a migration, re-parent yours onto main's head. | Two heads blocks deploys. |
| Migrations use **literal** table/column names in every `op.create_table` / `op.add_column` call (no loops, no variables for names). | `scripts/drift_pending_filter.py` reads migration *text*. |
| Every value in JP content stays `pending_g1=True`; never transcribe a statutory number that is not in the spec or an archived authority artefact. Missing content → the engine **BLOCKS** (`JPCalculationBlockedError`), it never guesses. | Spec page 1 "Production safety rule". |
| No global rounding helper (JP-002). Each amount uses its own `jp_*_rounding` row. | Spec JP-002. |
| My Number never appears in logs, exceptions, traces, snapshots, exports, analytics or API responses (only a masked placeholder). | Spec §7, §12. |
| Do not register `"JP"` in `jurisdiction_hooks._MODULES` before **all 13** hooks exist (that is P5). | `jurisdiction_hooks.call()` is fail-closed — a missing hook raises for every Japan code path. |
| Commit/push only to `venu`; never create remote branches. Run `pytest` (targeted + guard tests), `npm run build`, `npm run check:undefined` before any commit. | Team rules. |
| Do not commit unrelated working-tree changes (e.g. the uncommitted `main.py` / `config.py` / auth / `api.js` edits that are not part of Japan). Stage Japan files explicitly. | Those edits remove privacy/RLS safeguards. |

### Files already in place (P0–P1) — read these first
| File | What it is |
|---|---|
| `backend/app/modules/payroll/engine/countries/japan_content.py` | The ONE content catalog: 47 scalar rows (`JP_SCALAR_CONTENT`, kinds in `JP_PARAMETER_KEYS`: `pct_pair` / `pct_total` / `amount` / `text`), `JP_EMPTY_BY_DESIGN`, `JP_EMPTY_TABLES` (authority tables, all empty), `JP_PREFECTURES` (47 JIS codes), `JP_EARNING_CLASSES` (5 obligations × 6 components), enums (`DECLARATION_CLASSES`, `HEALTH_INSURER_TYPES`, `EI_CLASSES`, `WITHHOLDING_METHODS`, …). |
| `backend/app/modules/payroll/engine/countries/japan.py` | Fail-closed scaffold: `JPCalculationBlockedError`, `JPPack`, `calculate()` always blocks. **P3 rewrites it.** |
| `backend/app/modules/payroll/japan_service.py` | `seed_japan_pack()` (Draft only) + `_as_date` / `_money` helpers. |
| `backend/app/modules/payroll/japan_dormancy.py` | `JP_TENANT_ONBOARDING_ENABLED` switch; `entering_japan_refusal()`. |
| `backend/scripts/seed_japan_canonical_packs.py` | Draft pack + PLANNED registry row, local-DB guard. **Never run it.** |
| `backend/app/modules/payroll/engine/base.py` (`PayrollContext`, ~line 981) | `jp_*` context fields (P3 revises the list). |
| `backend/app/modules/payroll/engine/standard.py` | `_COUNTRY_CALC["JP"] = japan.calculate` (fail-closed dispatch). |
| `backend/app/modules/payroll/engine/resolver.py` | Simple mode blocked for JP. |
| `backend/app/core/jurisdiction.py` | `JURISDICTION_TAX_SCHEMAS["JP"]`, aliases `japan/nippon/nihon`, **not** in `REGISTRATION_COUNTRIES`. |
| `backend/tests/test_japan_content.py` | 36 contract tests — keep green. |
| `frontend/src/modules/payroll/Compliances/JPComplianceCentreTab.jsx` + `CompliancePage.jsx` | Placeholder org tab (real UI is P7). |

### ZA reference files (patterns to copy)
| Concern | ZA file |
|---|---|
| Migration (tables, RLS, idempotent guards, downgrade) | `backend/alembic/versions/447f57564983_za_foundation.py` |
| Models | `backend/app/modules/payroll/models.py` — `PayrollZa*` classes from ~line 11364; `za_*` columns on `EmployeeStatutoryProfile` ~line 1203 |
| Migration tests | `backend/tests/test_south_africa_migrations.py` |
| Engine | `backend/app/modules/payroll/engine/countries/south_africa.py` (`_Pack`, `resolve_applicability`, `obligation_base`, `calculate()` return shape) |
| Pure jurisdiction helpers | `backend/app/modules/payroll/engine/jurisdictions/south_africa/labour.py` |
| Engine tests + golden | `backend/tests/test_south_africa_engine.py`, `test_south_africa_golden.py`, `tests/fixtures/za_golden/*.json`, `app/modules/payroll/hmrc_golden_harness.py` (`_south_africa_context`) |
| Net-pay aggregation | `backend/app/modules/payroll/engine/standard.py` ~lines 300–354 (`*_employee_total` keys) and ~line 624 (`za_result=`) |

---

## PHASE 2 — Database foundation (tables, models, vault, guard tests)

**Objective.** Create the Japan statutory tables the spec §9 domain model requires, plus the shared snapshot /
fingerprint columns, with row-level security, models and migration tests. **No engine, API or UI changes.**
Additive only. Never applied to any database by the agent.

### 2.1 Migration

New file: `backend/alembic/versions/<rev>_jp_foundation.py`
- `<rev>` = `uuid4().hex[:12]`; `down_revision = "67c8d7454716"` (or main's head if it moved — see rules).
- Copy the skeleton of `447f57564983_za_foundation.py`: `_postgres()`, `_has_table()`, `_columns()`, `_index()`,
  `_stamps()`, `_org()`, `_employee()`, `_user()`, `_rls_module()`; `SET LOCAL lock_timeout = '5s'` on Postgres;
  every create/add guarded by an existence check (idempotent both ways); literal names.
- RLS (Postgres only) via `_rls_for_new_tables()` exactly as ZA: `ENABLE` + `FORCE ROW LEVEL SECURITY` + one policy.
  **TENANT** = `rls._TENANT_PREDICATE`; **WORKER** = `rls._worker_predicate("org")` (tables with `employee_id`).

#### Shared tables — nullable columns only
| Table | Column | Type | Purpose |
|---|---|---|---|
| `payslip_items` | `jp_calculation_snapshot` | JSON (JSONB on PG) | Frozen JP inputs + pack ids + result + trace (JP-005, JP-019) |
| `payroll_runs` | `jp_approval_fingerprint` | JSON | Approval bound to inputs + packs (spec §10 stage 10) |

#### New tables
Common columns on every table unless stated: `id` PK; `organization_id` FK `organizations.id` CASCADE NOT NULL
(index); `legal_entity_id` FK `legal_entities.id` SET NULL (index) — JP-017 legal-employer scope; `status`;
`evidence_ref` String(300); `previous_version_id` self-FK SET NULL (new version instead of edits);
`created_by_id` / `approved_by_id` FK `users.id` SET NULL; `approved_at` timestamptz; `created_at` / `updated_at`.
Effective-dated tables also have `effective_from` Date NOT NULL, `effective_to` Date NULL +
`CHECK (effective_to IS NULL OR effective_to >= effective_from)`.

**1. `payroll_jp_employer_registrations`** — RLS **TENANT** (spec §7 employer setup, JP-009)
| Column | Type | Notes |
|---|---|---|
| `corporate_number` | String(13) | NTA Corporate Number (format in `core/jurisdiction.py`) |
| `withholding_tax_office` | String(100) | competent tax office |
| `withholding_payer_status` | String(30) | `STANDARD` \| `SMALL_EMPLOYER_SPECIAL` (special due dates only with evidence, spec §2) |
| `jps_office_symbol` | String(30) | pension/health workplace symbol |
| `jps_office_number` | String(10) | |
| `health_insurer_type` | String(30) NOT NULL | CHECK in `KYOKAI_KENPO`, `HEALTH_INSURANCE_SOCIETY` |
| `health_insurer_code` | String(20) | insurer / society code |
| `health_insurer_prefecture` | String(2) | JIS code; REQUIRED when `KYOKAI_KENPO` (CHECK) |
| `si_deduction_timing` | String(20) | `CURRENT_MONTH` \| `FOLLOWING_MONTH` (JP-009 "deduction timing") |
| `labour_insurance_number` | String(14) | |
| `ei_office_number` | String(20) | employment-insurance establishment number |
| `ei_industry_class` | String(30) NOT NULL | CHECK in `GENERAL`, `AGRICULTURE_SAKE`, `CONSTRUCTION` |
| `workers_comp_rate_class` | String(30) | employer-only, rates certified at G4 |
| `municipality_reporting_enabled` | Boolean NOT NULL default false | |
| `source_document_id` | FK `payroll_source_artifacts.id` SET NULL | |
| `status` | String(12) | CHECK `DRAFT`/`ACTIVE`/`SUPERSEDED` |
Indexes: `ix_jp_registration_org_period (organization_id, effective_from)`; partial unique
`uq_jp_registration_one_active (organization_id) WHERE status='ACTIVE' AND effective_to IS NULL` (first release =
one legal employer).

**2. `payroll_jp_my_number_vault`** — RLS **WORKER "org"** (spec §7 boundary, §12)
| Column | Type | Notes |
|---|---|---|
| `employee_id` | FK `payroll_employees.id` CASCADE NOT NULL | |
| `subject_type` | String(12) | `EMPLOYEE` \| `DEPENDANT` |
| `subject_ref` | String(64) | opaque dependant reference (never a name) |
| `ciphertext` | Text NOT NULL | encrypted 12-digit number |
| `key_version` | SmallInteger NOT NULL | supports key rotation (see 2.3) |
| `fingerprint` | String(64) NOT NULL | keyed HMAC for duplicate detection — never a plain hash |
| `purpose` | String(30) NOT NULL | `TAX_SOCIAL_INSURANCE` (purpose limitation) |
| `collected_at` | timestamptz NOT NULL | |
| `identity_verified_by` | String(30) | document type used for verification (not the document number) |
| `deleted_at` | timestamptz | retention/deletion (ciphertext nulled on delete → make `ciphertext` nullable + CHECK `deleted_at IS NOT NULL OR ciphertext IS NOT NULL`) |
| `status` | String(12) | `ACTIVE` / `DELETED` |
Unique: `(organization_id, employee_id, subject_type, subject_ref)` where `status='ACTIVE'`.
No `effective_from/to`. **No plaintext, no last-4 digits.**

**3. `payroll_jp_my_number_access_events`** — RLS **WORKER "org"**, append-only (spec §12 "audited reveal")
`vault_id` FK SET NULL, `employee_id`, `actor_id` FK users, `action` CHECK (`CREATE`,`REVEAL_REQUESTED`,
`REVEAL_APPROVED`,`REVEALED`,`EXPORTED`,`DELETED`), `purpose` String(60), `reason` String(300),
`approved_by_id` (four-eyes for reveal), `created_at`. No `updated_at`; service never updates/deletes rows.

**4. `payroll_jp_worker_tax_profiles`** — RLS **WORKER "org"** (spec §9 JPWorkerTaxProfile, §3)
| Column | Type | Notes |
|---|---|---|
| `employee_id` | FK NOT NULL | |
| `residency_status` | String(20) NOT NULL | CHECK `RESIDENT`/`NON_RESIDENT` (NON_RESIDENT → engine UNSUPPORTED) |
| `declaration_class` | String(12) NOT NULL | CHECK `PRIMARY`/`SECONDARY` (selects withholding column) |
| `declaration_received_on` | Date | |
| `dependants_count` | SmallInteger NOT NULL default 0 | CHECK ≥ 0 — NTA count semantics per tax year |
| `dependant_facts` | JSON | categories/flags only, versioned per tax year; no names, no My Number |
| `municipality_code` | String(6) | local-government code (resident-tax routing) |
| `residence_prefecture` | String(2) | JIS code (minimum wage, reporting) |
| `my_number_vault_id` | FK `payroll_jp_my_number_vault.id` SET NULL | token reference only |
Status `DRAFT`/`ACTIVE`/`SUPERSEDED`; effective-dated; index `(employee_id, effective_from)`.

**5. `payroll_jp_social_insurance_enrollments`** — RLS **WORKER "org"** (spec §5, JP-010, JP-011)
| Column | Type | Notes |
|---|---|---|
| `employee_id` | FK NOT NULL | |
| `health_eligible` / `pension_eligible` | Boolean NOT NULL | |
| `health_insurer_code` | String(20) | must match the employer registration |
| `smr_health_grade` / `smr_pension_grade` | SmallInteger | statutory grade |
| `smr_amount` | Numeric(12,0) | standard monthly remuneration (statutory) |
| `smr_basis` | String(30) | CHECK `QUALIFICATION`,`ANNUAL_DETERMINATION`,`ADHOC_REVISION`,`RETURN_TO_WORK`,`OTHER` |
| `actual_remuneration` | JSON | actual remuneration used for the determination (kept beside SMR, never overwritten — JP-010) |
| `care_state` | String(20) | `NOT_COVERED` \| `COVERED` \| `EXEMPT` (age 40–64 effective-dated) |
| `child_support_state` | String(20) | `COVERED` \| `EXEMPT` |
| `qualification_date` / `loss_date` | Date | |
Effective-dated; status `DRAFT`/`ACTIVE`/`SUPERSEDED`; index `(employee_id, effective_from)`.

**6. `payroll_jp_social_insurance_events`** — RLS **WORKER "org"** (spec §11 `POST /jp/social-insurance/events`)
`employee_id`, `enrollment_id` FK SET NULL, `event_type` CHECK (`QUALIFICATION`,`LOSS`,`ANNUAL_DETERMINATION`,
`ADHOC_REVISION`,`BONUS`,`MATERNITY_EXEMPTION`,`CHILDCARE_EXEMPTION`,`RETURN_TO_WORK_REVISION`), `effective_from`
Date NOT NULL, `effective_to`, `payload` JSON, `bonus_paid_on` Date, `sba_amount` Numeric(12,0),
`report_due_on` Date, `submission_status` CHECK (`CREATED`,`APPROVED`,`SUBMITTED`,`ACCEPTED`,`REJECTED`,`CORRECTED`),
`receipt_ref` String(100), approval columns, `previous_version_id`.

**7. `payroll_jp_employment_insurance_profiles`** — RLS **WORKER "org"** (spec §6, §9)
`employee_id`, `insured` Boolean NOT NULL, `ei_insured_number` String(20), `industry_class` String(30) NOT NULL
(CHECK `EI_CLASSES`), `qualification_date`, `loss_date`; effective-dated; status `DRAFT`/`ACTIVE`/`SUPERSEDED`.

**8. `payroll_jp_resident_tax_assessments`** — RLS **WORKER "org"** (spec §4, JP-007, JP-008)
| Column | Type | Notes |
|---|---|---|
| `employee_id` | FK NOT NULL | |
| `municipality_code` | String(6) NOT NULL | |
| `fiscal_notice_year` | SmallInteger NOT NULL | e.g. 2026 = June 2026–May 2027 |
| `notice_id` | String(50) NOT NULL | municipality notice reference |
| `version` | SmallInteger NOT NULL default 1 | change notice = new version |
| `received_on` | Date NOT NULL | |
| `first_deduction_month` | Date NOT NULL | first-of-month |
| `monthly_amounts` | JSON NOT NULL | exactly 12 keys `YYYY-MM` (June→May), integer yen — validated in the service/model test |
| `total_amount` | Numeric(12,0) NOT NULL | must equal the sum (service check) |
| `source_hash` | String(64) NOT NULL | SHA-256 of the imported row |
| `replaces_id` | self-FK SET NULL | replacement link |
| `status` | String(12) | CHECK `IMPORTED`,`APPROVED`,`SUPERSEDED`,`REJECTED` |
Unique `(organization_id, employee_id, municipality_code, fiscal_notice_year, version)`.
**Fix vs the old scaffold:** do NOT make `(organization_id, notice_id)` unique — it blocked change notices.

**Downgrade:** drop the 8 tables (reverse dependency order: access_events, worker_tax_profiles before vault,
events before enrollments) and the 2 shared columns, each guarded by existence checks.

### 2.2 Models — `backend/app/modules/payroll/models.py`
Append after `PayrollZaPayrollOverride` (end of file): `PayrollJpEmployerRegistration`, `PayrollJpMyNumberVault`,
`PayrollJpMyNumberAccessEvent`, `PayrollJpWorkerTaxProfile`, `PayrollJpSocialInsuranceEnrollment`,
`PayrollJpSocialInsuranceEvent`, `PayrollJpEmploymentInsuranceProfile`, `PayrollJpResidentTaxAssessment`.
Columns/constraints/index names must match the migration **exactly** (a test compares them). Add
`jp_calculation_snapshot` to `PayslipItem` and `jp_approval_fingerprint` to `PayrollRun` next to the `za_*` ones.
Keep the file's LF line endings (the old scaffold introduced CRLF).

### 2.3 My Number encryption helper
New file `backend/app/modules/payroll/japan_my_number.py` (pure helpers; no routes yet):
- `encrypt(number, key_version) -> ciphertext`, `decrypt(row) -> str`, `fingerprint(number) -> hmac`,
  `validate(number)` (12 digits + check digit), `masked() -> "•••• •••• ••••"`.
- Keys: new setting `JP_MY_NUMBER_KEYRING` in `backend/app/config.py` (JSON `{"1": "<key>"}`, Secret Manager;
  required outside development/test, **no fallback derived from `PAYROLL_SECRET_KEY`** — `app/core/secretbox.py` has
  no key versioning, so rotating that key would destroy every stored number). Use Fernet/AES-GCM per version.
- Never `repr`/log the number; raise errors without the value.
(If the team prefers to defer the helper to P5, the vault table still lands in P2.)

### 2.4 Guard files that MUST be updated
| File | Change |
|---|---|
| `backend/alembic/MIGRATIONS_MANIFEST.txt` | regenerate: `python scripts/update_migration_manifest.py` |
| `backend/tests/test_alembic_metadata.py` | heads `["<rev>"]` (lines ~276, ~288); revision count `235 → 236` (~line 330) with a comment |
| `backend/tests/test_migration_idempotency.py` | add `"<rev>"` to `_GUARDED` |
| `backend/tests/test_deploy_migrate_script.py` | add a `jp_tables` set (the 8 tables) to every pending-set expectation that currently ends in `za_tables` / `mx_final_mile` (lines ~99–148) |
| `backend/tests/test_south_africa_migrations.py` | if it asserts `67c8d7454716` is the head, change to "is an ancestor of the head" |

### 2.5 New tests — `backend/tests/test_japan_migrations.py` (mirror `test_south_africa_migrations.py`)
1. single child of the previous head; single head overall;
2. migration columns == model columns for every JP table and the 2 shared columns;
3. RLS: the policy each table gets == what `d7f9b1c3e5a6`'s `classify()` derives (TENANT vs WORKER "org");
4. replay is a no-op (upgrade twice); downgrade removes everything; upgrade again works;
5. drift filter explains every JP object (`scripts/drift_pending_filter`);
6. literal `op.create_table("payroll_jp_…")` / `op.add_column("…", sa.Column("jp_…"` present;
7. vault: no column named like `my_number`/`plain`; `ciphertext` nullable only with `deleted_at`;
8. `japan_my_number`: check-digit validation, encrypt/decrypt round-trip per key version, fingerprint stable,
   error messages never contain the number.

### 2.6 Frontend / docs in P2
None (no API yet). Update `docs/japan/` with a one-paragraph P2 note if desired.

### 2.7 P2 done when
`pytest tests/test_japan_migrations.py tests/test_japan_content.py tests/test_alembic_metadata.py
tests/test_migration_idempotency.py tests/test_deploy_migrate_script.py tests/test_south_africa_migrations.py
tests/privacy` all pass; `alembic heads` (read the script directory in a test, never a DB) shows one head.

---

## PHASE 3 — Engine core (monthly salary path, pure and fail-closed)

**Objective.** Replace the scaffold `calculate()` with the deterministic monthly pipeline of spec §10 stages 1–7
for the supported cohort (resident, MONTHLY, JPY, no bonus). Pure function of `PayrollContext` (JP-016): no DB,
no clock, no network. Bonuses (P4), labour premiums / minimum wage (P6), year-end (P8) are **not** in P3 — a
non-zero BONUS component BLOCKS with `JP_BONUS_PATH_PENDING_P4`.

### 3.1 Content additions — `japan_content.py` (schemas only; rows stay EMPTY)
Define how the authority tables will be stored when G1/G3 supply them (TaxSlab, `rule_type` ≤ 30 chars):
| rule_type | Row meaning (TaxSlab columns) |
|---|---|
| `JP_WHT_MONTHLY` | NTA monthly table: `min_amount`/`max_amount` = monthly pay after SI deduction band; `tax_column` = `PRIMARY`/`SECONDARY`; `tax_table_number` = dependants count `"0".."7"`; `flat_amount` = tax; `rate_pct`/`formula_expression` for the top/secondary formula branches |
| `JP_WHT_CMP_EID` | computer method — employment-income deduction bands (`rate_pct`, `flat_amount`) |
| `JP_WHT_CMP_RATE` | computer method — tax-rate bands (`rate_pct`, `flat_amount` = deduction) |
| `JP_HEALTH_RATE` | `tax_regime` = insurer type, `jurisdiction_state` = prefecture JIS code (or insurer code for societies), `rate_pct` = TOTAL health rate, `effective_from/to` |
| `JP_SMR_GRADE` | `filing_status` = `HEALTH`/`PENSION`, `tax_table_number` = grade, `min_amount`/`max_amount` = remuneration band, `flat_amount` = standard amount, effective dates |
Add scalar rows (EMPTY_BY_DESIGN, pending) the computer method needs, e.g. `jp_wht_cmp_basic_deduction`,
`jp_wht_cmp_dependant_deduction` — values come only from the archived NTA S1 material.
Update `test_japan_content.py`: new keys seeded once, still empty, `JP_EMPTY_TABLES` points at these rule types.
`japan_service.seed_japan_pack` must write any rows these tables gain (loops over empty tuples today).

### 3.2 Engine files
| File | Contents |
|---|---|
| `engine/countries/japan.py` (rewrite) | `JPCalculationBlockedError` (keep), `_Pack` like ZA (`require_text`, `require_amount`, `require_pct_total`, `require_pair`, `in_force(as_of)` honouring row `effective_from/to` — JP-004), `resolve_applicability()`, `pay_components()`, `obligation_base()` (per `JP_EARNING_CLASSES`; REVIEW + non-zero → BLOCK), `calculate()` |
| `engine/jurisdictions/japan/withholding.py` (new, pure) | `monthly_withholding(base_after_si, declaration_class, dependants, method, slabs, scalars, rounding)` → `{"tax", "branch", "row", "rounding_events"}`; PRIMARY + `COMPUTER_PRIMARY_TABLES_OTHERS` → computer method; SECONDARY or `TABLES_ONLY` → `JP_WHT_MONTHLY`; never adds Reconstruction tax on top (it is inside the official content) |
| `engine/jurisdictions/japan/social_insurance.py` (new, pure) | `monthly_contributions(enrollment, registration, pack, as_of, rounding)` → EPI, health, care, child-support employee/employer + trace; rate = insurer+prefecture `JP_HEALTH_RATE` row in force (none → BLOCK; outside `jp_kyokai_health_total_min/max` for Kyokai → BLOCK); care only when `care_state == COVERED` and age 40–64 (`jp_care_min_age`/`max_age`); child support only on/after its row's `effective_from`; split via `*_split_rule` (`PENDING_G1` → BLOCK) |
| `engine/jurisdictions/japan/employment_insurance.py` (new, pure) | `monthly_employment_insurance(profile, base, pack, as_of, rounding)`; class → `jp_ei_general` / `jp_ei_agriculture_sake` / `jp_ei_construction` pair in force (empty pair or no row in force → BLOCK) |
| `engine/jurisdictions/japan/resident_tax.py` (new, pure) | `resident_tax_for_month(assessments, pay_month)` → exact notified amount of the single APPROVED assessment covering that month; none / ambiguous → BLOCK `JP_RESIDENT_TAX_NOTICE_MISSING` (JP-007: never derived from salary). Employee with no assessment *for a month outside any notice year* → 0 with trace `NO_NOTICE_PERIOD` only if a signed rule says so — until then BLOCK |

### 3.3 `calculate(ctx)` pipeline (spec §10 order — keep this order)
1. **Validate**: `pay_date` present; `jp_supported_pay_frequencies` contains frequency; `jp_employer_registration`
   ACTIVE; `jp_worker_tax_profile` ACTIVE with `residency_status == RESIDENT` (else BLOCK `JP_NON_RESIDENT_UNSUPPORTED`);
   `jp_social_insurance_enrollment` and `jp_employment_insurance_profile` present; currency JPY.
2. **Classify**: `pay_components()` → bases for `WHT`, `SI`, `EI` (each its own base, JP-018). Non-zero BONUS → BLOCK (P4).
3. **Social insurance** (on SMR, not gross — JP-010) → employee/employer per component.
4. **Withholding**: base = WHT base − employee SI (EPI + health + care + child support) − employee EI, per the NTA method → tax.
   *(Confirm the exact "after social-insurance deduction" basis against S1 at G1; record it in the trace.)*
5. **Employment insurance** on the EI base (class rate).
6. **Resident tax**: exact monthly notified amount.
7. **Net**: employee total = WHT + SI employee + EI employee + resident tax. Net < 0 → BLOCK `JP_NEGATIVE_NET` (exception workflow is P9-style later).
Rounding: every amount rounded only through its own row (`jp_wht_rounding`, `jp_si_employee_share_rounding`,
`jp_ei_employee_share_rounding`); those rows are `PENDING_G1` today → the engine BLOCKS until G1 signs them. Tests
inject signed test values through `rate_map` (never through content).

### 3.4 Return shape and wiring
`calculate()` returns (mirror ZA's dict at `south_africa.py` ~line 764):
```python
{
  "tds": wht,                                   # national withholding (incl. reconstruction tax)
  "jp_employee_total": si_employee + ei_employee + resident_tax,   # everything else the employee pays
  "jp_result": {
     "jp_wht": "...", "jp_wht_base": "...", "jp_wht_branch": "...", "jp_declaration_class": "...",
     "jp_dependants": n, "jp_epi_employee": "...", "jp_epi_employer": "...",
     "jp_health_employee": "...", "jp_health_employer": "...", "jp_care_employee": "...", "jp_care_employer": "...",
     "jp_child_support_employee": "...", "jp_child_support_employer": "...",
     "jp_ei_employee": "...", "jp_ei_employer": "...", "jp_ei_base": "...", "jp_smr": "...",
     "jp_resident_tax": "...", "jp_resident_tax_notice": {"municipality": ..., "noticeYear": ..., "version": ...},
     "jp_employee_total": "...", "jp_employer_total": "...",
     "trace": {...  table_pack_id, row/branch, bases with lines, rate rows used, rounding events, rateKeys ...}
  },
}
```
Never put the My Number, names or bank data in `jp_result`/trace.

| File | Change |
|---|---|
| `engine/standard.py` | in the employee-deduction sum (~line 300–350) add `+ deductions.get("jp_employee_total", Decimal("0"))` with a comment like the others; in the `PayrollResult(...)` call (~line 624) add `jp_result=deductions.get("jp_result")` |
| `engine/base.py` | `PayrollResult.jp_result: dict = None` (next to `za_result`); revise `PayrollContext` JP fields to exactly what the engine reads: `jp_employer_registration`, `jp_worker_tax_profile`, `jp_social_insurance_enrollment`, `jp_employment_insurance_profile`, `jp_resident_tax_assessments`, `jp_organization_id`, `jp_employee_id`, `jp_date_of_birth`, `jp_components`; drop unused ones (`jp_statutory_profile`, `jp_rule_packs`, `jp_year_end_context`, `jp_bonus_context`, `jp_time_records`, `jp_earning_items`, `jp_legal_employer_id`) unless the engine uses them |
| `engine/countries/shared.py` | add `"JP"` to `_VALIDATION_ENABLED_COUNTRIES` (and update the pinned set in `tests/test_mexico_seed.py` if it asserts the exact set) |
| `engine/resolver.py` | keep the simple-mode block; no other change |
| `app/modules/payroll/hmrc_golden_harness.py` | add `_japan_context(case)` building a `PayrollContext` from a fixture (like `_south_africa_context`) |
| `japan_service.py` | **optional in P3**: `resolve_jp_calc_inputs(db, organization_id, employee, as_of)` returning the dict of ctx fields from the P2 tables (ACTIVE, in force on `as_of`). Do **not** add `JURISDICTION_HOOKS` or wire `service.py` call sites yet (P5). |

### 3.5 Tests
| File | Covers |
|---|---|
| `tests/test_japan_engine.py` | every BLOCK path (missing registration/profile/enrollment/EI profile, NON_RESIDENT, DAILY frequency, Kyokai without prefecture rate, rate outside bounds, PENDING split, PENDING rounding, EI Jan–Mar 2026 no row, child support before April 2026 = not charged, care only 40–64, REVIEW component non-zero, BONUS non-zero, missing/ambiguous resident-tax notice, negative net); separate bases; withholding base after SI; no My Number in result/trace; `_COUNTRY_CALC["JP"]`; determinism (same ctx → same dict) |
| `tests/test_japan_golden.py` + `tests/fixtures/jp_golden/*.json` | golden cases through `hmrc_golden_harness`. **Because the official tables are not archived yet, fixtures use a clearly labelled TEST content set** injected via `rate_map`/`slabs` (e.g. `"content": "SYNTHETIC — not NTA"`), with hand-computed expectations. Real NTA boundary fixtures (spec §13) replace them at G1 |
| `tests/test_japan_content.py` | extend for 3.1 |

### 3.6 Frontend in P3
None (payslip breakdown, Super Admin tabs and labels are P7). Do not add JP to `jurisdictionLabels.js` /
`jurisdictionTax.js` yet.

### 3.7 P3 done when
All JP tests + `tests/test_south_africa_engine.py` + every test touching `_COUNTRY_CALC` / `resolver.calculate_payroll`
pass; batched full suite shows no new failures; `npm run build` unaffected.

---

## Known risks to carry forward
- No archived NTA / JPS / Kyokai / MHLW artefacts yet → real calculations stay BLOCKED; only synthetic fixtures run.
- Withholding basis after social insurance, all rounding rules, care split, EI agriculture/construction splits,
  resident-tax handling outside a notice year and the withholding due-date holiday rule are **PENDING_G1** decisions.
- `ZA` gates only the org-country change, not the company-jurisdiction update/back-fill (Japan gates all three) —
  a ZA follow-up, not part of P2/P3.
