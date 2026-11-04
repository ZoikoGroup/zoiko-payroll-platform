# New Zealand (NZ): implementation hand-off for phases P3–P10

**Spec:** `Jur_doc/Zoiko_Payroll_New_Zealand_Engineering_Implementation_Wireframe_v1.0.docx` (ZP-NZ-ENG-001). Rules NZ-001..NZ-026, gates G1..G7, acceptance AC-NZ-01..08.
**Branch:** `venu`. P0–P2 are committed (`62be8d8`, `2293e11`, `c8b1494`) and **not pushed**.
**Template:** Japan (JP), which is fully built in this repository. For almost every NZ file below there is a Japan file that does the same job; read it first and mirror it.

---

> **Read `docs/new_zealand/REVIEW_P3_P4_WIP_2026-11-03.md` first.** It lists every defect in a rejected earlier P3/P4 attempt (backed up, not in the tree). Do not repeat them.

## 0. Ground rules (read before writing any code)

These rules are not optional. Each one comes from a real incident in this repository.

| # | Rule |
|---|---|
| R1 | **Never read `.env` files**, directly or indirectly. Never run a script that connects to a database. `app.database` points at a real remote PostgreSQL. Tests are safe: `tests/conftest.py` uses in-memory SQLite. |
| R2 | **Never run a seed script, `alembic upgrade` or `alembic stamp` against any database.** Migrations are verified by the SQLite tests listed below. |
| R3 | **Commit only on `venu`. Never push, never create a remote branch.** One commit per phase. Message format: `New Zealand Pn: <summary>`. |
| R4 | **No statutory number in code, DB CHECK constraints or the frontend.** Every rate, threshold, due date, age, multiplier and rounding rule is read from the content pack (`new_zealand_content.py` → pack rows → `ctx.rate_map` / `ctx.slabs`). `tests/test_nz_content.py::test_nz_engine_code_holds_no_statutory_literal` enforces this for engine files. |
| R5 | **Fail closed.** A missing row, an empty authority table, a `PENDING_G1` value, an unknown tax code, a `REVIEW` earning class or missing evidence raises `NZCalculationBlockedError(key, reason)`. Never fall back to a default and never "closest-match" a code. |
| R6 | **Versioning (NZ-020).** Statutory rows are never updated in place. A change inserts a new row (`previous_version_id` → old row), and approval flips the old row `ACTIVE → SUPERSEDED` and closes its `effective_to`. |
| R7 | **Four-eyes (NZ-024).** Every approval calls `service.require_four_eyes(preparer, approver, what, db=db, entity_type=..., entity_id=...)` (`service.py:15709`). Every write needs a reason and writes an audit row. |
| R8 | **Migrations** copy `alembic/versions/0e697c2388bf_nz_foundation.py` exactly. That means:<br>• the revision id comes from `python -c "import uuid;print(uuid.uuid4().hex[:12])"`;<br>• **literal** table and column names inside `op.create_table("...")` / `op.add_column("...")` (the deploy drift filter parses them);<br>• `SET LOCAL lock_timeout='5s'` on PostgreSQL;<br>• idempotent upgrade and downgrade;<br>• RLS through `_rls_for_new_tables` (TENANT for employer-level tables, `_worker_predicate("org")` for tables with `employee_id` / `payslip_item_id`);<br>• one new single head. |
| R9 | **After every migration**, update all of the following:<br>• run `python -I scripts/update_migration_manifest.py` (from `backend/`); it must add exactly one line;<br>• `tests/test_alembic_metadata.py`: the head in 2 places, plus the revision count (+1 each);<br>• `tests/test_migration_idempotency.py`: add the id;<br>• `tests/test_deploy_migrate_script.py`: add the new tables to `nz_tables` and the new columns to `nz_run_columns`, or to a new dict;<br>• `tests/test_south_africa_migrations.py`: `NZ_TABLES` and the column sets;<br>• `tests/test_japan_migrations.py` and `tests/test_nz_migrations.py::test_deploy_drift_filter_explains_every_nz_object`, which become supersets. |
| R10 | **Routes.** Whenever routes change, regenerate the route registry: `cd backend && python -m app.core.authz.generate`. Handler function names must be `nz_`-prefixed (the call graph resolves by simple name). Commit `app/core/authz/route_registry.json` and `docs/privacy/route_policy_inventory.csv`. |
| R11 | **Line endings.** The repo uses `core.autocrlf=input`. If you edit files with a script, preserve the existing newline style (`open(..., newline="")`). |
| R12 | **Frontend.** Before every frontend commit, run `npm run build`, `npm run check:undefined` and `npm test`. A Vite build alone misses undefined components; this blanked production once (9fc1a36). |
| R13 | **Never put an IRD number, bank account, child-support notice content or family-violence detail** in a log, an exception message, an analytics event, a test fixture string that looks real, or an API response (NZ-023, NZ-025). Use `nz_ird_number.masked()`. |

### Verification commands (from `backend/`)
```
python -m pytest -q -p no:cacheprovider -n 4 tests/test_nz_*.py
python -m pytest -q -p no:cacheprovider -n 4 tests/test_alembic_metadata.py tests/test_alembic_migration_manifest.py tests/test_deploy_migrate_script.py tests/test_migration_idempotency.py tests/test_south_africa_migrations.py tests/test_japan_migrations.py
python -m pytest -q -p no:cacheprovider -n 4 tests/test_japan_*.py tests/privacy
python -m pytest -q -p no:cacheprovider -n 4 tests        # full suite, about 20 minutes, before each commit
```
Frontend (from `frontend/`): `npm run build && npm run check:undefined && npm test`.

---

## 1. What already exists (P0–P2)

| File | What it gives you |
|---|---|
| `backend/app/core/jurisdiction.py` | `JURISDICTION_TAX_SCHEMAS["NZ"]` (public NZBN only); `nz_ird_number_valid()` (IRD mod-11); aliases `new zealand / aotearoa / nzl / nz → NZ`. NZ is deliberately **not** in `REGISTRATION_COUNTRIES`. |
| `backend/app/config.py` | `NZ_TENANT_ONBOARDING_ENABLED=False`, `NZ_IRD_KEYRING=""`, `NZ_IRD_FINGERPRINT_KEY=""`. |
| `backend/app/modules/payroll/nz_dormancy.py` | `onboarding_enabled()`, `is_new_zealand()`, `entering_nz_refusal()`. Already wired into `tax_resolver.get_jurisdiction_change_block_reason` and `service.get_company_details` / `update_company_details`. |
| `engine/countries/new_zealand.py` | **Stub**: `calculate(ctx)` always raises `NZ_ENGINE_NOT_BUILT`. Registered as `standard._COUNTRY_CALC["NZ"]`. `resolver.py` blocks simple mode (`NZ_SIMPLE_MODE_UNSUPPORTED`). |
| `engine/jurisdictions/new_zealand/errors.py` | `NZCalculationBlockedError(key, reason, organization_id=None)`, a subclass of `shared.MissingComplianceConfigurationError`. |
| `engine/countries/new_zealand_content.py` | The whole Draft catalogue: `NZ_SCALAR_CONTENT` (row shape `(key, label, ee_pct, er_pct, flat_amount, text_value, source, pending_g1, eff_from, eff_to)`), `NZ_PARAMETER_KEYS` (kind per key), `NZ_PAYE_BANDS`, `NZ_ESCT_BANDS`, `NZ_TAX_CODES`, `SUPPORTED_TAX_CODES`, `REFUSED_TAX_CODES`, `NZ_EARNING_CLASSES`, `NZ_COMPONENTS`, `OBLIGATIONS`, `TREATMENTS`, `NZ_EMPTY_TABLES` (+ rule types), `NZ_EMPTY_BY_DESIGN`, `NZ_REGIONS`, `NZ_DEFERRED` reason codes, `NZ_EXPORT_SCHEMAS={}`, `NZ_ELA_2028`, `content_rows_in_force(payday)`. |
| `payroll/new_zealand_service.py` | `seed_nz_pack(db)` (Draft pack + empty `NZ-ELA-2028`) and `nz_pack_activation_refusal(db, pack, actor_id=None, today=None)`. **No hooks yet, and NZ is not yet in `jurisdiction_hooks._MODULES`.** |
| `backend/scripts/seed_nz_canonical_packs.py` | Local-DB-guarded seeder (never run it, R2). |
| Migration `0e697c2388bf_nz_foundation.py` (current single head) | Tables `payroll_nz_employer_profiles`, `payroll_nz_ird_vault`, `payroll_nz_ird_access_events`, `payroll_nz_employee_tax_profiles`, `payroll_nz_kiwisaver_elections`, `payroll_nz_authority_deductions`, `payroll_nz_work_pattern_versions`, `payroll_nz_accumulator_entries`; columns `payslip_items.nz_calculation_snapshot`, `payroll_runs.nz_approval_fingerprint`, `payroll_runs.nz_payment_kind`. |
| `payroll/models.py` (end of file) | `PayrollNz*` models for the tables above, plus the shared `_NzCommon` mixin (id, organization_id, legal_entity_id, evidence_ref, previous_version_id, created_by_id, approved_by_id, approved_at, created_at). **Reuse `_NzCommon` for every new NZ table.** |
| `payroll/nz_ird_number.py` | `normalise`, `encrypt(number, owner)`, `decrypt(ct, version, owner)`, `reencrypt`, `fingerprint`, `vault_owner(org_id, subject_type, subject_id, vault_id)`, `masked()`, `IrdNumberError`. The owner binding is mandatory. |
| Tests | `test_nz_scaffold.py`, `test_nz_content.py`, `test_nz_migrations.py`, `test_nz_ird_number.py`. |

