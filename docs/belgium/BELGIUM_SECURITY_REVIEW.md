# Belgium security and hardening review (Block D2)

Scope: the whole Belgium diff `1af3d44..HEAD` (pre-Belgium baseline 1af3d44, 30+ commits, 122 files) —
every Belgium file and every hunk in a shared file. Reviewed 2026-11-13 on branch nikhil.

## Summary of findings and fixes

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| F1 | `GET /api/payroll/belgium/filing-calendar` did not pin the caller's organisation. It returns jurisdiction content (the authority calendar), not tenant data, but with onboarding enabled the router guard admits a user without an organisation, which every other Belgian route refuses. | Low | `_org_id(current_user)` added (be_org_router); a route test now asserts every Belgian route calls it. |
| F2 | The Phase 2 PostgreSQL migration round trip would have failed on its first PostgreSQL run (it asserted that no `payroll_be_*` policy remains after its own downgrade; Blocks B / C keep theirs), and no CI job collected it. | Medium (unproven RLS on PostgreSQL) | D1: shared `pg_round_trip` helper per revision (own tables only); round trips for 2943a0490b5b and 8a1f5ef9fa5d; CI privacy-isolation job runs the three Belgium migration files on PostgreSQL. |
| F3 | Stale comments in two Belgian lines of shared files (`engine/standard.py` said the engine "always raises BE_ENGINE_NOT_BUILT"; `service.py` said the console "arrives in Phase 3"). | Info | Comments corrected (comment-only change inside the BE-guarded lines). |
| F4 | C2 callgraph collisions (generic function names; `statutory_summary`) re-classified 13 existing NZ / PL / MX routes; caught by the standing registry diff before commit. | Medium (would have mis-stated other countries' data access) | Fixed in C2 (be_-unique names; the hook maps to `be_statutory_summary`). Recorded here for completeness. |
| F5 | The Super Admin readiness route first read worker tables (G2 per-employee detail) and was classified **worker**, which a platform role may not use. | Medium (privacy) | Fixed in C2: counts and organisation ids only; reviewed `aggregate` override in route_overrides.py. |

No finding in shared code required a non-additive change (stop condition (a) not triggered).

## 1. NISS / BIS / ONSS number

- Storage: only `payroll_be_identifier_vault` (AES-GCM ciphertext bound to the owner, key version, keyed
  HMAC fingerprint for duplicates). No plaintext column; `BEEmployeeValidation` refuses any NISS-like
  compliance field and never echoes it; `be_identifiers.normalise` errors name the type, never the value.
- Exposure points checked (all clean): log records (no logger in Belgian code; every record emitted during a
  full synthetic month captured at DEBUG), URLs and query strings (identifier routes carry a vault id, the
  value only in a POST body or the single-use reveal response), exception texts, the audit table and the
  identifier access events, payslip snapshots incl. the frozen context and `be_result` (masked marker only,
  no digit), the serialized payslip, every filing (payload, readable rendition, idempotency key, response),
  obligation keys, parallel imports and differences, and the payroll-register CSV export.
- The single deliberate exception: `POST /identifiers/{vault_id}/reveal` returns the value once to the
  requester after a second person's approval (BE-040; audited access events).
- Proof: `tests/test_belgium_security_review.py` (a synthetic month with a NISS and an employer ONSS number
  on file; scans every output above for both values and the renditions for any eleven-digit run).

## 2. Routes

Generated from the committed route registry and the live app (role dependency read from the FastAPI
dependency tree). Every `/api/payroll/belgium` route:
- is dormancy-gated (`require_be_tenant`: 404 unless onboarding is on or the org is a canary, and the
  organisation's payroll jurisdiction is Belgium);
- acts only on the caller's own organisation (`_org_id(current_user)`; no route takes an organisation id;
  every child id and every `legalEntityId` is checked against that organisation in the service);
- writes need an org admin; the only POST open to a payroll operator is the read-only classification resolver;
- "Four-eyes = yes": the service refuses when the actor is the maker (shared `require_four_eyes` or the
  Belgian equivalent) and a DB CHECK refuses approver = creator; "maker step": the write creates a DRAFT /
  OPEN record whose approval is a separate four-eyes route, or records an external fact (bank result,
  authority response, payment) idempotently by reference.
- Super Admin routes (`/api/super-admin/compliance/belgium/...`) are platform routes; none returns worker
  data (readiness = aggregate, F5).

Proof: `tests/test_belgium_security_review.py::test_every_belgium_route_is_dormancy_gated_tenant_scoped_and_role_checked`
and `tests/privacy/test_route_registry.py` (no worker route reachable by super admin).

### Route table (98 routes, generated)

| Method | Path | Role dependency | Dormancy gate | Own org only | Four-eyes | Data class | Registry principals |
|---|---|---|---|---|---|---|---|
| POST | `/api/payroll/belgium/absence-episodes/{row_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/absence-episodes/{row_id}/cancel` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/belcotax/{income_year}/build` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/classification/resolve` | payroll_operator | yes | yes | read-only | worker | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/classifications/{row_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| GET | `/api/payroll/belgium/component-mappings` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/component-mappings` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/component-mappings/{row_id}/approve` | org_admin | yes | yes | yes | tenant_config | org_admin |
| POST | `/api/payroll/belgium/declarations/{row_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/declarations/{row_id}/withdraw` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/dimona/events` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/dmfa/quarters/{quarter}/build` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/absence-episodes` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/absence-episodes` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/classifications` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/classifications` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/declarations` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/declarations` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/holiday-certificates` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/holiday-certificates` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/identifiers` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/identifiers` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/summary` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/work-schedules` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/work-schedules` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employees/{employee_id}/worker-profiles` | payroll_operator | yes | yes | - | worker | employee,org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employees/{employee_id}/worker-profiles` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/employer-registrations` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/employer-registrations` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/employer-registrations/{row_id}/approve` | org_admin | yes | yes | yes | tenant_config | org_admin |
| POST | `/api/payroll/belgium/employer-registrations/{row_id}/onss-number` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/employer-registrations/{row_id}/verify` | org_admin | yes | yes | yes | tenant_config | org_admin |
| GET | `/api/payroll/belgium/establishment-units` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/establishment-units` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/establishment-units/{row_id}/approve` | org_admin | yes | yes | yes | tenant_config | org_admin |
| GET | `/api/payroll/belgium/filing-calendar` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/filing-exceptions` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/filings` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/filings/{filing_id}` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/filings/{filing_id}/approve` | org_admin | yes | yes | yes | tenant_config | org_admin |
| POST | `/api/payroll/belgium/filings/{filing_id}/cancel` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| GET | `/api/payroll/belgium/filings/{filing_id}/employee-copy` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/filings/{filing_id}/response` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/filings/{filing_id}/submission` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/filings/{filing_id}/transmit` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/filings/{filing_id}/validate` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/holiday-certificates/{row_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/identifiers/{vault_id}/delete` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/identifiers/{vault_id}/reveal` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/identifiers/{vault_id}/reveal-approve` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/identifiers/{vault_id}/reveal-request` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/joint-committees` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/obligations` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/obligations/onss-advances` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/obligations/{obligation_id}/payments` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| POST | `/api/payroll/belgium/obligations/{obligation_id}/reconcile` | org_admin | yes | yes | yes | tenant_config | org_admin |
| GET | `/api/payroll/belgium/options` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/parallel-differences/{difference_id}/accept` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/parallel-differences/{difference_id}/explain` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/parallel-imports` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/parallel-imports` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/parallel-imports/{import_id}` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/parallel-imports/{import_id}/accept` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/parallel-imports/{import_id}/withdraw` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| GET | `/api/payroll/belgium/payment-batches` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/payment-batches/{batch_id}` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/payment-batches/{batch_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/payment-batches/{batch_id}/bank-result` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/payment-batches/{batch_id}/file` | org_admin | yes | yes | - | worker | org_admin |
| POST | `/api/payroll/belgium/payment-batches/{batch_id}/reconcile` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/payment-batches/{batch_id}/returns` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/payment-batches/{batch_id}/submit` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/payslips/{payslip_item_id}/corrections` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/runs/{run_id}/exceptions/acknowledge` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/runs/{run_id}/payment-batches` | org_admin | yes | yes | maker step | worker | org_admin |
| GET | `/api/payroll/belgium/runs/{run_id}/payment-preview` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/runs/{run_id}/preflight` | payroll_operator | yes | yes | - | worker | org_admin,payroll_admin |
| GET | `/api/payroll/belgium/substitute-days` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/substitute-days` | org_admin | yes | yes | maker step | tenant_config | org_admin |
| GET | `/api/payroll/belgium/variances` | payroll_operator | yes | yes | - | tenant_config | org_admin,payroll_admin |
| POST | `/api/payroll/belgium/variances/{variance_id}/resolve` | org_admin | yes | yes | yes | tenant_config | org_admin |
| POST | `/api/payroll/belgium/withholding-obligations/{period}/build` | org_admin | yes | yes | maker step | worker | org_admin |
| POST | `/api/payroll/belgium/work-schedules/{row_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| POST | `/api/payroll/belgium/worker-profiles/{row_id}/approve` | org_admin | yes | yes | yes | worker | org_admin |
| PUT | `/api/super-admin/compliance/belgium/configuration/rows/{kind}/{row_id}` | super_admin | n/a | n/a | maker step | platform | super_admin |
| DELETE | `/api/super-admin/compliance/belgium/configuration/slab-rows/{row_id}` | super_admin | n/a | n/a | maker step | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/decisions` | super_admin | n/a | n/a | - | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/joint-committees` | super_admin | n/a | n/a | - | platform | super_admin |
| PUT | `/api/super-admin/compliance/belgium/joint-committees/{agreement_id}/wage-modules` | super_admin | n/a | n/a | maker step | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/packs` | super_admin | n/a | n/a | - | platform | super_admin |
| POST | `/api/super-admin/compliance/belgium/packs/{pack_row_id}/authority-examples` | super_admin | n/a | n/a | maker step | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/packs/{pack_row_id}/configuration` | super_admin | n/a | n/a | - | platform | super_admin |
| POST | `/api/super-admin/compliance/belgium/packs/{pack_row_id}/golden-certification` | super_admin | n/a | n/a | maker step | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/packs/{pack_row_id}/golden-check` | super_admin | n/a | n/a | - | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/packs/{pack_row_id}/signing-status` | super_admin | n/a | n/a | - | platform | super_admin |
| POST | `/api/super-admin/compliance/belgium/packs/{pack_row_id}/slab-rows/{key}` | super_admin | n/a | n/a | maker step | platform | super_admin |
| GET | `/api/super-admin/compliance/belgium/readiness` | super_admin | n/a | n/a | - | aggregate | super_admin |
| POST | `/api/super-admin/compliance/belgium/seed-draft` | super_admin | n/a | n/a | maker step | platform | super_admin |

## 3. Shared-file hunks (1af3d44..HEAD)

Every hunk below is additive and keyed to Belgium (`"BE"` in a per-country opt-in tuple / dict, or a branch
guarded by `country == "BE"`), or a test re-pin under the standing rule. None changes another country's
behaviour.

| File | Hunks | Nature |
|------|-------|--------|
| backend/app/config.py | +16 | BE_TENANT_ONBOARDING_ENABLED, BE_CANARY_ORG_IDS, BE_IDENTIFIER_KEYRING, BE_IDENTIFIER_FINGERPRINT_KEY (defaults off / empty) |
| backend/app/core/jurisdiction.py | +31 | "BE" tax-identifier schema; Belgian name aliases (bare "be" deliberately not an alias: Bern canton) |
| backend/app/core/authz/route_overrides.py | +2 | aggregate override for the Belgian readiness route (with note) |
| backend/app/core/authz/route_registry.json, docs/privacy/route_policy_inventory.csv | additive | generated entries for the Belgian routes only (registry diff: no existing route changed) |
| backend/app/modules/payroll/bank_routing.py | +7 / 1 modified | "BE" appended to ROUTING_COUNTRIES; BE IBAN field, labels |
| backend/app/modules/payroll/employee_validation.py | +43 | BEEmployeeValidation (IBAN only, NISS refused); `code == "BE"` dormancy gate |
| backend/app/modules/payroll/engine/base.py | +38 | be_* PayrollContext fields (None for every other country) |
| backend/app/modules/payroll/engine/resolver.py | +15 | BE simple-mode refusal; `belgium_inputs` passthrough |
| backend/app/modules/payroll/engine/standard.py | +10 | `_COUNTRY_CALC["BE"]`; `be_employee_total` (0 elsewhere); `be_result` |
| backend/app/modules/payroll/engine/tax_resolver.py | 1 modified, +6 | "BE" in the registry-required tuple; entering-Belgium refusal |
| backend/app/modules/payroll/jurisdiction_hooks.py | +2 | "BE" -> belgium_service |
| backend/app/modules/payroll/router.py | +3 | include be_org_router |
| backend/app/modules/payroll/service.py | ~92 | "BE" in canonical-only / gated / four-eyes opt-in tuples; BE generic-editor refusal; BE pack assignment refusal; calc_inputs + freeze / snapshot for country == "BE"; serializer key; entering-Belgium refusals; BE agreement-code refusal |
| backend/app/modules/payroll/models.py | +813 | Belgian tables / columns only (payslip_items.be_calculation_snapshot, payroll_runs.be_approval_fingerprint nullable) |
| backend/app/modules/super_admin/router.py | +139 | /compliance/belgium/* routes only |
| backend/alembic/MIGRATIONS_MANIFEST.txt | +3 | the three Belgian revisions |
| .github/workflows/backend-deploy*.yml | +6 each | last step of the PostgreSQL job: Belgium migration round trips |
| frontend: App.jsx, CountryFlag.jsx, CompliancePage.jsx, RunDetailPanel.jsx, PayslipStub.jsx, EmployeeDetailPanel.jsx, bankFieldsFor.js, countryFieldSpecs.js, JurisdictionCompliance/index.js, payrollService.js, superAdminService.js, currency.js, jurisdictionLabels.js, jurisdictionTax.js, package.json | additive | BE tab / routes / labels / service functions behind `=== "BE"` checks; package.json test script gains the two BE validation scripts |
| backend/tests (non-BE) | re-pins | exact-list pins only (Alembic head / count, drift table sets) in separate "test: re-pin" commits; no behaviour change |

Flagged: none.

## 4. Statutory values, code execution, grammar

- Numeric-literal guard (`tests/test_belgium_content.py::test_no_statutory_numeric_literal_in_belgian_code`)
  re-run over every belgium*.py, be_*.py and engine/jurisdictions/belgium/* file: passes; every allowed
  number is listed per file with its structural reason (widths, calendar month arithmetic, identifier SHAPES
  used to refuse imports). No statutory rate, threshold, date or schema version is in code; all come from
  signed pack rows.
- No `eval`, `exec` or `compile` (other than `re.compile`) anywhere in Belgian code
  (`tests/test_belgium_formula.py::test_the_module_never_calls_eval_or_exec`).
- Formula grammar: AST whitelist (numbers, signed names, + - * /, comparisons, min / max, conditional) in
  Decimal; refuses imports, attributes, dunder access, other calls, lambdas, subscripts, literals of other
  types, `**` `//` `%` bit operators, comprehensions, walrus, f-strings, unknown names, empty / oversized /
  deeply nested input and division by zero (`tests/test_belgium_formula.py`, 30+ cases).

## 5. Fail-closed audit — every place a Belgian result can be produced

| # | Path | What must hold before a result exists | Proof |
|---|------|----------------------------------------|-------|
| 1 | `engine/countries/belgium.calculate` (Standard and Enterprise strategies dispatch BE here; never the generic calculator) | pay date; every pack row read is in force, signed (no "[PENDING G1]"), not NOT_SUPPORTED, else BE_CONTENT_PENDING / BE_ROW_MISSING / BE_FEATURE_BLOCKED; the applicability resolver (`applicability.require`) has no blocker (employer, worker, Joint Committee, contract, schedule, special regime, G-27 scope) | test_belgium_engine.py, test_belgium_applicability.py, test_belgium_pack.py |
| 2 | Simple calculation mode | refused for BE (BE_SIMPLE_MODE_UNSUPPORTED) | test_belgium_scaffold.py |
| 3 | Inputs (`calc_inputs`) | only APPROVED / ACTIVE Belgian records in force on the pay date; the pack is the Active canonical pack only (canonical-only tuple); no Active pack -> blocked | test_belgium_setup.py, test_belgium_run_lifecycle.py |
| 4 | Pack activation (what makes content "signed") | every catalogue row signed, sourced, not empty; slab rows signed; earning classes signed; authority examples replay exactly; latest BE golden certification PASS; editors / approver never activate | test_belgium_super_admin.py, test_belgium_slab_rows.py, test_belgium_parallel_golden_readiness.py |
| 5 | Run preview (`preview_payroll_run`) | same engine and inputs as 1 / 3; nothing is committed | test_belgium_run_lifecycle.py |
| 6 | Run commit (Review -> APPROVED) | preflight without BLOCK: pack in force, no blocked payslip, resolver pass per employee, engine exceptions acknowledged (audited), **accepted Dimona IN per employment line**; approver != preparer and != input creators (G-18); fingerprint stored; ledger posted | test_belgium_run_lifecycle.py |
| 7 | AUTHORIZED / PAID | fingerprint unchanged since commit; authorizer != approver | test_belgium_run_lifecycle.py |
| 8 | Correction (`create_be_correction`) | replays the original's frozen, already-certified context with the declared input delta (reason + evidence); creates a new run that goes through 6 / 7 (the resolver and Dimona checks are skipped for a correction payslip by design: it re-states an already committed period) | test_belgium_run_lifecycle.py |
| 9 | Golden replay (`belgium_golden`) | synthetic worker, the pack's own rows, nothing written to an organisation | test_belgium_parallel_golden_readiness.py |
| 10 | Filings / obligations / parallel | built only from committed ledger entries and frozen snapshots; never recalculate | test_belgium_filing.py, test_belgium_parallel_golden_readiness.py |
| 11 | Service availability | PLANNED -> AVAILABLE refused while any gate G1-G7 is red | test_belgium_parallel_golden_readiness.py, test_belgium_scaffold.py |

Result: no path produces a Belgian payslip without signed content and a resolver pass, and no run can be
approved without an accepted Dimona IN for each employee's employment line.
