# Belgium Block A — progress log

Resume point after any restart: the last entry below. Branch `nikhil`, local commits only (never pushed).
Merge / push is gated on the PostgreSQL RLS test passing in CI.

## Standing environment facts

- Python: 3.11 (`C:/Users/Nikhi/AppData/Local/Programs/Python/Python311/python.exe`). The 3.14 interpreter
  cannot build the pinned numpy 2.1.3 (no wheel, no compiler), so `backend/.venv-be` was not built.
  **CI must run 3.12.**
- Every pytest run: `PAYROLL_DATABASE_URL=sqlite:///<scratchpad>/testdb_<timestamp>/zp_test.db` (fresh file per
  run), `ZP_TEST_POSTGRES_URL` unset. `backend/.env` is never edited; the env var overrides it. Only
  `PAYROLL_DATABASE_URL` is read by `app/config.py` and the conftest guard.
- PostgreSQL gate: Docker Desktop cannot start on this machine (no WSL distro), so the Postgres-gated RLS tests
  are SKIPPED locally. Open gate before merge.
- Pre-existing, not investigated: Germany ordering, test_engine_jurisdiction_db_integration ordering, HK CSV,
  route registry health routes from the uncommitted `main.py`, Mexico timezone flake.
- Untouched in every commit: `backend/.env.example`, `backend/app/main.py`, `frontend/vite.config.js`, the three
  Singapore docs.

## Merge gates (CI; they gate push / merge, not Block B)

- Frontend production build (`npm run build`) — not verifiable on this machine (out of memory at ~1.3 GB free).
- PostgreSQL RLS tests (Postgres-gated; Docker cannot start locally).
- Python 3.12 test run (only 3.11 locally).

## Standing rules added after Block A (2026-11-12)

- After every sub-step: rebuild the route registry in-test and diff it against the committed one. An
  unintended change to an existing route's classification, permitted roles or data categories is a STOP
  condition (the A3 `evaluate` incident).

## A1 — identifiers and statutory setup

- Commit: 02f4891 `feat(belgium): block A1 identifiers and statutory setup`.
- Added: `be_identifiers.py` (AES-GCM vault helpers, owner AAD, keyring, HMAC fingerprint, no fallback key,
  format-only checks per G-16), `be_org_router.py` (`/api/payroll/belgium`, 28 routes, dormant + Belgium-only
  guard), service functions in `belgium_service.py` (versioned records with four-eyes, declarations, vault,
  reveal, employee summary), `SCHEDULE_REGIMES` vocabulary, `BE_IDENTIFIER_KEYRING` /
  `BE_IDENTIFIER_FINGERPRINT_KEY` settings (empty), router include, route registry + inventory regenerated
  (+28 BE routes; nothing removed or changed; health routes stripped).
- Tests: `test_belgium_identifiers.py` (25), `test_belgium_setup.py` (22); guard allow-list extended for
  `be_identifiers.py` and the new `belgium_service.py` patterns.
- Run: tests/test_belgium_*.py + tests/privacy/test_route_registry.py + tests/test_poland_service.py →
  294 passed, 1 skipped (PG), 4 failed before the guard fix: 1 guard (fixed, content now 23/23) + 3 route
  registry failures that are the pre-existing health routes only.
- Open items: G-16 (NISS/BIS check digit, ONSS number format) still unverified — format-only checks.

## A2 — applicability resolver

- Commit: 720d74b `feat(belgium): block A2 applicability resolver`.
- Added: `engine/jurisdictions/belgium/applicability.py` (pure; collects every blocking reason; `require()` raises
  the first for the engine), A2 block / exception codes in `errors.py`, `belgium_service.resolve_be_classification`
  (read-only: loads records + the active BE pack via `resolve_tax_configuration`, no pack -> BE_PACK_MISSING),
  `POST /api/payroll/belgium/classification/resolve` (route registry +1 entry, health routes stripped).
