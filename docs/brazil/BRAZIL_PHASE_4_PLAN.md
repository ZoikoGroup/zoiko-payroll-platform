# Brazil (BR) — Phase 4 Plan (Employee statutory profile)

Spec: ZP-BR-ENG-001 §7 (validation, PIX masking, dependants, concurrent-INSS, alimony, VT).
Pattern: Mexico Phase 4 (`docs/mexico/MEXICO_PHASE_4_PLAN.md` / `MEXICO_PHASE_4_IMPLEMENTATION_REPORT.md`),
merged into `venu`. Head today: `64424fd61652` (br_employer_m2).
Status: **DELIVERED** — 4a (validation/PIX/masking + tests) and 4b (profiles, child tables, migration,
frontend, tests) are implemented and green on `venu`; uncommitted. See
`docs/brazil/BRAZIL_PHASE_4_IMPLEMENTATION_REPORT.md`.

## 1. Scope

**In scope**
- **Validation — finish `BREmployeeValidation`:**
  - PIX key format checked **against its declared type** (`pix_key_type` × `pix_key`).
  - `bank_account` added to bank **routing** (backend + frontend).
  - `pix_key` and `bank_account` become **sensitive** (masked in every response).
  - PIX **masking by key type** everywhere a PIX key is returned (compliance fields, employee
    detail, bank routing, payslip/payment views).
- **Profiles:** effective-dated, **non-overlapping** BR statutory profiles driven by the existing
  `statutory_profile_errors` / `statutory_profile_values` hooks (the Mexico pattern), with a
  **separate IRRF dependants count and salário-família dependants count, each with its own evidence
  reference**.
- **New tables:**
  - `payroll_br_concurrent_inss_declarations` — **monthly** concurrent-employment INSS
    declarations (BR-009).
  - `payroll_br_alimony_orders` — court orders, either a **fixed amount** or a **percentage with a
    defined base**.
  - `payroll_br_vale_transporte_elections` — VT elections (elected flag + daily cost + evidence).
- **Frontend:**
  - `countryFieldSpecs.js`: add `BR` to `COUNTRIES` and `COUNTRY_FIELD_SPECS.BR`, **including
    client-side CPF/CNPJ check-digit `check` functions**.
  - `bankFieldsFor.js`: add BR routing (`BANK_ROUTING_COUNTRIES`, `PAYMENT_MODE_LABEL`,
    `BTF_ROUTING_LABEL`, `BANKING_COMPLIANCE_KEYS`) including `bank_account`.
  - `BrazilStatutoryProfilePanel` mounted inside `EmployeeDetailPanel` (NL/MX pattern).

**Out of scope here** (each has a home phase; shown BLOCKED in readiness):
- Any calculation, base determination, alimony-deduction / VT-cap math, INSS/IRRF arithmetic → **5**.
- `calc_inputs` real inputs, preflight, run snapshot, payslip `br_*` values → **6**.
- eSocial S-1200/S-1005 transmission of these facts → **9**; PIX/CNAB settlement files → **11**.
- Alimony **payment/remittance** and accounting → 11.

## 2. Data model — the split-brain decision (Q1)

Phase 0/1 already created a **dedicated** `payroll_br_statutory_profiles` table
(`models.py:10053`, migration `b7a1c9e3d5f2`), carrying contract/CBO/category/weekly-hours/
dependants/alimony/VT columns. **Every other jurisdiction (DE/HK/IE/SE/IT/SA/CH/NL/MX) instead keeps
its employee statutory facts as country-prefixed columns on the shared
`payroll_employee_statutory_profiles` table**, written through the `statutory_profile_values` hook.
The hook can only set columns on the **shared** table (`service.py:27556`).

**Recommended (Q1 — yes):** adopt the shared-table pattern. Add a `br_*` column block to
`payroll_employee_statutory_profiles`, drive it with the hooks, and **drop the redundant
`payroll_br_statutory_profiles` table** (it is empty everywhere) so there is one source of truth —
the same split-brain fix applied to `brazil_content.py` in Phase 2.

### 2.1 Shared-table `br_*` columns (migration, child of `64424fd61652`)

