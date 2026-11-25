# Spain (ES): Implementation Plan — simplified design from ZP-ES-ENG-001 v1.0

Approved by the owner 2026-11-24. Each phase starts on "GO AHEAD Pn"; commit and push only on the owner's word. Gaps and decisions: `docs/spain/SPAIN_GAPS_AND_DECISIONS.md`.

## Context

**Source.** The spec is `Jur_doc/Zoiko_Payroll_Spain_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx` (24 sections, rules ES-001 to ES-063, fixtures F1–F6, gates G1–G8). Spain is the last country of the 33 that Super Admin is missing. Nothing for Spain exists in the code today, except:
- region and timezone lists (`registrationRegions.js:149, 316`);
- the EUR mapping (`currency.js`).

**Owner decisions (2026-11-24):**
1. **Simplified design, like the UAE and Jamaica.**
   - Every value is a pack row in Super Admin.
   - Calculation is accurate, and a missing value blocks the employee (`ES_RATE_MISSING:<key>`).
   - No signing, evidence, golden checks or G1–G8 gates; no Spain-specific four-eyes (the platform-wide second-approver rule stays).
   - SLD/SILTRA, CRA transmission, AEAT Modelo 111/190 filing files, the convenio engine, IT benefits and severance are later phases.
2. **IRPF values come from the official AEAT document the owner sends:** "Algoritmo de cálculo de retenciones 2026", both versions, 1 Jan–9 Sep and from 10 Sep.
   - The spec contains none of these values.
   - Until they are seeded, IRPF rows are missing, so a Spanish employee is blocked with `ES_RATE_MISSING:irpf_*`. Social Security is fully built and tested in the meantime.

**Outcome:** organisations can register in Spain once a Super Admin activates `ES-PAYROLL-2026`. Payroll then calculates:
- employee and employer Social Security, including MEI and the 2026 solidarity tranches;
- IRPF;
- net pay;
- the payslip breakdown;
- 3 report templates.

**Pattern:** copy the UAE build, which is the latest and simplest. Reference commits: `6fe6555` (engine, seed, fields, pages) and `43aa8d0` (report templates).

## Values from the spec (seeded; nothing invented)

| Key (pack row) | Employee | Employer | Flat / text | Source |
|---|---|---|---|---|
| `es_cc` common contingencies | 0.047 | 0.236 | | §2/§4 |
| `es_mei` | 0.0015 | 0.0075 | | §2 |
| `es_unemployment_general` | 0.0155 | 0.055 | | §2 |
| `es_unemployment_temporary` | 0.016 | 0.067 | | §2 |
| `es_fogasa` | — | 0.002 | | §2 |
| `es_training` | 0.001 | 0.006 | | §2 |
| `es_overtime_force_majeure` | 0.02 | 0.12 | | §4 |
| `es_overtime_other` | 0.047 | 0.236 | | §4 |
| `es_solidarity_t1` / `_t1_upper` | 0.0019 | 0.0096 | 5,611.32 | §5 |
| `es_solidarity_t2` / `_t2_upper` | 0.0021 | 0.0104 | 7,651.80 | §5 |
| `es_solidarity_t3` | 0.0024 | 0.0122 | | §5 |
| `es_base_max_monthly` / `es_base_max_daily` | | | 5,101.20 / 170.04 | §2 |
| `es_base_min_group_4_7` (monthly) | | | 1,424.40 | §2 |
| `es_base_min_group_8_11` (daily) | | | 47.48 | §2 |
| `es_smi_monthly` / `_daily` / `_annual` | | | 1,221 / 40.70 / 17,094 | §2 / S1 |
| `es_short_contract_surcharge` | | | 33.62 | §2 / ES-010 |
| `es_short_contract_days` | | | 30 | §2 |

Pack `ES-PAYROLL-2026`, EUR, effective 2026-01-01. About 25 Social Security rows are seeded at first. IRPF rows are added from the AEAT document.