- A1 follow-up in this commit: `BEEmployeeValidation._VAULT_ONLY` also refuses `bis` / `bis_number` keys
  (Belgium-only class; additive).
- Design: SUPERSEDED versions count as in force inside their own truncated window (past pay dates replay);
  DRAFT never counts. Mid-period classification change blocks (pro-rating not certified). Missing agreement link
  and missing function class / seniority are exceptions, not blocks (§2 calls them compliance exceptions).
- Tests: `test_belgium_applicability.py` 49 passed.
- Run: tests/test_belgium_*.py + test_route_registry + test_poland_service + test_*employee_validation →
  404 passed, 1 skipped (PG), 3 failed = pre-existing health routes only (verified by path listing).
- Gaps added: G-22 (pay basis has no recorded source), G-23 (contract-type vocabulary unsigned),
  G-24 (special statuses blocked; exceptions vs blocks).

## A3 — core engine

- Commit: 800c464 `feat(belgium): block A3 core engine`.
- Added (pure, engine/jurisdictions/belgium/): `formula.py` (AST whitelist; Decimal literals from the source
  text; never eval / exec; interpreter BE-FORMULA-1), `declarations.py`, `bases.py` (closed components,
  signed earning-class matrix, REVIEW / missing class blocks, exceptional never in the regular base, source
  periods kept), `onss.py` (employee base; 108%-style uplift only for signed manual categories; social work
  bonus line; employer base / wage moderation / special / funds / pension as separate lines; manual holiday
  fund to obligation deltas only; BSSC exception only), `withholding.py` (Annex III stages 1-8; regular vs
  exceptional strategies; family layer from APPROVED declarations; fiscal work bonus line; trace has pack
  + interpreter versions). `pack.py`: be_evaluate / formula / band_for / band_value; formula text in used().
- Orchestrator `engine/countries/belgium.py` replaces BE_ENGINE_NOT_BUILT for the supported scope (one
  employment line, resident). Mapping: tds, be_employee_total, employer_esi, employer_pension, be_result.
- Integration (additive; BE-guarded): PayrollContext be_* fields; build_context_from_employee
  belgium_inputs; standard.py sums be_employee_total and maps be_result; service.py preview /
  _compute_payslip_values / add_payslip_item call the BE calc_inputs hook only when country == "BE",
  freeze + persist payslip_items.be_calculation_snapshot; _serialize_payslip beCalculationSnapshot (no
  frozenContext); ledger: generate / add item post RUN entries, regenerate / delete post linked CORRECTIONs.
- belgium_service: calc_inputs (pay-date records; vault ids / credentials stripped), be_ytd_snapshot,
  be_freeze_context / be_thaw_context / be_replay, be_payslip_snapshot / view, post_be_accumulators.
- Route registry: no new route. The ledger write adds `payroll_be_accumulator_entries` to scan_worker_tables
  of 11 payslip routes (generate / runs / items / recalculate / delete, MX / NZ run + correction routes);
  data_class, scope and principals unchanged (verified by diffing the fresh build). A first draft named a
  pack method `evaluate`, which the name-based callgraph linked to authz `policy.evaluate` and turned other
  countries' calculation-preview routes into worker routes; renamed to be_evaluate / evaluate_be_formula.
- Tests updated (BE only): test_belgium_scaffold (standard / enterprise now block with a BE_ reason, never
  BE_ENGINE_NOT_BUILT; calc_inputs needs a pay date), test_belgium_super_admin (still blocks). Guard
  allow-list extended for the new modules.
- New tests: test_belgium_formula.py 54, test_belgium_engine.py 34 (synthetic TEST ONLY packs; seams in the
  end-to-end tests: synthetic pack instead of the canonical resolver, pay basis (G-22), fake business-code
  generator for SQLite as in tests/_nz_p6_fixtures.py).