### Owner decisions already taken (do not re-decide)

| Decision | Ruling |
|---|---|
| D-1 | The NZ legal employer is `(organization_id, legal_entity_id)`; a NULL legal entity is the organisation itself. Employer profile, accumulators and remittance are keyed this way. `PayrollEmployee.legal_entity_id` exists (`models.py:145`). |
| D-2 | Spec values are seeded but every row is `PENDING G1`. Authority tables stay empty until their gate. |
| D-3 | Payday filing = snapshot + state machine + **JSON preview only**. Transport and export are refused while `NZ_EXPORT_SCHEMAS == {}`. |
| D-4 | IRD numbers live only in `payroll_nz_ird_vault`, through `nz_ird_number.py`. Japan's code stays untouched. |
| D-5 | The full current Holidays Act is in scope. Employment Leave Act 2028 exists only as the empty, never-activatable `NZ-ELA-2028` pack. |
| D-6 | Deferred and refused with `NZ_DEFERRED` codes: WT/CAE/EDW/NSW codes, non-residents, ESS, bureau filing, ESCT PAYE-alternative, ACC invoices. |
| D-7 | Retention: wage, time and leave records 6 years (from content). Tax-record retention is `PENDING_DECISION`, not guessed. |

### Authority-table row formats (all `TaxSlab` rows; define them in the `new_zealand_content.py` docstring in P3)

| `rule_type` | Columns used |
|---|---|
| `NZ_PAYE_METHOD` | one row per frequency: `filing_status`=WEEKLY/FORTNIGHTLY/FOUR_WEEKLY/MONTHLY, `flat_amount`=periods per year, `tax_formula`=method id from the IRD spec (`ANNUALISE_BANDS`) |
| `NZ_SECONDARY_RATE` | `filing_status`=SB/S/SH/ST/SA, `rate_pct` |
| `NZ_ND_RATE` | one row: `rate_pct` |
| `NZ_IETC` | band rows: `min_amount`, `max_amount`, `flat_amount`=credit, `rate_pct`=abatement |
| `NZ_CS_VARIATION` | `filing_status`=variation code, `rate_label`=meaning |
| `NZ_LUMP_SUM` | `tax_formula`=method id, `flat_amount`/`rate_pct` per the IRD spec |
| `NZ_HOLIDAY_ADVANCE` | `filing_status`=STANDARD/ALTERNATIVE, `tax_formula`=method id |
| `NZ_IRD_EXAMPLE` | `formula_expression`=JSON `{"inputs":{...},"expected":{...}}` |
| `NZ_PUBLIC_HOLIDAY` | `effective_from`=date, `jurisdiction_state`=ISO 3166-2 region (NULL = national), `rate_label`=name |
| `NZ_ACC_CLASSIFICATION` | employer content: `filing_status`=CU code, `rate_pct` |

---

## P3: Pure calculation engine (spec §3–§7)

> **The full build plan for P3 is `docs/new_zealand/P3_CALCULATION_ENGINE_PLAN.md`.** It has every
> function signature, the step-by-step rules, the `nz_result` schema, the hashing and the complete test
> list. Where it differs from the summary below, follow that document.
> **The file-by-file code blueprint is `docs/new_zealand/P3_CODE_ARCHITECTURE.md`.** It has the file tree,
> dependency graph, call sequence, a pseudocode skeleton for every function, the exact edit anchors,
> a worked example and the test-function names.

**Goal.** Replace the stub with a deterministic, pure `calculate(ctx)`. Test it with a **synthetic signed pack built inside the tests** (values labelled TEST). The shipped pack must still block.

### Files
| File | Action |
|---|---|
| `engine/base.py` | Add the `PayrollContext` fields below next to the `jp_*` block (~line 983), and `PayrollResult.nz_result: dict = None` next to `jp_result` (~line 1752). |
| `engine/countries/new_zealand.py` | Replace the stub (pipeline below). Mirror `engine/countries/japan.py` structure: `_Pack` class (`row`, `require_amount`, `require_pct_total`, `require_text`, `rounder`, `block`), `resolve_applicability`, `obligation_base`. **Add one thing Japan lacks:** `_Pack.row()` blocks when the row's `label` contains `[PENDING G1]` (defence in depth). |
| `engine/jurisdictions/new_zealand/paye.py` | new |
| `engine/jurisdictions/new_zealand/acc_earner_levy.py` | new |
| `engine/jurisdictions/new_zealand/student_loan.py` | new |
| `engine/jurisdictions/new_zealand/kiwisaver.py` | new |
| `engine/jurisdictions/new_zealand/esct.py` | new |
| `engine/jurisdictions/new_zealand/child_support.py` | new |
| `engine/jurisdictions/new_zealand/deduction_precedence.py` | new |
| `engine/jurisdictions/new_zealand/minimum_wage.py` | new |
| `engine/jurisdictions/new_zealand/errors.py` | Add the reason-code constants (list below). |
| `engine/standard.py` | Add NZ deductions and result passthrough, mirroring `jp_employee_total` (line ~358) and `jp_result=deductions.get("jp_result")` (line ~644). |
| `engine/countries/new_zealand_content.py` | Docstring only: document the authority-table row formats above. |
| `tests/test_nz_engine.py`, `tests/test_nz_golden.py` | new |

### `PayrollContext` fields
| Group | Fields |
|---|---|
| Records | `nz_employer_profile: dict = None`, `nz_tax_profile: dict = None`, `nz_kiwisaver: dict = None`, `nz_authority_deductions: list = None`, `nz_work_pattern: dict = None` |
| Ledger and hours | `nz_accumulators: dict = None` (`{obligation: Decimal}`, the YTD sum **before** this payday, same employee + legal entity + tax year), `nz_hours: Decimal = None`, `nz_hours_source: str = None` |
| Pay details | `nz_payment_kind: str = None` (None = REGULAR), `nz_pay_frequency: str = None`, `nz_date_of_birth: date = None`, `nz_components: dict = None` (`{"SALARY": Decimal, "OVERTIME": ...}`) |
| Identity (trace only) | `nz_organization_id`, `nz_legal_entity_id`, `nz_employee_id` |

The **payday is `ctx.pay_date`**. Every effective-dated row and pack row is selected by payday (NZ-008), never by period end.

### Module contracts (pure: no DB, no clock, no network; NZ-022)