## Gaps (recorded in `docs/spain/SPAIN_GAPS_AND_DECISIONS.md`; no values invented)

| ID | Gap | Handling |
|---|---|---|
| G-01 | IRPF algorithm parameters, both 2026 versions | The owner sends the AEAT PDF. Rows `irpf_a_*` (to 9 Sep) and `irpf_b_*` (from 10 Sep) carry row-level `effective_from`. Missing rows block. |
| G-02 | Minimum bases for groups 1–3 (spec: "higher minima", no figures) | Rows `es_base_min_group_1/2/3`; a missing row blocks only that group |
| G-03 | AT/EP rate: no universal rate (ES-008) | Employer fact `es_at_ep_rate` in company/tax details (from the employer's own tarifa); a missing value blocks |
| G-04 | Part-time hourly minimum bases | Part-time is blocked (`ES_PART_TIME_NOT_SUPPORTED`) until rows are given |
| G-05 | Solidarity for daily contributors / partial month (ES-012) | Thresholds prorated by days in alta ÷ 30 for monthly contributors; daily contributor groups 8–11 are blocked until the official rule is given |
| G-06 | Exact Model 145 fact list | Fields from §7: family situation, spouse, children, ascendants, disability; finalised from the AEAT document |
| Later | SLD/SILTRA, CRA, Modelo 111/190 files, IT benefits, severance, convenio tables, regularisation workflow UI | Out of scope (owner decision 2); the employee is blocked where a fact needs them |

## Phases (each starts on "GO AHEAD Pn"; commit or push only on your word)

### P0: docs (no code)
- `docs/spain/SPAIN_IMPLEMENTATION_PLAN.md` (this plan).
- `docs/spain/SPAIN_GAPS_AND_DECISIONS.md` (D1–Dn: the simplified decisions plus G-01 to G-06).

### P1: registration and country config
- **`backend/app/core/jurisdiction.py`:**
  - "Spain" added to `REGISTRATION_COUNTRIES`;
  - `CODE_TO_COUNTRY_NAME["ES"]`;
  - aliases "spain", "españa", "espana", "kingdom of spain" (no bare "es");
  - ES tax schema: employer `nif` (primary), `ccc`; currency EUR.
- **`backend/app/modules/payroll/service.py`:** ES in `_CANONICAL_PACK_ONLY_COUNTRIES` only, so it is **not** in the four-eyes, registry-required, dormancy or hook lists (same as AE).
- **`backend/app/modules/payroll/engine/tax_resolver.py`:** no change. ES is not in `_REGISTRY_ROW_REQUIRED_COUNTRIES`.
- **Frontend:**
  - `frontend/src/utils/registrationRegions.js`: "Spain" in `REGISTRATION_COUNTRIES` (the regions already exist at line 149);
  - `CountryFlag.jsx` (Spain);
  - `jurisdictionLabels.js`, `jurisdictionTax.js` (IRPF label, EUR).
- **Tests:** `backend/tests/test_spain_scaffold.py` covers aliases, registration list, canonical-pack-only and the no-gate lists. Re-pin the lists in `test_mexico_activation_gates` / `test_singapore_phase60_remediation` if they enumerate countries, as done for AE.

### P2: values, seed and schema
- **`backend/app/modules/payroll/engine/countries/spain_content.py`:**
  - `PACK_ID`, `CURRENCY`, `EFFECTIVE_FROM`, `SOURCE_REFERENCES` (S1–S16);
  - `RATES` tuples in UAE shape: `(key, label, employee_frac, employer_frac, flat, text, row_effective_from, source)`.
- **`backend/scripts/seed_spain_canonical_pack.py`:** a copy of `seed_uae_canonical_pack.py`.
  - `seed_spain_pack(db)` creates or refreshes a Draft pack and refuses a non-Draft pack.
  - It shows percentage labels and is guarded by `_local_db_guard`.
- **`backend/app/modules/payroll/models.py`:** `PayslipItem.es_calculation_snapshot = Column(JSON, nullable=True)`.
- **Migration** `backend/alembic/versions/<uuid12>_es_foundation.py`:
  - adds that one column, on main's head at build time (today `b5f3e8a1c6d9`);
  - regenerate the manifest (`python -m scripts.update_migration_manifest`);
  - re-pin the head and drift tests (`test_alembic_metadata`, the Belgium C/K/M and seed_postgres tests, `test_uae_migrations`, the drift sets) exactly as done for AE.
- **Tests:** `test_spain_migrations.py`.

### P3: Social Security engine (all values from the pack)
New package `backend/app/modules/payroll/engine/jurisdictions/spain/`:
- **`errors.py`:** `ESCalculationBlockedError`; codes `RATE_MISSING`, `EMPLOYEE_FACT_MISSING`, `OUT_OF_SCOPE`, `PART_TIME_NOT_SUPPORTED`, `DAILY_GROUP_NOT_SUPPORTED`, `AT_EP_RATE_MISSING`, `BELOW_SMI`, `SIMPLE_MODE_UNSUPPORTED`. Copy of `engine/jurisdictions/uae/errors.py`.
- **`params.py`:** strict `pct` / `amount` / `has`; a missing key raises `ES_RATE_MISSING:<key>`. Copy of `uae/params.py`.
- **`bases.py`:**
  - common base = contributable ordinary pay (excluding overtime) + extra-pay prorrata (ES-006);
  - AT/EP base = common base + overtime;
  - clamp each to the group minimum (monthly groups; prorated by days in alta) and to `es_base_max_monthly`;
  - excess above the maximum = remuneration − max (ES-011).
- **`social_security.py`:** per family (CC, MEI, unemployment general or temporary by `contract_type`, FOGASA, training), the employee and employer amounts on the right base. Overtime additional contribution on the overtime amount. AT/EP employer = AT/EP base × employer `es_at_ep_rate`.
- **`solidarity.py`:** splits the excess into the 3 tranches (thresholds from the rows, prorated by days for a partial month), with employee/employer per tranche (ES-011, ES-012).
- **`extra_pay.py`:**
  - policy `PRORATED_12` (cash already monthly, no prorrata) or `SEPARATE_14`;
  - for `SEPARATE_14`, monthly prorrata = annual extra-pay total ÷ 12, added to the bases only (ES-006, ES-021);
  - in the payment month the cash is gross but is **not** added to the base again (F5).
- **SMI check:** if total wage for a full-time monthly period is below `es_smi_monthly` (prorated by days), block with `ES_BELOW_SMI`.
- **Short-contract surcharge:** when the employee leaves in this period, `contract_type = TEMPORARY`, length < `es_short_contract_days` and no exception flag, employer cost = `es_short_contract_surcharge` (ES-010).

### P4: IRPF engine (needs the AEAT document)
- **`engine/jurisdictions/spain/irpf.py`:** the AEAT withholding algorithm.
  - annual forecast remuneration;
  - minus Social Security contributions;
  - work-income reduction and expenses;
  - personal/family minimum (Model 145 facts);
  - scale on the base and on the minimum;
  - type = quota ÷ forecast, rounded per AEAT;
  - minimum rates (for example short contracts);
  - regularisation as the remaining-year spread.
- **Version selection by pay date:** `irpf_a_*` rows until 2026-09-09, `irpf_b_*` from 2026-09-10, chosen through row-level `effective_from` (already honoured by `tax_resolver._resolve_uncached`). The version id is stored in the snapshot (ES-015, ES-016, ES-039).
- **Year-to-date inputs:** remuneration and withholding to date come from prior Spanish payslips' `es_calculation_snapshot` (the same way gratuity history reads prior payslips). There is no new table.
- **Voluntary higher rate (ES-017):** the employee field `irpf_voluntary_rate` is used only when it is above the calculated rate.
- **Seed:** IRPF rows are added to `spain_content.py` **only from the AEAT document**, with that document as the source label.
- **Tests:** F3 (9 Sep vs 10 Sep) plus the AEAT worked examples from the document.

### P5: country calculator and wiring
- **`backend/app/modules/payroll/engine/countries/spain.py`** (like `countries/uae.py`):
  1. `_facts`;
  2. scope blocks: unsupported regime, part-time, daily group, missing contract type or group;
  3. wages;
  4. extra pay;
  5. bases;
  6. Social Security;
  7. solidarity;
  8. IRPF;
  9. surcharge;
  10. JSON-safe `es_result` breakdown: inputs, bases, families, solidarity tranches, IRPF (version, rate, forecast), employer cost, lines.
- **Generic payslip lines it returns:**
  - `tds` = IRPF;
  - `social_security` = employee Social Security total (CC + MEI + unemployment + training + solidarity + overtime);
  - `employer_social_security` = employer Social Security total;
  - `employer_occupational_hazard` = AT/EP (the column already exists, from SA);
  - `employer_payroll_tax` = short-contract surcharge;
  - `es_result`.
- **Wiring:**
  - `engine/base.py`: `PayrollContext.es_facts`, `PayrollResult.es_result`;
  - `engine/resolver.py`: `es_facts` from `compliance_fields` plus `work_state`; simple mode blocked;
  - `engine/standard.py`: `_COUNTRY_CALC["ES"]`, `es_result`;
  - `service.py` payslip kwargs: `"es_calculation_snapshot": result.es_result`.
- **Tests:** `test_spain_calculator.py` covers:
  - F1: €5,500 → base 5,101.20, excess 398.80 all in tranche 1;
  - F2: €8,000 → three tranches;
  - F4: temporary rates + €33.62;
  - F5: 14 pays, no double count;
  - min/max by group; SMI block; employer costs never reduce net; standard dispatch.

### P6: employee fields and banking
- **`backend/app/modules/payroll/employee_validation.py`:** `ESEmployeeValidation` in `_STRATEGIES` (not dormant).
  - `nif_nie` (pattern, sensitive);
  - `naf_nuss` (12 digits, sensitive);
  - `contract_type` (INDEFINITE / TEMPORARY);
  - `contract_end_date`;
  - `short_contract_exception` (YES / NO);
  - `contribution_group` (1–11);
  - `work_pattern` (FULL_TIME / PART_TIME);
  - `extra_pay_policy` (PRORATED_12 / SEPARATE_14);
  - `extra_pay_annual_amount`;
  - Model 145 facts: `family_situation` (1/2/3), `children_under_25`, `children_under_3`, `ascendants`, `disability_degree`;
  - `irpf_voluntary_rate`.
  - Combination checks: a temporary contract needs an end date; SEPARATE_14 needs an amount.
- **`backend/app/modules/payroll/bank_routing.py`:** ES IBAN (`ES` + 22 characters, mod-97), payment mode "SEPA".
- **Frontend:** `frontend/src/utils/countryFieldSpecs.js` (ES fields), `bankFieldsFor.js` (ES before ZA; keep the Poland tail pin `"ZA", "PL", "MY"]`).
- **Tests:** `test_spain_employee_validation.py`, and `_STRATEGIES` re-pinned in `test_mexico_employee_validation`.

### P7: Super Admin and organisation pages
- **New pages:**
  - `frontend/src/pages/JurisdictionCompliance/ESCompliancePage.jsx` (`<JurisdictionLayout country="ES" countryName="Spain" />`);
  - `frontend/src/pages/ReportTemplates/ESReportTemplatesPage.jsx`.
- **Routes:** `App.jsx`; `JurisdictionCompliance/index.js` and `ReportTemplates/index.js` (`ES: "spain"`); exclude ES in `JurisdictionStatutory/index.js`.
- **Company details:** the employer AT/EP rate field (`es_at_ep_rate`) and the CCC.
- **UI check script:** `frontend/scripts/es-scaffold-ui-validation.mjs`, added to `npm test`.
- **Undefined-JSX check** (`node scripts/check-undefined.mjs`) before commit.

### P8: report templates
- **`service.py`:**
  - `_PAYSLIP_ITEM_JSON_FIELD_CATALOG["ES"]`: bases, families, solidarity tranches, IRPF version/rate; employer labels carry "(Employer)";
  - `_PAYSLIP_FIELDS_BY_COUNTRY["ES"]`;
  - `_PAYSLIP_FIELD_LABEL_OVERRIDES["ES"]`: tds → "IRPF", social_security → "Social Security (Employee)", and so on.
- **`backend/scripts/seed_statutory_report_templates.py`:** `_es_templates()` / `seed_spain` with:
  - `ES-PAYROLL-REGISTER`;
  - `ES-SS-SUMMARY` (SUM_RUN, to reconcile against the TGSS RLC);
  - `ES-IRPF-SUMMARY` (SUM_RUN, a Modelo 111 helper, not a filing file).
  - Added to `SEED_COMING_SOON_COUNTRIES`.
- **Tests:** `test_spain_report_templates.py`, a copy of `test_uae_report_templates.py`.

### P9: merge, full suite, PR, production
- Merge `origin/main` into venu (venu is 1 merge behind today), full batched suite, push venu, PR venu → main.
- After the deploy, **separate approvals** for:
  - the read-only check and Draft seed of `ES-PAYROLL-2026` (a `uae_prod_seed.py`-style script);
  - the 3 ES report templates (a `uae_prod_report_templates.py`-style script).
- Then Super Admin review → second-SA approve → activate → test organisation and payroll.

## Reuse (no new frameworks)
| Need | Reuse |
|---|---|
| Strict parameter reads / blocks | `engine/jurisdictions/uae/params.py`, `errors.py` |
| Country calc + JSON breakdown | `engine/countries/uae.py` (`_json`, `_facts`, `calculate`) |
| Seed script | `scripts/seed_uae_canonical_pack.py` |
| Effective-dated rows (IRPF A/B, MEI phase-in) | row `effective_from` in `tax_resolver._resolve_uncached` |
| Employee fields | `AEEmployeeValidation` FIELD_SPECS / `_validate_combination` |
| Report templates | `_json`, `_col`, `_register`, `_run_summary`, `_seed_country` in `seed_statutory_report_templates.py` |
| Pages | `JurisdictionLayout`, `ReportTemplateLayout` |
| Production scripts | `scratchpad/uae_prod_seed.py`, `uae_prod_report_templates.py` (target check + read-only check + one transaction + verify) |

## Verification (per phase, then at the end)
- **Each phase:** its targeted tests (system Python 3.11, `pytest -n 4`), plus import checks.
- **Frontend phases:** `npm run build`, `npm test` (all validation scripts), `node scripts/check-undefined.mjs`.
- **Fixtures:** F1, F2, F4 and F5 as unit tests with hand-calculated values from the spec rates. F3 and the IRPF worked examples come only from the AEAT document.
- **P9:** full suite (batched runner) checked against the known local-only failures (MFA ×2, the xdist-only checkout/assist, order-only entitlement and trial_lifecycle).
- **End to end after deploy:** a test org in Spain (Madrid), employees:
  - one above the maximum base (€8,000);
  - one temporary contract;
  - one on 14 pays.
  Then a run, approve, payslips and the 3 reports, checked against hand-calculated Social Security.

## What the owner provides
1. **The AEAT "Algoritmo de cálculo de retenciones 2026" documents** (both versions) for P4. Everything else can be built before they arrive.
2. Optional:
   - the group 1–3 minimum bases (G-02);
   - an example AT/EP rate for the test employer.