- Run: test_belgium_*.py + attendance gate + AU / CA integration + Poland service / engine + engine
  standard / calendar days + route registry -> 1146 passed, 1 skipped, 4 failed before the guard entry
  (guard fixed; the other 3 = pre-existing health routes).
- Gaps added: G-25 .. G-29.

## A4 — frontend (organisation and employee)

- Commit: 8abb230 `feat(belgium): block A4 organisation and employee screens`.
- A3 commit: 800c464 `feat(belgium): block A3 core engine`.
- Frontend: `Compliances/BEComplianceCentreTab.jsx` (setup status, employer registrations with approve / verify /
  reject, mandates as references, employer ONSS number (vault, masked), establishment units, Joint Committee
  coverage, resolver blockers for every Belgian employee, employee records picker); tab added in
  CompliancePage.jsx for BE orgs (Tax Configuration hidden like PL). `Payroll_Employees/BelgiumStatutoryProfilePanel.jsx`
  (worker profile, work schedules, classification with the Joint Committee / agreement picker, declarations,
  identifier field, resolver panel) + `BEIdentifierField.jsx` (masked NISS / BIS, four-eyes single-use reveal,
  60 s, never stored) + `beOrgPayloads.js`; "Manage" button in EmployeeDetailPanel.jsx for BE.
  `service/payrollService.js` BE section (placed before the Poland section: pl-compliance-ui-validation reads
  from the Poland marker to the end of the file).
- Backend support: `GET /api/payroll/belgium/options` (catalogue vocabularies, so no UI file types a vocabulary
  value) and `GET /api/payroll/belgium/joint-committees` (platform definitions for the picker); route registry
  +2 (tenant_config). Tests added to test_belgium_setup.py (2).
- Validation: `scripts/be-console-ui-validation.mjs` extended with 7 A4 checks (wiring, no statutory number,
  no vocabulary / content key, no payroll arithmetic, no storage / URL / console use of identifiers, every
  imported service function exists, every /api/payroll/belgium path exists in be_org_router.py) -> 16 pass.
- npm test: all 9 scripts pass. Lint: new files clean; CompliancePage / EmployeeDetailPanel clean (same as
  HEAD); payrollService.js 0 findings in the BE section (32 pre-existing older findings).
- Build: NOT VERIFIED on this machine — `npm run build` (NODE_OPTIONS=--max-old-space-size=8192) died twice
  with V8 "out of memory" at ~1.3 GB free physical RAM (it passed in Phase 3B with ~2 GB free). Must be re-run
  with more free memory (or in CI) before merge.

## End of Block A — full backend suite (chunked, reconciled)

- Environment: PAYROLL_DATABASE_URL=sqlite:///<scratchpad>/testdb_<timestamp>/zp_test.db (fresh file per chunk),
  ZP_TEST_POSTGRES_URL unset, Python 3.11 (CI must run 3.12). 472 top-level test files in 12 chunks of 40
  (files that set PAYROLL_DATABASE_URL at import collected first), plus the golden / privacy test dirs in
  chunk 11. One sequential run (an earlier run overlapped with leftover runners from a lost session and was
  discarded).
- Collected 9947 = executed 9947: 9798 passed, 15 failed, 132 skipped, 2 xfailed. Every chunk reconciles
  exactly (collected = passed + failed + skipped + xfailed).
- The 15 failures are all pre-existing and were not investigated: 6 Germany ordering (full business
  acceptance x5, overtime edge cases x1), 5 test_engine_jurisdiction_db_integration ordering, 1 HK
  configuration CSV, 3 route registry (health routes from the uncommitted main.py). No Belgium test fails.
- Skipped include the Postgres-gated RLS tests: the PostgreSQL gate is still OPEN (merge / push blocked on it).

## B0 — decisions G-22..G-29 and migration be_absence_holiday_payment (2943a0490b5b)