**`paye.py`**
- `route_tax_code(code, catalogue_slabs)` → `MAIN|SECONDARY|SPECIAL`. An unknown code raises `NZ_TAX_CODE_UNSUPPORTED`; a refused code raises `NZ_TAX_CODE_REFUSED:<code>`.
- `main_paye(gross, frequency, bands, method_row, ietc_rows, is_me, rounder)` → `(amount, steps)`. Annualise by `method_row.flat_amount`, apply bands (rate on the part above `min_amount`), apply IETC for ME codes, de-annualise, round with `nz_paye_rounding`. An empty `NZ_PAYE_METHOD` blocks `NZ_TABLE_EMPTY:paye_main_method`; ME with no IETC rows blocks `NZ_TABLE_EMPTY:ietc_parameters`.
- `secondary_paye(gross, code, rate_rows, rounder)` uses the flat rate for the code.
- `nd_paye(gross, nd_row, rounder)`.
- `stc_paye(gross, profile, pay_date, rounder)`: the certificate is valid only for `tailored_valid_from <= payday <= tailored_valid_to`, else `NZ_STC_OUT_OF_WINDOW`.

**`acc_earner_levy.py`**
- `levy(acc_gross, ytd_liable, cap, rate, rounder)` → `{liable, levy, cap_crossed, ytd_after}` with `liable = min(acc_gross, max(cap - ytd_liable, 0))`.
- `ytd_liable` comes from `ctx.nz_accumulators["ACC_LIABLE_EARNINGS"]`. If it is missing, block `NZ_ACC_ACCUMULATOR_MISSING` (never assume 0, except that P4 supplies an explicit 0 for a first payday in the tax year).
- Reported inside PAYE but traced separately (§6).

**`student_loan.py`**
- `deduct(gross, frequency, code_has_sl, income_class, profile, pay_date, pack, extra_notices, rounder)`.
- MAIN: `max(0, gross - threshold_for_frequency) * nz_sl_rate`.
- SECONDARY: `gross * nz_sl_rate` (`nz_sl_secondary_basis == WHOLE_PAYMENT`, else block).
- A certificate in window overrides (SPECIAL_DEDUCTION_RATE → its rate, NIL_DEDUCTION → 0).
- Then add APPROVED `STUDENT_LOAN_EXTRA` notices.

**`kiwisaver.py`**
- `eligibility(election, dob, pay_date, pack)` → `CONTRIBUTING|NOT_DEDUCTING(reason)`.
- `SAVINGS_SUSPENSION` counts only with `suspension_ref` and the payday inside `[suspension_from, suspension_to]` (NZ-009); a zero deduction is never inferred.
- `employee_deduction(ks_gross, election, pay_date, pack, rounder)`: the rate must be in `nz_ks_employee_rates` (or equal `nz_ks_temporary_reduction_rate` inside the reduction window); no rate means `nz_ks_default_rate`.
- `employer_contribution(ks_gross, election, dob, pay_date, pack, esct_rate, rounder)` → `{gross, esct, net, destination}` (NZ-007):
  - compulsory only while CONTRIBUTING and age ≥ `nz_ks_employer_min_age`;
  - `nz_ks_employer_max_age` empty → block `NZ_ROW_MISSING:nz_ks_employer_max_age`;
  - employer rate ≥ `nz_ks_employer_min_rate`, unless `employer_matches_reduction` inside the reduction window;
  - `PAYE_ALTERNATIVE` → `NZ_KS_PAYE_ALTERNATIVE_UNSUPPORTED`.

**`esct.py`**
- `esct_rate(election, bands)`: `esct_rate_pct` must equal the band rate for `esct_basis_amount` (bands `NZ_ESCT_BAND`), else `NZ_ESCT_RATE_UNRESOLVED`.
- `esct(employer_gross, rate, rounder)`.

**`child_support.py`**
- `deduct(net_before, notices, pack, variation_rows, rounder)`.
- `max_allowed = net_before * nz_cs_max_deduction_pct/100` (protecting `nz_cs_protected_net_pct`).
- Amount = `min(sum(notice amounts), max_allowed)`.
- On a shortfall, return `{shortfall, variation_code}`. The variation code comes from `NZ_CS_VARIATION` rows; if they are empty, block `NZ_CS_VARIATION_CODE_MISSING` (NZ-012).
- A manual force is never possible.

**`deduction_precedence.py`**
- `order(pack)` parses `nz_deduction_precedence` (comma list of obligations). `PENDING_G1` blocks `NZ_PRECEDENCE_PENDING`.
- Tenant voluntary deductions always come after (NZ-011).

**`minimum_wage.py`**
- `check(pay_for_hours, hours, category, pack, pay_date)` → `PASS | FAIL(shortfall) | UNDETERMINABLE`.
- Never PASS without hours. The category comes from the tax profile (`EXEMPTION_PERMIT` → `UNDETERMINABLE` until signed).
- The result goes into `nz_result["exceptions"]`. It does **not** block the calculation; P4 blocks approval (NZ-015).

### Error codes (`errors.py`)
| Area | Codes |
|---|---|
| Pack and tables | `NZ_PACK_UNSIGNED`, `NZ_TABLE_EMPTY` (+ `:<table>`), `NZ_ROW_MISSING` (+ `:<key>`) |
| Tax profile | `NZ_TAX_PROFILE_MISSING`, `NZ_TAX_CODE_UNSUPPORTED`, `NZ_TAX_CODE_REFUSED`, `NZ_STC_OUT_OF_WINDOW`, `NZ_NON_RESIDENT_UNSUPPORTED` |
| Payment and pay basis | `NZ_EARNING_CLASS_REVIEW` (+ `:<component>`), `NZ_PAYMENT_KIND_UNSUPPORTED`, `NZ_FREQUENCY_UNSUPPORTED` |
| KiwiSaver / ESCT | `NZ_KS_RATE_UNSUPPORTED`, `NZ_KS_PAYE_ALTERNATIVE_UNSUPPORTED`, `NZ_ESCT_RATE_UNRESOLVED` |
| Accumulators and deductions | `NZ_ACC_ACCUMULATOR_MISSING`, `NZ_CS_VARIATION_CODE_MISSING`, `NZ_PRECEDENCE_PENDING` |
| Employer and payday | `NZ_EMPLOYER_PROFILE_MISSING`, `NZ_PAY_DATE_MISSING` |

### `calculate(ctx)` pipeline
1. **Guards.**
   - `pay_date` is present.
   - The frequency is in `nz_supported_pay_frequencies`.
   - The employer profile and tax profile are ACTIVE on the payday (`status`, `effective_from/to`).
   - The employee is resident.
   - `nz_payment_kind` is REGULAR; anything else raises `NZ_PAYMENT_KIND_UNSUPPORTED` until P6.
2. **Components → bases.** Use the `NZ_EARNING_CLASS` slabs.
   - Each obligation gets its own base: PAYE, ACC, KIWISAVER, STUDENT_LOAN, MIN_WAGE.
   - A REVIEW component with a non-zero amount blocks.
   - LUMP_SUM_PATH blocks until P6.
   - Build components exactly as `japan.pay_components` does: SALARY=basic, OVERTIME=overtime, named components from `ctx.nz_components`, and OTHER_EARNINGS = gross minus the named components.
3. **PAYE**, then the **ACC levy**.
4. **Student loan.**
5. **KiwiSaver** employee deduction, then employer gross → ESCT → net.
6. **Minimum-wage** exception.
7. **Child support** on `net_before = gross - paye - acc - ks_employee - sl`.
8. **Precedence** order, then net pay.
9. **Return** `{"nz_employee_total", "nz_result"}` as the deductions dict. Japan's equivalents show the expected shape:

```
nz_result = {
  "obligations": {"paye", "acc_levy", "student_loan", "ks_employee", "ks_employer_gross",
                  "esct", "ks_employer_net", "child_support"},          # Decimals as str
  "bases": {"PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "MIN_WAGE"},
  "accumulatorDeltas": {"ACC_LIABLE_EARNINGS", "PAYE_GROSS", "PAYE", "ACC_LEVY", "KS_GROSS",
                        "KS_EMPLOYEE", "KS_EMPLOYER_GROSS", "ESCT", "STUDENT_LOAN", "CHILD_SUPPORT"},
  "exceptions": [ {"code": "NZ_MIN_WAGE_FAIL"|"NZ_MIN_WAGE_UNDETERMINABLE"|"NZ_CS_SHORTFALL", ...} ],
  "settlement": {"ks_destination": ..., "complying_fund_ref": ...},
  "trace": {"taxCode", "incomeClass", "tableVersion", "periodFactor", "steps": [...],
            "roundingEvents": [...]},                                     # NZ-005
  "packHash": ..., "inputHash": ..., "engineVersion": "nz-engine-1"
}
```