| Column | Type | Notes |
|---|---|---|
| `br_establishment_id` | FK → `payroll_br_establishments.id` ON DELETE SET NULL | nullable; validated same-org + active on `effective_from` |
| `br_esocial_category` | String(3) | `101` / `103` (CHECK) |
| `br_cbo_code` | String(6) | CBO |
| `br_contract_type` | String(20) | INDEFINITE / DETERMINED / INTERMITTENT |
| `br_weekly_hours` | Numeric(4,2) | > 0 and ≤ 44 |
| `br_simplified_irrf_opt_out` | Boolean | simplified-discount opt-out flag |
| `br_irrf_dependents_count` | SmallInteger | ≥ 0 |
| `br_irrf_dependents_evidence_ref` | String(300) | evidence for the IRRF dependants (required when count > 0) |
| `br_salario_familia_dependents_count` | SmallInteger | ≥ 0 |
| `br_salario_familia_dependents_evidence_ref` | String(300) | evidence for the salário-família dependants (required when count > 0) |

One `ALTER TABLE` (Postgres `lock_timeout='5s'`, FK `NOT VALID` then `VALIDATE`), SQLite `batch_alter`
fallback — the exact `8b2f6d4e1a93` pattern. `br_establishment_id` FK `ON DELETE SET NULL` so an
establishment can never be deleted out from under a profile (also relieves the Phase-3 RESTRICT risk
noted in the Phase 3 audit).

**Drop** `payroll_br_statutory_profiles` in the same migration (guarded, table empty everywhere).
Repoint the three references to it:
- `brazil_service._has_statutory_profile` (`brazil_service.py:194`) → query the shared table with
  `country_code = 'BR'`.
- `engine/base.py:1038` `brazil_statutory_profile` type hint → the shared `EmployeeStatutoryProfile`.
- `tests/test_brazil_phase1_foundation.py:198–209` → updated to the shared table.

## 3. New child tables (all hang off `employee_id` + `organization_id`, like MX INFONAVIT notices)

### 3.1 `payroll_br_concurrent_inss_declarations` (BR-009)
- Columns: `id`, `organization_id` FK→org CASCADE, `employee_id` FK→`payroll_employees.id` CASCADE,
  `competence_month` Date (first day of the month), `base_external` Numeric(12,2) ≥ 0,
  `deducted_external` Numeric(12,2) ≥ 0, `evidence_ref` String(300), `status`
  (RECORDED / SUPERSEDED), `created_by_id`, `created_at`.
- Constraint: unique (`employee_id`, `competence_month`) — one live declaration per month.
- Readiness: an active profile with `concurrent_inss` declared for the payroll month is required
  before Phase 6 preflight (`docs/brazil/BRAZIL_IMPLEMENTATION_PLAN.md:103`).

### 3.2 `payroll_br_alimony_orders`
- Columns: `id`, `organization_id`, `employee_id`, `order_reference` String(100) (court/process no.),
  `method` (FIXED_AMOUNT / PERCENTAGE), `fixed_amount` Numeric(12,2) NULL, `percentage` Numeric(5,2)
  NULL, `base` (GROSS / NET / BASE_INSS / BASE_IRRF) NULL, `effective_from`, `effective_to` NULL,
  `evidence_ref` String(300), `status` (ACTIVE / SUPERSEDED / CLOSED), `created_by_id`, `created_at`.
- Constraints: check `method`; fixed-amount ⇒ `fixed_amount` set and `percentage`/`base` null;
  percentage ⇒ `percentage` in (0,100] and `base` set; `effective_to >= effective_from`.
  Partial unique index: one ACTIVE open order per (`employee_id`, `order_reference`).
- Phase 5 deducts the alimony (fixed, or percentage × its base) from IRRF base and net pay; Phase 4
  only **records** it.

### 3.3 `payroll_br_vale_transporte_elections`
- Columns: `id`, `organization_id`, `employee_id`, `elected` Boolean, `daily_cost` Numeric(8,2) NULL
  (required when elected), `effective_from`, `effective_to` NULL, `evidence_ref` String(300),
  `status` (ACTIVE / SUPERSEDED), `created_by_id`, `created_at`.
- Constraint: `elected ⇒ daily_cost` not null; effective-dated, one ACTIVE open election per employee.
- The 6% cap and the deduction itself are Phase 5 (`brazil_content.VALE_TRANSPORTE_MAX_DEDUCTION_PCT`).

## 4. Validation (`employee_validation.py`) — finish `BREmployeeValidation`

### 4.1 PIX format by type
`_validate_combination` (currently `employee_validation.py:1648`) gains a PIX type/value check when
`pix_key` is present (every value trimmed; `pix_key_type` upper-cased by the spec):
| type | rule |
|---|---|
| CPF | 11 digits + `cpf_is_valid` |
| CNPJ | 14 chars `[0-9A-Z]{14}` + `cnpj_is_valid` |
| EMAIL | `^[^@\s]+@[^@\s]+\.[^@\s]+$`, ≤ 77 chars |
| PHONE | `^\+55\d{10,11}$` (E.164 +55 + DDD + number) |
| RANDOM (EVP) | UUID v4, `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` |
A `pix_key` present without `pix_key_type` (or vice versa) is refused.