- Commit: 8432510 `feat(belgium): block B0 decisions and migration be_absence_holiday_payment` (+ re-pins
  e4065bc and 7d1f735).
- Migration 2943a0490b5b (child of 1d76678ef1a1, single head): payroll_be_absence_episodes,
  payroll_be_holiday_certificates, payroll_be_payment_batches / items (NL mirror + four-eyes),
  payroll_be_component_mappings; pay_basis, contract_type / dates, onss_special_160_status / evidence;
  six new ledger accumulators (PostgreSQL CHECK replaced; SQLite keeps the old CHECK, schema from models);
  RLS as classify() derives; manifest; literal add_column calls for the drift filter.
- Decisions implemented: resolver blocks NULL / unsupported pay basis (profile), NULL / unsupported
  contract (line), UNKNOWN 1.60% status, a second line in the pay period, non-resident; engine maps platform
  pay through ACTIVE mappings (unmapped blocks), 1.60% line from the employer status, reductions / BIK block
  when they apply. Org routes: GET/POST /component-mappings, POST /component-mappings/{id}/approve
  (registry +3, no existing route changed). E2E test shortcut for pay basis removed.
- G-18 / wage scales: user decisions recorded in the gaps register Notes. G-29 (ledger at commit) is B3.
- Tests: test_belgium_block_b_migration.py (new), test_belgium_migrations.py adapted (head pin moved),
  engine / applicability / setup updated + decision tests; Belgium suite 400+ passed.
- Re-pins (standing rule, separate commit): test_alembic_metadata (head, count 261), drift-filter pending
  sets + Block B columns in test_deploy_migrate_script and the NZ x4 / PL / ZA migration tests.
- Registry diff: only the 3 new routes; health routes stripped as before.

## B1 — wages and working time

- Commit: see `feat(belgium): block B1 wages and working time`.
- `engine/jurisdictions/belgium/wages.py`: sector minimum from the line's ACTIVE agreement
  `modules["wage_scales"]` (function class, highest seniority band not above the employee's, optional schedule
  regime, effective dates; part-time pro rata on fullTimeWeeklyHours; hourly rows need the hours paid);
  RMMMG fallback ONLY when the agreement defines no scale (reason in the trace; minimum-age condition; pro
  rata on be_wt_weekly_limit_hours); no agreement linked = no fallback; a breach is BE_MINIMUM_WAGE_BREACH
  (exception, never a top-up); compared with the SECTOR_MIN_WAGE base (new engine obligation). Index-centime
  limitation (be_wage_index_centime_threshold + formula) and wage norm (warning only) run only when an
  indexation input is supplied; pending content blocks.
- `working_time.py`: overtime against the governing schedule (EFFECTIVE per ISO week; AVERAGE over the weeks
  covered); daily / weekly limits as exceptions; Sunday / signed public holiday / employer substitute day
  hours use the holiday premium; premiums from content or the agreement `modules["overtime"]` override;
  compensatory rest via be_ot_compensatory_rest_rule; OVERTIME_HOURS and COMPENSATORY_REST_HOURS ledger
  deltas; premium checked against the hourly rate when known (else an exception); paid overtime without facts
  blocks. Facts come from the platform attendance hours of the run period.
- Public holidays: the pack_holidays hook returns the SIGNED BE_PUBLIC_HOLIDAY rows of the active pack
  (nothing when unsigned / no pack). Substitute days (D15): payroll_holidays category "Substitute", audited in
  payroll_tax_configuration_audit; org routes GET/POST /belgium/substitute-days.
- Super Admin: PUT /compliance/belgium/joint-committees/{id}/wage-modules writes wage scales / overtime
  override on DRAFT Belgian agreements only (validated, audited; approval = existing agreement four-eyes).
- Registry diff: 3 new routes, no existing route changed.
- Tests: test_belgium_wages_working_time.py (new, 19); Belgium + shared engine / attendance / Poland service
  suites: 1093 passed, 1 skipped.