`inputHash` and `packHash` are SHA-256 over canonical JSON (sorted keys, Decimal as str) of the inputs used and of the rows used.

### `standard.py` mapping
- **taxes** = PAYE + ACC levy.
- **deductions** = KS employee + student loan + child support (`nz_employee_total`).
- **employer contribution** = KS employer gross. ESCT is inside the gross; do not add it twice.

### Tests (`tests/test_nz_engine.py`)
Build the pack in a fixture with a helper `signed_pack(**overrides)` that returns a `rate_map` and `slabs` with `[PENDING G1]` removed and TEST labels. Cover:
- **PAYE:** every band edge (just below and above each `min_amount`), every supported code, a refused code, an unknown code, STC inside and outside its window, all 4 frequencies.
- **ACC:** cap crossing (before, crossing, after), and two pay groups sharing one accumulator.
- **Student loan:** main threshold edges, secondary whole payment, certificate rate, nil certificate.
- **KiwiSaver:**
  - a period straddling 1 April with payday 2 April uses the new rate (NZ-008);
  - the 3% reduction inside and outside its window;
  - a 16-year-old member gets the employer contribution;
  - suspension without evidence blocks;
  - an employer rate below the minimum blocks;
  - PAYE_ALTERNATIVE is refused.
- **ESCT:** each band edge, and a rate that disagrees with its basis.
- **Child support:** normal, low pay with shortfall and variation code, two notices, variation table empty → block.
- **Minimum wage:** adult and starting-out boundaries, no hours → UNDETERMINABLE.
- **General:**
  - a REVIEW component blocks;
  - determinism (same input → same `inputHash` and identical result);
  - the **shipped** content (built from `new_zealand_content` without removing PENDING) blocks with `NZ_PACK_UNSIGNED`.

`tests/test_nz_golden.py` loads `NZ_IRD_EXAMPLE` rows and asserts exact equality. It is `pytest.skip("G1: IRD official examples not loaded")` while the table is empty (AC-NZ-01).

**Done when:** the NZ tests, `test_nz_content.py` (including the no-literal test) and the Japan engine tests are green, and the full suite is green.

---

## P4: Service hooks, organisation APIs, run binding

> **Full build plan: `docs/new_zealand/P4_SERVICE_HOOKS_AND_API_PLAN.md`** (file tree, every service function, the 13 hooks, 26 routes, exact `service.py` anchors, test names). Where it differs from the summary below, follow that document.

**Goal.** Wire the engine to real records and pay runs, still dormant (every route returns 404 unless the flag is on and the org is NZ).