### 4.2 Sensitivity and masking
- `SENSITIVE_FIELDS` → `("cpf", "pis_nis", "pix_key", "bank_account")`.
- New helper `mask_pix_key(value, key_type)` in `employee_validation.py` with a **different mask per
  type** (CPF/CNPJ → last 4; EMAIL → first char + domain; PHONE → last 4; RANDOM → last 4), used
  wherever a PIX key is returned.
- `mask_routing` (`employee_validation.py:1827`) → also mask `pix_key` and `bank_account` entries
  (currently only `iban`/`clabe`), and route `pix_key` through `mask_pix_key` using the row's
  `pix_key_type` when present.
- `bank_account` is already in `SENSITIVE_EMPLOYEE_COLUMNS` (`employee_validation.py:1774`); the
  compliance-field copy of `bank_account` becomes sensitive via 4.2 above.

### 4.3 Routing
`bank_routing.py` `ROUTING_FIELDS["BR"]` (`bank_routing.py:98–102`) → add
`{"key": "bank_account", "label": "Account"}`; keep PIX key first so `btf_routing_value` is unchanged.

## 5. Hooks and readiness

### 5.1 Replace the stubs (`brazil_service.py:129–134`)
- `_br_statutory_profile_errors(data)` → shape-only validation (no DB): CBO 6 digits, category ∈
  {101,103}, contract type, weekly hours ≤ 44, dependants ≥ 0 with evidence when > 0, PIX already
  validated upstream; returns `[]` when clean. Delegates to a new
  `brazil_employee_service.statutory_profile_errors`.
- `_br_profile_values(db, employee, data, previous)` → carry-forward (only fields in
  `model_fields_set` overwrite), `br_establishment_id` same-tenant + active-on, numeric coercion;
  returns the `br_*` column dict. Delegates to `brazil_employee_service.profile_values`.
- Update `tests/test_brazil_scaffolding.py:235–236`, which currently asserts the not-built refusal.

### 5.2 New service `brazil_employee_service.py` (mirrors `mexico_employee_service.py`)
`statutory_profile_errors`, `profile_values`, `profile_view`, `employee_record`,
`employee_readiness`, plus child-table `record_/list_` functions for concurrent-INSS, alimony and VT.

### 5.3 Per-employee readiness (G1–G8)
Items: profile version in force on `on`; establishment active; IRRF and salário-família dependants
with evidence; concurrent-INSS declaration for the competência; VT election current; alimony order
active; later-phase items BLOCKED (engine, eSocial, DCTFWeb, FGTS, labor/CCT, parallel payroll).
`on` required, no server-date default; never signs a gate.

## 6. Endpoints

**Org (`/api/payroll/brazil`, `brazil_org_router.py`, behind `require_brazil_tenant`)** — reads: payroll
operator; † writes: org admin.
- `GET /employees/{id}` — the whole BR employee record (masked) with profile versions + child tables.
- `GET /employees/{id}/readiness?on=` — per-employee readiness.
- `POST † /employees/{id}/concurrent-inss-declarations`; `GET /employees/{id}/concurrent-inss-declarations`.
- `POST † /employees/{id}/alimony-orders`; `PUT † /alimony-orders/{id}/close`.
- `POST † /employees/{id}/vale-transporte-elections`.

Profile versions themselves use the **shared** routes
`GET/POST /api/payroll/employees/{id}/statutory-profile` and `…/history` (unchanged).

**Super Admin (`brazil_router.py`, read-only, masked)** — `GET /employees/{id}?organization_id=&on=`.

## 7. Frontend

- `countryFieldSpecs.js` — add `"BR"` to `COUNTRIES` and a `COUNTRY_FIELD_SPECS.BR` block mirroring
  `BREmployeeValidation.FIELD_SPECS` (cpf, pis_nis, rg_number, ctps_number, ctps_series, pix_key_type,
  pix_key, bank_compe, bank_agency, bank_account, bank_account_type), with `check` functions doing
  **client-side CPF/CNPJ check digits** (a JS port of `cpf_is_valid`/`cnpj_is_valid`).
- `bankFieldsFor.js` — add `BR` to `BANK_ROUTING_COUNTRIES`, `PAYMENT_MODE_LABEL.BR = "PIX / TED"`,
  `BTF_ROUTING_LABEL.BR = "PIX Key / COMPE"`, and
  `BANKING_COMPLIANCE_KEYS.BR = ["pix_key", "bank_compe", "bank_agency", "bank_account"]` (mirrors the
  backend `bank_routing.py`, which already knows BR).
- `BrazilStatutoryProfilePanel.jsx` under `modules/payroll/Payroll_Employees/` — copy
  `MexicoStatutoryProfilePanel.jsx`: sections (contract, establishment, dependants, concurrent INSS,
  alimony, VT), saves a new version via the shared `createEmployeeStatutoryProfile` with
  `{countryCode: "BR", effectiveFrom, ...brXxx}`, lists versions, renders readiness and the three
  child-table sub-panels. Register in `EmployeeDetailPanel.jsx` (import, `showBrStatutory` state,
  `countryCode === "BR"` card, modal) and optionally a BR identity block.
- `payrollService.js` — `getBrEmployeeRecord`, `getBrEmployeeReadiness`, and the child-table creators.
- `superAdminService.js` — BR Super Admin employee read-only.

## 8. Migration and platform bookkeeping
- New revision (child of `64424fd61652`): `+10 br_*` columns, `br_establishment_id` FK, the three new
  tables, drop `payroll_br_statutory_profiles`; guarded and idempotent.
- `MIGRATIONS_MANIFEST.txt`: add the new revision + refresh the changed hash.
- `tests/test_alembic_metadata.py`: revision count and single-head +1.

## 9. Files
**Backend** — new: `brazil_employee_service.py`, `alembic/versions/<uuid>_br_employee_m3.py`.
Modified: `models.py` (br_* block, 3 tables, remove PayrollBrStatutoryProfile), `schemas.py` (br_*
fields), `brazil_service.py` (hooks + `_has_statutory_profile`), `brazil_schemas.py` (child-table
inputs), `brazil_org_router.py`, `brazil_router.py`, `employee_validation.py` (PIX + masking),
`bank_routing.py`, `engine/base.py`, `MIGRATIONS_MANIFEST.txt`.
**Frontend** — new: `BrazilStatutoryProfilePanel.jsx` (+ child sub-panels).
Modified: `countryFieldSpecs.js`, `bankFieldsFor.js`, `EmployeeDetailPanel.jsx`, `payrollService.js`,
`superAdminService.js`.
**Docs** — this plan + a Phase 4 implementation report on completion.

## 10. Tests
- `test_brazil_employee_validation.py` — PIX format per type (incl. EPV UUID, +55 phone), CPF/CNPJ
  check digits, sensitivity, `mask_pix_key` per type, `mask_routing` for pix/account.
- `test_brazil_statutory_profile.py` — dated non-overlapping versions, carry-forward, separate IRRF /
  salário-família dependants with evidence, establishment scoping.
- `test_brazil_employee_children.py` — concurrent-INSS (one per month), alimony (fixed vs percentage,
  close), VT election.
- `test_brazil_employee_readiness.py` — every item; LIVE-eligible unreachable.
- `test_brazil_org_router.py` extension — tenant isolation, operator vs admin, masked, no org id.
- Update `test_brazil_scaffolding.py`, `test_brazil_phase1_foundation.py`, `test_alembic_metadata.py`.
- Browser check locally (throwaway SQLite) → `docs/brazil/phase4-evidence/`.

## 11. Decisions needed before I build
| # | Question | Recommendation |
|---|---|---|
| Q1 | Move BR statutory facts to the shared table's `br_*` block and **drop** the empty dedicated `payroll_br_statutory_profiles` table (split-brain)? | **Yes** — matches every other jurisdiction and the hook contract |
| Q2 | Dependants: two counts + two evidence refs as columns (not child tables)? | **Yes** — simplest, mirrors MX evidence pattern |
| Q3 | Concurrent-INSS: monthly declarations table (one per competência), replacing the three scalar columns? | **Yes** |
| Q4 | Alimony: FIXED_AMOUNT or PERCENTAGE×base in one table? | **Yes** |
| Q5 | VT: election record only (deduction + 6% cap stay Phase 5)? | **Yes** |
| Q6 | PIX masking rule per type (CPF/CNPJ last-4, email first-char+domain, phone/random last-4)? | **Yes** |
| Q7 | Keep BR behind `BR_TENANT_ONBOARDING_ENABLED` (already dormant from Phase 3)? | **Yes** — no change |
| Q8 | Split delivery 4a (validation/PIX/masking + tests) then 4b (profiles, tables, frontend)? | **Yes** (optional) |

## 11a. Approval
Awaiting answers to Q1–Q8 (or "go ahead" to accept every recommendation). On approval I will build
4a, run the phase gate (import, targeted pytest, `check:undefined`, build), then 4b.