### Files
| File | Action |
|---|---|
| `payroll/new_zealand_service.py` | Extend it: inputs, snapshots, the 13 hooks, versioned writers, the vault workflow, preflight. Mirror `japan_service.py` (hook map at line ~1040; `resolve_jp_calc_inputs` ~430; `calc_inputs` ~499; `jp_freeze_context` ~581; `jp_approval_fingerprint` ~703; `before_run_transition` ~731). |
| `payroll/nz_org_router.py` | New. Mirror `japan_org_router.py` (dependency `require_japan_tenant`, line 32; router prefix line 46). |
| `payroll/jurisdiction_hooks.py` | `_MODULES["NZ"] = "app.modules.payroll.new_zealand_service"`. **Only after all 13 hooks exist**: the registry fails closed. |
| `payroll/router.py` | `payroll_router.include_router(nz_org_router.router)`, next to the Japan include. |
| `engine/resolver.py` | `build_context_from_employee(..., nz_inputs: dict \| None = None)`, merged exactly like `japan_inputs` (lines 281 / 486). |
| `payroll/service.py` | Add an `nz_inputs` block **after each Japan block** at the four call sites: preview (~20419, `as_of=period_end`, the run's pay date), generate (~25646), add_payslip_item (~32730); pass `nz_inputs=` where `japan_inputs=` is passed (~20614, ~25781, ~32880); freeze like `_jp_service.jp_freeze_context` (~25816, ~32904) and store `nz_calculation_snapshot` (~25989, ~32949); `_serialize_payslip` (~33652) returns `"nzCalculationSnapshot"` without `frozenContext` when the item is NZ. **NZ uses the run's `pay_date`, never period end.** |
| `payroll/schemas.py` | `nzPaymentKind` (Literal of `content.PAYMENT_KINDS`, optional) on run create/update/response, mirroring `jpPaymentKind`; `nzCalculationSnapshot: Optional[dict]` on `PayslipItemResponse`. |
| `payroll/employee_validation.py` | `NZEmployeeValidation` in `_DORMANT_STRATEGIES`, gated in `_dormant_strategy` by `nz_dormancy.onboarding_enabled()`. Its `SENSITIVE_FIELDS` must include any IRD-like key; the IRD number is never a compliance field. **First check how Japan employees pass validation:** JP is in neither map today. |
| `app/core/authz/route_registry.json`, `docs/privacy/route_policy_inventory.csv` | Regenerate (R10). |
| `tests/test_nz_phase4.py` | new |

### Service functions (signatures)
```python
# The tax year (for accumulators) comes from the pack window in force on the payday
# (content.NZ_2026_27 -> "2026-27"), never from a hard-coded 1 April.
def resolve_nz_calc_inputs(db, organization_id, employee, pay_date, run=None) -> dict
    # Loads the ACTIVE versions in force ON THE PAYDAY:
    #   employer profile  (by employee.legal_entity_id, else the org-level row; none -> leave None)
    #   tax profile, KiwiSaver election, work pattern, APPROVED authority notices
    #   accumulators: SUM(amount) of payroll_nz_accumulator_entries for
    #     (employee, legal_entity_id, tax_year) with pay_date < payday, grouped by obligation;
    #     explicit Decimal("0") when the employee has no entries this tax year
    #   hours: approved attendance in the period; else contracted hours from the work pattern
    #   nz_payment_kind from run.nz_payment_kind (None -> REGULAR)
    # Infers nothing.
def calc_inputs(db, run=None, employee=None, resolved_pack=None, as_of=None, period=None) -> dict
def nz_freeze_context(ctx, calculation_mode="standard") -> dict      # JSON-safe, Decimal as str
def nz_thaw_context(frozen) -> PayrollContext
def nz_replay(frozen) -> dict                                         # recompute; must equal the stored result
def nz_input_hash(frozen) -> str
def nz_payslip_snapshot(result, frozen=None) -> dict | None           # {"frozenContext", "nzResult", "hashes"}
def nz_approval_fingerprint(db, run) -> str | None                    # sha256 over every payslip snapshot hash + pack hash + engine version
def nz_run_preflight(db, run) -> list[dict]                           # [{"code", "employeeId", "message"}]
def before_run_transition(db, run, next_status, actor_id) -> None
```

### `before_run_transition`
| Transition | Checks |
|---|---|
| → `APPROVED` | Every payslip has `nz_calculation_snapshot`; the employer profile is `VERIFIED`; no `NZ_MIN_WAGE_*` or `NZ_CS_SHORTFALL` exception without an approved run exception (P8; until then, refuse); `nz_run_preflight` is empty; store `run.nz_approval_fingerprint`. |
| → `AUTHORIZED` / `PAID` | The recomputed fingerprint equals the stored one. |
| → `PAID` | Insert `payroll_nz_accumulator_entries` (`entry_kind="RUN"`, one row per obligation from `accumulatorDeltas`, `result_hash`). It is idempotent through `uq_nz_accum_payslip_obligation`: skip rows that already exist and never double-post. |

### The 13 hooks (`JURISDICTION_HOOKS`; names must match exactly)
| Hook | Function |
|---|---|
| `calc_inputs` | `calc_inputs` |
| `before_run_transition` | `before_run_transition` |
| `statutory_profile_errors` | `_nz_statutory_profile_errors(data) -> list` (code supported, STC complete, IRD state consistent, minimum-wage evidence present) |
| `statutory_profile_values` | `_nz_profile_values(db, employee, data, previous) -> {}` |
| `pack_activation_refusal` | `_nz_pack_activation_refusal(db, pack, actor_id)` → calls `nz_pack_activation_refusal` |
| `retention_settings` | `_nz_retention_settings()` → `retention_service.RetentionJurisdiction` (wage/time/leave years from `nz_record_retention_years`; tax records `PENDING_DECISION`). Copy `_jp_retention_settings` (~line 964) **including its signature**: Japan once broke the retention report for every country with a wrong signature. |
| `service_registry_transition` | `_nz_service_registry_transition(db, target, reason, actor_id)` → `service.transition_service_registry(db, "NZ", target, reason, actor_id, label="New Zealand", readiness=nz_unmet_requirements, ...)`. Until P9, `nz_unmet_requirements` returns `["Release gates G1–G7 are not implemented yet"]`. |
| `statutory_summary` | `statutory_summary(db)`: packs, row counts, pending counts, empty tables, decisions D-1..D-7 |
| `statutory_editors` | `_nz_statutory_editors(db, pack) -> set()` |
| `template_activation_refusal` | always refuses `NZ` / `NZ_*` templates |
| `pack_holidays` | `_nz_pack_holidays(db, year)` → `NZ_PUBLIC_HOLIDAY` rows of the in-force pack (`[]` until G2) |
| `payment_treatment` | `_nz_payment_treatment(...) -> {}` |
| `payslip_hold_view` | `_nz_payslip_hold_view(item) -> None` |

### Versioned writers (R6 + R7)
- `create_nz_employer_profile_version(db, org_id, data, actor_id)` / `approve_nz_employer_profile(db, org_id, row_id, actor_id)`.
- The same pair for `tax_profile`, `kiwisaver_election` and `work_pattern`.
- `import_nz_authority_notice(db, org_id, employee_id, meta, file_bytes, actor_id)`: `file_hash=sha256(file_bytes)`; a re-import with the same `notice_id` gets `version+1` and `replaces_id`. **Store only the hash plus `evidence_ref`, never the file body.**
- `approve_nz_authority_notice`, `revoke_nz_authority_notice`.
- `record_nz_opening_accumulator(db, org_id, employee_id, obligation, amount, tax_year, evidence_ref, actor_id)` creates a **pending** request; `approve_nz_opening_accumulator` (a different user) inserts the `OPENING_BALANCE` entry with `approved_by_id`.

### IRD vault workflow
- `create_nz_ird_number(db, org_id, subject_type, employee_id|None, legal_entity_id|None, raw, actor_id)`:
  1. normalise;
  2. compute the fingerprint and refuse a duplicate;
  3. insert the vault row with a placeholder;
  4. compute `vault_owner(...)` with the new id and encrypt;
  5. write the `CREATE` event.
- `request_nz_ird_reveal(..., reason)`, then `approve_nz_ird_reveal(...)` by a different user, then `reveal_nz_ird_number(...)`: single use, writes a `REVEALED` event, and returns the digits **only in that response**.
- `delete_nz_ird_number(...)`: `ciphertext=None`, `status=DELETED`, plus a `DELETED` event.

### `nz_org_router.py`
- Prefix `/new-zealand` (full path `/api/payroll/new-zealand`), `dependencies=[Depends(require_nz_tenant)]`.
- `require_nz_tenant` returns 404 unless `nz_dormancy.onboarding_enabled()` and the caller's org is NZ.
- Reads use `get_current_payroll_operator`; writes use `get_current_org_admin` (`app.core.dependencies`).
- Every handler name starts with `nz_`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/summary`, `/readiness` | |
| GET / POST | `/employer-profiles` | |
| POST | `/employer-profiles/{id}/approve` | |
| GET / POST | `/employees/{eid}/tax-profiles` | |
| POST | `/tax-profiles/{id}/approve` | |
| GET / POST | `/employees/{eid}/kiwisaver` | |
| POST | `/kiwisaver/{id}/approve` | |
| GET / POST | `/employees/{eid}/work-patterns` | |
| POST | `/work-patterns/{id}/approve` | |
| GET / POST | `/employees/{eid}/authority-deductions` | notice upload (multipart) |
| POST | `/authority-deductions/{id}/approve`, `/authority-deductions/{id}/revoke` | |
| GET / POST | `/employees/{eid}/accumulators/opening` | |
| POST | `/accumulators/opening/{id}/approve` | |
| GET / POST / DELETE | `/employees/{eid}/ird-number` | GET returns `{"onFile": bool, "masked": masked()}` only |
| POST | `/employees/{eid}/ird-number/reveal-requests` | |
| POST | `/ird-number/reveal-requests/{id}/approve` | |
| POST | `/ird-number/reveal-requests/{id}/reveal` | |
| GET / POST / DELETE | `/employer-profiles/{id}/ird-number` (+ the same reveal flow) | |
| GET | `/runs/{rid}/preflight`, `/runs/{rid}/fingerprint` | |
| GET | `/employees/{eid}/summary` | for the P7 panel |

Reveal requests need storage. Add them to `payroll_nz_ird_access_events` as `REVEAL_REQUESTED` / `REVEAL_APPROVED` rows (`previous_version_id` links approval → request); **no new table is needed**.

### Tests: `tests/test_nz_phase4.py`
- All 13 hooks resolve via `jurisdiction_hooks.get("NZ", name)`.
- Every NZ route returns 404 with the flag off, and for a non-NZ org.
- Four-eyes refuses a self-approval and writes the audit row.
- A new version supersedes and the old row is unchanged.
- STC without a certificate is refused.
- A notice re-import creates v2 with `replaces_id`.
- A duplicate IRD number is refused; reveal needs a different approver, is single use, and writes events; no response or log contains digits (use `caplog`).
- APPROVED is refused on a minimum-wage exception, on an unverified employer, and on a fingerprint changed after approval.
- PAID posts the accumulator once, and a retry posts nothing.
- `nz_replay(frozen)` equals the stored result.
- `calc_inputs` picks rows by **payday** (a 1-April straddle).
- Also `tests/privacy/test_route_registry.py`, and `tests/test_mexico_scaffolding.py` (its `_MODULES` expectation map needs `"NZ"` added).

---

## P5: Holidays Act I (employments, entitlements, gross-earnings ledger, public holidays; §8, gate G2)

> **Full build plan: `docs/new_zealand/P5_HOLIDAYS_ACT_ENTITLEMENTS_PLAN.md`** (5 tables with every column, the pure entitlement engine, family-violence privacy, test names). Where it differs from the summary below, follow that document.

**Goal.** The entitlement side of the Holidays Act 2003: who is entitled to what, when, and why. **No generic hours-accrual balance is ever the legal source of truth (NZ-016).**

### Migration `<hex12>_nz_holidays_act.py` (down_revision = `0e697c2388bf`)
All tables use `_common()` unless noted, and WORKER RLS.

**`payroll_nz_employments`** (employment instances; rehire = new instance, §10)

| column | type | notes |
|---|---|---|
| employee_id | FK payroll_employees CASCADE NOT NULL | |
| start_date | Date NOT NULL | anniversary anchor |
| end_date | Date | |
| continuity_rule | String(20) | `NEW_INSTANCE` / `CONTINUOUS`; CONTINUOUS needs `evidence_ref` (CHECK) |
| termination_reason | String(30) | |
| payg_eligible | Boolean NOT NULL default false | pay-as-you-go 8% eligibility |
| payg_basis | String(24) | `FIXED_TERM_UNDER_12_MONTHS` / `IRREGULAR_INTERMITTENT`; required when `payg_eligible` (CHECK); never a default for "casual" |
| payg_agreement_ref | String(300) | required when `payg_eligible` (CHECK) |
| status | String(12) | `ACTIVE` / `ENDED` |

Unique: one `ACTIVE` row per employee and legal entity (partial index).

**`payroll_nz_leave_entitlements`**

| column | type | notes |
|---|---|---|
| employee_id, employment_id | FKs | |
| leave_type | String(20) | `ANNUAL` / `SICK` / `BEREAVEMENT_CLOSE` / `BEREAVEMENT_OTHER` / `FAMILY_VIOLENCE` / `ALTERNATIVE` |
| qualifying_date | Date NOT NULL | |
| entitlement_date | Date NOT NULL | the anniversary on which it vests |
| unit | String(6) | `WEEKS` / `DAYS` |
| quantity | Numeric(8,4) NOT NULL | |
| carried_balance | Numeric(8,4) | sick carry-over is capped from content |
| taken | Numeric(8,4) NOT NULL default 0 | |
| source | String(40) | `HOLIDAYS_ACT_2003` / `EMPLOYMENT_AGREEMENT` |
| expires_on | Date | |
| status | String(12) | `ACTIVE` / `EXHAUSTED` / `PAID_OUT` / `SUPERSEDED` |

Unique `(employment_id, leave_type, entitlement_date)`.

**`payroll_nz_gross_earnings_ledger`** (written at PAID, append-only, no `updated_at`)

| column | type | notes |
|---|---|---|
| employee_id, employment_id | FKs | |
| run_id, payslip_item_id | FKs SET NULL | |
| pay_date | Date NOT NULL | |
| period_start, period_end | Date | |
| category | String(30) | the statutory gross-earnings category (component) |
| amount | Numeric(14,2) NOT NULL | |
| included | Boolean NOT NULL | |
| reason | String(120) NOT NULL | why it was included or excluded |
| days_worked | Numeric(6,2) | for ADP |

Unique `(payslip_item_id, category)`.

**`payroll_nz_public_holiday_decisions`**

| column | type | notes |
|---|---|---|
| employee_id, employment_id | FKs | |
| holiday_date | Date NOT NULL | |
| holiday_name | String(80) | |
| region | String(3) | ISO 3166-2 code from content `NZ_REGIONS`, or NULL for national |
| otherwise_working_day | String(12) | `YES` / `NO` / `UNDETERMINED`; UNDETERMINED blocks approval |
| owd_basis | String(40) | e.g. `WORK_PATTERN_FIXED`, `ROSTER`, `HISTORY_REVIEW` |
| owd_evidence_ref | String(300) | |
| worked | Boolean NOT NULL | |
| hours_worked | Numeric(6,2) | includes the portion crossing midnight that falls on the holiday |
| shift_start, shift_end | DateTime(tz) | |
| alternative_holiday_id | FK payroll_nz_leave_entitlements | |
| status | String(12) | `DRAFT` / `APPROVED` / `SUPERSEDED` |

**`payroll_nz_leave_events`** (requests taken against entitlements)

| column | type | notes |
|---|---|---|
| employee_id, employment_id, entitlement_id | FKs | |
| leave_type | String(20) | |
| start_date, end_date | Date | |
| quantity | Numeric(8,4) | |
| unit | String(6) | |
| source_request_id | FK payroll_leave_requests SET NULL | the generic request it came from |
| restricted | Boolean NOT NULL default false | TRUE for FAMILY_VIOLENCE (CHECK) |
| evidence_ref | | |
| status | String(12) | `REQUESTED` / `APPROVED` / `PAID` / `CANCELLED` |

**No reason, narrative or free-text column** (NZ-023).

### Code
- **`engine/jurisdictions/new_zealand/holidays_act.py`** (pure):
  - `annual_entitlement(employment, as_of, pack)` → vests `nz_hol_annual_weeks` weeks on each anniversary after `nz_hol_annual_qualifying_months`;
  - `sick_entitlement(employment, prior_balance, as_of, pack)` → 10 days after 6 months, not pro-rated, carry-over capped at `nz_hol_sick_carry_max`;
  - `bereavement_entitlement(kind, pack)`;
  - `family_violence_entitlement(employment, as_of, pack)`;
  - `otherwise_working_day(work_pattern, holiday_date, history)` → `YES` / `NO` / `UNDETERMINED`, with a reason;
  - `public_holiday_hours(shift_start, shift_end, holiday_date, tz)` handles midnight crossing in `Pacific/Auckland` / `Pacific/Chatham`.
- **`payroll/nz_leave_service.py`** (new):
  - `vest_entitlements(db, org_id, as_of)`, which is idempotent through the unique key;
  - `record_public_holiday_decision`, plus four-eyes `approve_public_holiday_decision`; a worked public holiday on an otherwise working day creates an `ALTERNATIVE` entitlement;
  - `sync_leave_request(db, request)`, which maps a generic `PayrollLeaveRequest` to an NZ leave event;
  - `write_gross_earnings(db, run)`, called from `before_run_transition` at PAID;
  - `nz_leave_balances(db, employee_id, viewer)`, which **hides `restricted` rows unless the viewer holds the restricted-leave permission**.
- **Permission.** Add `nz.family_violence.view` to the field/permission layer (`app/core/authz/fields.py` and `PayrollUserPermission`). Exports and manager views exclude these rows.
- **`_nz_pack_holidays`** returns national holidays plus the regional anniversary holiday for the region.
- **Routes** (add to `nz_org_router.py`):
  - `GET/POST /employees/{eid}/employments`, `POST /employments/{id}/end`;
  - `GET /employees/{eid}/leave-entitlements`, `POST /leave/vest`;
  - `GET/POST /employees/{eid}/public-holiday-decisions`, `POST /public-holiday-decisions/{id}/approve`;
  - `GET /employees/{eid}/leave-events`.
- **Tests (`tests/test_nz_holidays_act_entitlements.py`):** anniversary vesting, the 6-month sick qualification and carry cap, stable vs variable weeks, otherwise-working-day yes/no/undetermined, a partial shift and midnight crossing, alternative holiday creation, family-violence rows invisible to a normal operator and absent from exports, the ledger written once per payslip.

---

## P6: Holidays Act II (leave pay, final pay) and non-standard payments

> **Full build plan: `docs/new_zealand/P6_LEAVE_PAY_FINAL_PAY_NONSTANDARD_PLAN.md`** (4 tables + 3 columns, OWP/AWE/RDP/ADP, extra-pay method, final pay, corrections, ELA isolation, test names). Where it differs from the summary below, follow that document.

**Goal.** Pay the right amount for leave (NZ-017), close an employment correctly (NZ-021), and support lump sums, holiday pay in advance, out-of-cycle payments and corrections (NZ-006).

### Migration `<hex12>_nz_leave_pay.py` (on the P5 revision)

**`payroll_nz_leave_pay_calculations`** (append-only)

| column | type | notes |
|---|---|---|
| employee_id, employment_id, leave_event_id | FKs | |
| run_id, payslip_item_id | FKs SET NULL | |
| leave_type | String(20) | |
| method_pair | String(10) | `OWP_AWE` (annual) / `RDP_ADP` (sick, bereavement, family violence, public holiday) / `PAYG` |
| candidate_a_name, candidate_a_amount | String(4) / Numeric(14,2) | OWP or RDP |
| candidate_b_name, candidate_b_amount | String(4) / Numeric(14,2) | AWE or ADP |
| inputs | JSON NOT NULL | lookback window, gross earnings rows used, divisor, days worked |
| chosen | String(4) NOT NULL | |
| chosen_amount | Numeric(14,2) NOT NULL | |
| statutory_reason | String(200) NOT NULL | why the chosen value won |
| pack_hash | String(64) NOT NULL | |

**`payroll_nz_cash_up_requests`**

| column | type | notes |
|---|---|---|
| employee_id, employment_id, entitlement_id | FKs | |
| requested_on | Date NOT NULL | |
| written_request_ref | String(300) NOT NULL | evidence |
| weeks | Numeric(6,4) NOT NULL | ≤ `nz_hol_cashup_max_weeks`, checked at runtime |
| status | String(12) | `REQUESTED` / `APPROVED` / `PAID` / `REJECTED` |

**`payroll_nz_final_pay_cases`**

| column | type | notes |
|---|---|---|
| employee_id, employment_id | FKs | |
| termination_date | Date NOT NULL | |
| termination_reason | String(30) NOT NULL | |
| run_id | FK | |
| outstanding | JSON | each entitlement and its pay calculation |
| status | String(12) | `OPEN` / `CALCULATED` / `APPROVED` / `PAID` |

The employment can be closed only when the case is PAID.

**`payroll_nz_corrections`**

| column | type | notes |
|---|---|---|
| original_payslip_item_id | FK NOT NULL | |
| correction_payslip_item_id | FK | |
| reason | String(300) NOT NULL | |
| delta | JSON NOT NULL | |
| status | String(12) | `DRAFT` / `APPROVED` / `APPLIED` |

Corrections are blocked while `nz_correction_policy == PENDING_G1`.

### Code
- **`holidays_act.py` additions:**
  - `ordinary_weekly_pay(...)`, `average_weekly_earnings(ledger_rows, as_of)` (the 12 months before the end of the last pay period ÷ 52), `relevant_daily_pay(...)`, `average_daily_pay(ledger_rows, days_worked)`;
  - `annual_leave_pay(...)` = max(OWP, AWE) per week; `daily_leave_pay(...)` = RDP, or ADP where RDP cannot be determined;
  - each returns both candidates plus the reason;
  - missing inputs block `NZ_LEAVE_EVIDENCE_MISSING`;
  - `payg_holiday_pay(gross, employment, pack)` is gated on `payg_eligible` and reported as a separate payment line;
  - `cash_up(...)`;
  - `public_holiday_worked_pay(...)` uses `nz_hol_ph_worked_multiplier` and creates an alternative holiday.
- **`paye.py` additions:** `lump_sum_paye(...)` (`NZ_LUMP_SUM`, blocks while empty) and `holiday_pay_advance_paye(...)` (`NZ_HOLIDAY_ADVANCE`).
- **`new_zealand.py`:** accept `nz_payment_kind` in {LUMP_SUM, OUT_OF_CYCLE, HOLIDAY_PAY_ADVANCE, FINAL, CORRECTION}. LUMP_SUM_PATH components route to `lump_sum_paye`. ACC, student loan and KiwiSaver treatment of lump sums is read from the earning classes.
- **`payroll/nz_lifecycle.py`** (new):
  - `open_final_pay_case`, `calculate_final_pay` (resolves every outstanding entitlement into leave-pay calculations; never zeroes a balance), `approve_final_pay` (four-eyes);
  - `create_nz_correction(original_item, delta, reason)` creates a compensating delta payslip and never edits the original (NZ-006). P8 adds the amended filing link.
- **ELA 2028:** `tests/test_nz_ela_isolation.py` proves no code path can select `NZ-ELA-2028` before 2028-08-06 (pack resolution, activation, `calc_inputs`).
- **Tests:** `test_nz_leave_pay.py` (OWP vs AWE winner both ways, RDP vs ADP, PAYG eligible/ineligible, cash-up limit, missing evidence blocks), `test_nz_nonstandard_payments.py`, `test_nz_final_pay.py`.

---

## P7: Frontend (spec §12)

**Goal.** Operator screens, mirroring the Japan screens one for one. All paths are under `frontend/src/`.

| NZ file (new) | Japan file to mirror | Content |
|---|---|---|
| `pages/JurisdictionCompliance/NZCompliancePage.jsx` (+ export in `index.js`, slug `NZ: "new-zealand"`) | `JPCompliancePage.jsx` | Super Admin page |
| `config/jurisdictions/newZealandComplianceConfig.jsx` | `japanComplianceConfig.jsx` | tabs: Overview, Pack rows, Tax codes, Earning classes, Authority tables (empty + gate), ELA 2028 (future pack, cannot activate), Readiness |
| `components/jurisdiction/new_zealand/{NZOverviewDashboard,NZPackRowsTab,NZReadinessTab,NZRecordSection}.jsx`, `nzComponentConfig.js`, `nzFormat.js`, `nzShared.jsx` | `components/jurisdiction/japan/*` | |
| `App.jsx` routes `/super-admin/compliance/new-zealand` and `/new-zealand/:state` | JP routes | |
| `service/superAdminService.js` `getNzStatutorySummary` | `getJpStatutorySummary` | calls the generic statutory-summary endpoint with `NZ` |
| `modules/payroll/Compliances/NZComplianceCentreTab.jsx` (mounted in `CompliancePage.jsx`) | `JPComplianceCentreTab.jsx` | employer profile versions + approve; P8 adds filings and remittances |
| `modules/payroll/Payroll_Employees/NewZealandStatutoryProfilePanel.jsx` (opened from `EmployeeDetailPanel.jsx`) | `JapanStatutoryProfilePanel.jsx` | tax profile, KiwiSaver, work pattern, authority notices, opening accumulators, employments |
| `modules/payroll/Payroll_Employees/NZIrdNumberField.jsx` | `JPMyNumberField.jsx` | masked; reveal flow; the revealed value is wiped after 60 s and on unmount; never written to storage, the URL or the console |
| `modules/payroll/Payroll_Employees/NZLeaveAuditPanel.jsx` | (new) | entitlements, anniversaries, work patterns, OWP/AWE/RDP/ADP traces, public-holiday decisions; family-violence rows only with the restricted permission |
| `modules/payroll/PayRollRuns/NZPayslipBreakdown.jsx`, `NZRunPreflightPanel.jsx` (mounted in `RunDetailPanel.jsx`) | `JPPayslipBreakdown.jsx`, `JPRunPreflightPanel.jsx` | read-only calculation drawer: bases, PAYE/ACC trace, KiwiSaver/ESCT, student loan, child support, exceptions; **no manual override of statutory amounts** |
| `service/payrollService.js` (`const NZ = "/api/payroll/new-zealand"`) | JP clients (~2885–2985) | one client per route |
| `components/jurisdiction/CountryFlag.jsx`, `utils/jurisdictionLabels.js` | JP entries | |
| `scripts/nz-compliance-ui-validation.mjs`, appended to `npm test` in `package.json` | `scripts/jp-compliance-ui-validation.mjs` | see the checks below |

The UI validation script must check:
- every NZ client path matches a route parsed from `backend/app/modules/payroll/nz_org_router.py`;
- there are no 8–9 digit IRD-like literals;
- the IRD number never goes to localStorage, sessionStorage, the URL or the console;
- reveal wipe timers exist;
- every NZ file is reachable from a mount;
- there is no JP or ZA field leakage.

Use relative paths only (Japan's first draft broke on an absolute `C:/` path) and ESM `import`, not `require`.

**Do not add NZ to `utils/registrationRegions.js` `REGISTRATION_COUNTRIES`** while it is dormant.

Backend: `tests/test_nz_phase7.py` covers `/employees/{eid}/summary` and `nzCalculationSnapshot` serialisation (no `frozenContext`).

---

## P8: Payday filing, remittance, reconciliation, run exceptions, corrections, journal (§9, gate G3)

### Migration `<hex12>_nz_filings.py` (on the P6 revision)

**`payroll_nz_filings`** (TENANT RLS: employer level)

| column | type | notes |
|---|---|---|
| run_id | FK payroll_runs | |
| pay_date | Date NOT NULL | |
| filing_type | String(24) | `EMPLOYMENT_INFORMATION` / `EMPLOYEE_DETAILS` / `AMENDMENT` |
| payload_version | SmallInteger NOT NULL | |
| payload | JSON NOT NULL | generated only from PAID payroll; no free-form amount edits |
| payload_hash | String(64) NOT NULL | |
| channel | String(20) | `GATEWAY` / `MYIR_FILE` / `PAPER` |
| due_on | Date NOT NULL | payday + `nz_payday_filing_working_days` NZ working days (public holidays from the pack) |
| status | String(12) | `DRAFT` / `APPROVED` / `SUBMITTED` / `ACCEPTED` / `REJECTED` / `AMENDED` |
| authority_reference | String(100) | |
| authority_errors | JSON | structured error codes |
| amends_id | FK self | correction chain |
| submitted_by_id, approved_by_id | FK users | |

Unique `(organization_id, legal_entity_id, pay_date, filing_type, payload_version)`, which makes filings idempotent (NZ-018).

**`payroll_nz_obligations`** (liability; TENANT)

| column | type | notes |
|---|---|---|
| run_id | FK | |
| period_start, period_end | Date | the remittance period: monthly, or 1–15 / 16–end |
| obligation | String(20) | `PAYE` / `ACC_LEVY` / `KS_EMPLOYEE` / `KS_EMPLOYER_NET` / `ESCT` / `STUDENT_LOAN` / `CHILD_SUPPORT` |
| amount | Numeric(14,2) | |
| destination | String(16) | `INLAND_REVENUE` / `COMPLYING_FUND` |
| due_on | Date NOT NULL | 20th, 5th or 15 Jan rules from content |
| status | String(12) | `OPEN` / `PART_PAID` / `PAID` |

**`payroll_nz_settlements`** (TENANT)

| column | type | notes |
|---|---|---|
| obligation_id | FK | |
| paid_on | Date | |
| amount | Numeric(14,2) | |
| payment_reference | String(100) | |
| matched_by_id | FK users | |
| status | String(12) | `RECORDED` / `MATCHED` / `UNMATCHED` |

Filing acceptance **never** sets an obligation to PAID (NZ-019).

**`payroll_nz_run_exceptions`** (TENANT)

| column | type | notes |
|---|---|---|
| run_id | FK | |
| payslip_item_id | FK | |
| code | String(40) | `NZ_MIN_WAGE_FAIL`, `NZ_CS_SHORTFALL`, … |
| detail | JSON | |
| payload_fingerprint | String(64) | |
| requested_by_id, approved_by_id | FK users | four-eyes |
| status | String(12) | `OPEN` / `APPROVED` / `REJECTED` |

A minimum-wage FAIL is never approvable. Only documented exceptions are.

Also add the column **`payroll_nz_employer_profiles.nz_journal_accounts`** (JSON, literal `op.add_column`).

### Code
- **`payroll/nz_filing.py`:**
  - `build_filing_snapshot(db, run)`, called at PAID from `before_run_transition`;
  - `nz_due_date(pay_date, working_days, holidays)`;
  - `approve_filing` (four-eyes) and `submit_filing`, which refuses with `NZ_EXPORT_SCHEMA_NOT_CERTIFIED` while `NZ_EXPORT_SCHEMAS == {}`;
  - `record_authority_response(filing, accepted|rejected, ref, errors)`;
  - `amend_filing(original, reason)`;
  - `remittance_periods(employer_profile, pay_date)` (connected-business aggregation from the evidenced group).
- **`payroll/nz_journal.py`:** `build_journal(db, run)`; it must balance and blocks when the account map is incomplete. Mirror `japan_journal.py`.
- **`nz_lifecycle.py`:** run exceptions (bound to the payload fingerprint), and corrections producing an `AMENDMENT` filing.
- **Routes:**
  - `GET /filings`, `GET /filings/{id}` (JSON preview), `POST /filings/{id}/approve`, `/submit` (refused), `/response`, `/amend`;
  - `GET /obligations`, `POST /obligations/{id}/settlements`, `POST /settlements/{id}/match`;
  - `GET/POST /runs/{rid}/exceptions`, `POST /run-exceptions/{id}/approve`;
  - `GET /runs/{rid}/journal`;
  - `POST /payslips/{id}/corrections`.
- **Frontend:** `NZFilingsPanel.jsx`, `NZRemittancePanel.jsx`, `NZRunExceptionsPanel.jsx`; extend the nz-ui check.
- **Tests (`test_nz_phase8.py`):**
  - the 2-working-day deadline across a weekend and a public holiday;
  - a retry produces no duplicate;
  - a rejected filing leaves payroll unchanged;
  - the amendment chain;
  - < $500k is monthly and ≥ $500k is twice-monthly, including the 16–31 Dec → 15 Jan case;
  - connected-business aggregation;
  - acceptance ≠ paid;
  - the journal balances.

---

## P9: Release gates, parallel cycles, privacy proof, key rotation (§13–§15)

### Migration `<hex12>_nz_parallel_cycles.py`
- **`payroll_nz_parallel_imports`** (TENANT): `cycle_month` Date, `pay_date` Date, `source_name` String(100), `file_hash` String(64), `row_count` Integer, `status` String(12).
- **`payroll_nz_parallel_differences`** (WORKER): `import_id` FK, `employee_id` FK, `obligation` String(24), `incumbent_amount` / `zoiko_amount` / `difference` Numeric(14,2), `explanation` String(300), `explained_by_id`, `accepted_by_id` (a different person), `status` String(12).

### Code
- **`payroll/nz_readiness.py`.** Mirror `japan_readiness.py`. `GATES` G1–G7 with owners from spec §15. `nz_code_checks(db)`:

  | Gate | Check |
  |---|---|
  | G1 | No pending row; every `NZ_EMPTY_TABLES` G1 table is filled; IRD examples present and the golden test passes |
  | G2 | Public holidays and Holidays Act fixtures present |
  | G3 | `NZ_EXPORT_SCHEMAS` non-empty |
  | G4 | `NZ_IRD_KEYRING` and the fingerprint key configured; privacy tests marker |
  | G5 | ≥ 2 accepted parallel cycles in distinct months for ≥ 2 employers (AC-NZ-03) |
  | G6 | Runbooks present |
  | G7 | Commercial sign-offs |

  A gate passes only when its checks pass **and** a `SourceArtifact` with `form_number="NZ-GATE-Gn"` is reviewed by someone other than the uploader. `nz_unmet_requirements(db)` replaces the P4 stub.
- **`payroll/nz_parallel.py`:** CSV import compared at zero tolerance. Refuse any file with an IRD-like column or value (8–9 digits that pass `nz_ird_number_valid`). Explain-then-accept by a different person.
- **`scripts/rotate_nz_ird_keys.py`:** dry run by default; `--apply`; `--confirm-remote` required for non-local. It uses `nz_ird_number.reencrypt` and writes `ROTATED` events. **Never run it against any DB (R2)**; it is tested with SQLite only.
- **Docs:** `docs/new_zealand/release-gates/README.md`, `G1.md` … `G7.md` (owner, evidence, go/no-go rule from spec §15) and `docs/new_zealand/RUNBOOK_GO_LIVE.md`. The runbook covers:
  - authority outage and filing retry;
  - payment recovery;
  - corrections;
  - the breach runbook with the OPC 72-hour target;
  - canary and rollback (NZ-026): rollback restores the prior signed pack and never rewrites committed payroll.
- **Frontend:** `NZReadinessTab.jsx`, `NZParallelCyclesSection.jsx`.
- **Tests:**
  - `tests/privacy/test_nz_ird_redaction.py`: no IRD digits, bank account, notice content or family-violence detail in logs, events, exports or API responses (NZ-025);
  - cross-tenant and cross-legal-employer denial;
  - `test_nz_phase9.py`: gates, parallel cycles, rotation dry run vs apply.

---

## P10: Integration and PR

1. `git fetch origin && git merge origin/main` into `venu`.
2. If main gained migrations, re-parent the **first** NZ migration onto main's head, keep a single head, and update the manifest and every head pin (R9).
3. Run the full backend suite, `npm run build`, `npm run check:undefined` and `npm test`.
4. **Ask Venu before pushing.** The PR is `venu → main` only. End the PR body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)` if Claude wrote it.

---

## Acceptance mapping

| Spec item | Delivered by |
|---|---|
| AC-NZ-01 | IRD examples: P3 golden harness + G1 data |
| AC-NZ-02 | Specialist sign-off: G1 evidence artifact |
| AC-NZ-03 | Two parallel cycles: P9 |
| AC-NZ-04 | Holidays Act edge cases: P5/P6 |
| AC-NZ-05 | Payday filing certification: P8 + G3 |
| AC-NZ-06 | Security/privacy: P9 |
| AC-NZ-07 | Performance / outage recovery: P8 idempotency + P9 runbook |
| AC-NZ-08 | ELA 2028 isolation: P1 + P6 |

## External dependencies (code cannot close these; NZ stays dormant until they arrive)
- The signed IRD 2026-27 payroll calculations and business-rules specification, plus its official examples.
- An NZ payroll/tax specialist's sign-off.
- IR gateway onboarding and credentials.
- Public-holiday and regional anniversary dates.
- Employer ACC classifications.
- Two design employers for the parallel cycles.
- Commercial sign-off.
