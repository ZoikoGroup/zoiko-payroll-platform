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

- Commit: 23c02ac `feat(belgium): block B1 wages and working time`.
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

## B2 — holiday pay and absence

- Commit: 6933789 `feat(belgium): block B2 holiday pay and absence`.
- `holiday.py`: SEPARATE strategies (BE-025). White-collar: simple pay = continued salary (signed ack),
  double pay = be_hol_wc_double_pct x reference salary (HOLIDAY_BASE, never the wage floor, BE-028) x months
  worked / 12 in the SERVICE year, minus approved IN certificates of that year and the additional-holiday advance
  (BE-026 offset); additional holidays advanced; departure pay by formula. Manual: holiday-fund regime (employer
  pay = exception), annual debit reconciliation (obligation delta HOLIDAY_FUND_ANNUAL_DEBIT). Service year kept
  apart from the taking year (BE-024); a category change in the service year is an explicit exception. Pay is
  verified, never topped up.
- `absence.py`: episode engine; rules read by a BePack scoped to the incapacity START date (BE-030);
  white-collar guaranteed days (contract condition) else manual day bands; relapse within the window continues
  the day count (chains too) with lookback across the year boundary; declared different cause = new period +
  exception; maternity suspends salary with CBA top-up overlay (BE-032); birth-leave employer vs external days;
  external benefits never in net (BE-031). GUARANTEED_SALARY_DAYS ledger delta.
- Service + routes (four-eyes): absence episodes (record / approve / cancel; no diagnosis field; category at
  start from the approved profile; relapse link validated) and holiday certificates (record / approve;
  immutable after approval; correction supersedes). Calc inputs: ACTIVE episodes (certificate refs stripped),
  approved certificates, profile history, service-year facts from the ledger.
- UI: absence-episode and holiday-certificate sections in BelgiumStatutoryProfilePanel; pay basis / contract
  fields; Compliance Centre: 1.60% status on the registration form, pay-component mappings, substitute days.
  Choice lists from /belgium/options. Validation script: content-key check now uses the catalogue KEYS (org
  files name columns such as be_component) -> 17 checks pass.
- Registry diff: 7 new routes, no existing route changed.
- Tests: test_belgium_holiday_absence.py (new, 19, incl. relapse across 31 Dec 2025 / 1 Jan 2026); Belgium +
  engine standard + Poland service: 957 passed, 1 skipped.

## B3 — run lifecycle, payslip, corrections, payment

- Commit: ed734a1 `feat(belgium): block B3 run lifecycle, payslip, corrections and payment`.
- G-29: ledger posting moved to run COMMIT (APPROVED in before_run_transition); the generation / add-item /
  regenerate / delete posting added in A3 is removed (service.py back to no ledger calls). Draft runs post
  nothing; correction runs post CORRECTION entries linked (reverses_id) to the original RUN entries.
- before_run_transition replaces the Phase 1 refusal. APPROVED: preflight (resolver blockers, pack /
  content pending, engine exceptions, Dimona IN placeholder) must have no BLOCK item; G-18 four-eyes inside
  the BE hook (user decision): approver != run preparer and != creator of any Belgian input the payslips
  use; approval fingerprint stored on payroll_runs.be_approval_fingerprint. AUTHORIZED / PAID: fingerprint
  re-verified; AUTHORIZED needs a person other than the approver, so a retried approval never advances the
  run twice (commit idempotency); ledger post idempotent per payslip + accumulator.
- Engine exceptions (e.g. BE_BSSC_PENDING, always present per D7) stop approval until an org admin
  acknowledges each (employee + code) with a reason (POST /runs/{id}/exceptions/acknowledge; audited;
  stored in the approval record). Blocking reasons can never be acknowledged.
- Corrections: POST /payslips/{id}/corrections (reason + evidence + inputDelta) replays the frozen context
  and creates a CORRECTION run with one payslip carrying the deltas and correctionOf; the original is never
  mutated; one open correction at a time; a correction of a correction / of a draft run is refused.
- Payment (D13): belgium_payment_service.py builds the pain.001.001.09 batch with bank_export/sepa_pain001.py
  UNCHANGED (debtor = company settlement account, creditor = employee IBAN), four-eyes approval before the
  file / submission, bank result, reconciliation, returns; payment_treatment keeps BE payslips out of the
  generic bank file; payslip_hold_view stays None (Phase 1 Q2).
- Payslip §11: snapshot carries documentVersion BE-PAYSLIP-1, the masked NISS / BIS (no digit), sector fields;
  PayslipStub BE branch + BEPayslipBreakdown render bases, employee lines, employer composition (base /
  special / holiday / reduction) and obligations with nl / fr / de content keys (D10); net never editable.
  Individual account: seed_be_individual_account_template (EMPLOYEE scope, Draft, refused activation).
- Frontend: BERunPreflightPanel (acknowledge exceptions, fingerprint), BEPayslipBreakdown, BEPaymentPanel in
  RunDetailPanel; payrollService BE functions; validation 19 checks; npm test all pass; lint clean on new
  files (RunDetailPanel set-state-in-effect error is pre-existing at HEAD); BUILD PASSED locally (14.5 s).
- Registry diff: 13 new BE routes; 11 existing payslip routes LOSE payroll_be_accumulator_entries from
  scan_worker_tables (intended: the G-29 removal of generation-time posting); nothing else changed.
- Tests: test_belgium_run_lifecycle.py (new, 10: preflight, acknowledgements, four-eyes, retried approval,
  fingerprint, corrections lineage, payment batch + XSD, white-collar + manual month end to end, template);
  engine ledger tests rewritten for G-29. Belgium + NL payment / SEPA + shared: 1018 passed, 1 skipped.

## End of Block B — full backend suite (chunked, reconciled)

- Environment: PAYROLL_DATABASE_URL=sqlite:///<scratchpad>/testdb_<timestamp>/zp_test.db per chunk, ZP_TEST_POSTGRES_URL
  unset, Python 3.11. 476 top-level test files in 12 chunks (+ golden / privacy dirs in chunk 11). Chunk 0 ran
  on ed734a1 before an interrupted session; chunks 1-11 re-ran on the same commit (no code change in between).
- Collected 10028 = executed 10028: 9878 passed, 16 failed, 132 skipped, 2 xfailed; every chunk reconciles.
- 15 failures pre-existing (6 Germany ordering, 5 test_engine_jurisdiction_db_integration ordering, 1 HK CSV,
  3 route-registry health routes from the uncommitted main.py). 1 NEW: tests/privacy/test_nonprod_data.py flagged
  the two published example IBANs in test_belgium_run_lifecycle.py; fixed with the repository privacy-scan
  allow marker (see the fix commit); privacy scan + lifecycle tests re-run: 18 passed.
- Frontend at B3: build passed (14.5 s), lint clean on new files, npm test all 9 scripts pass.

## Block C0 — migration be_filing_parallel (952284b; re-pins b188ee0)

- Migration 8a1f5ef9fa5d (child of 2943a0490b5b, single head): payroll_be_filings, payroll_be_obligations,
  payroll_be_reconciliation_variances, payroll_be_parallel_imports (TENANT) and payroll_be_parallel_differences
  (WORKER); RLS as classify() derives; manifest entry; downgrade drops only these five tables.
- Filing CHECKs: authority / form / kind (ORIGINAL, CORRECTION, CANCELLATION) / status vocabularies; a
  CORRECTION or CANCELLATION must carry corrects_id; APPROVED onward needs an approver other than the creator
  and a schema version; TRANSMITTED onward needs a submission reference; UNIQUE idempotency key. Obligations:
  acceptance_status separate from status (accepted-but-unpaid is a legal open state, BE-036); RECONCILED
  needs a reconciler. Variances and parallel differences resolve / accept four-eyes. No statutory number,
  DmfA schema version or calendar date appears in any CHECK (they are content rows).
- Tests: test_belgium_block_c_migration.py (new, 18); Phase 2 / Block B migration tests adapted (drift sets
  gain the Block C tables; single-head check moved to the Block C test). Migration and pin tests: 186 passed,
  1 skipped. Env: PAYROLL_DATABASE_URL=sqlite:///<scratchpad>/testdb_<ts>/zp_test.db, ZP_TEST_POSTGRES_URL unset.
- Re-pin commit b188ee0 (standing rule, exact lists only): test_alembic_metadata (head x2, count 261 -> 262);
  test_deploy_migrate_script (x2), test_nz_filings_migration, test_nz_holidays_act_migration,
  test_nz_leave_pay_migration, test_nz_migrations, test_nz_parallel_migration, test_poland_migrations,
  test_south_africa_migrations: pending-table sets gain the five Block C tables.
- Registry diff: no existing route changed (no routes in C0).
- Open: PostgreSQL RLS run of the new policies (CI merge gate).

## Block C1 — filings and obligations (1403aa5)

- belgium_filing.py: Dimona IN / UPDATE / OUT / CANCEL from the ACTIVE employment lines and their contract dates
  (BE-033): IN once per line; a changed period after transmission is an UPDATE linked to the IN by corrects_id
  (never a silent overwrite); OUT when the line has an end date (linked inFilingId); CANCEL is a CANCELLATION.
  DmfA per legal employer + quarter from the committed ledger + employment lines (BE-034): employee / employer
  contributions per line, masked identifiers, codes PENDING_CONTENT (G-33); a CORRECTION ledger entry counts in
  the quarter of its source period, so a correction of an accepted quarter re-declares that quarter as a linked
  CORRECTION filing. FinProf object from the tax ledger (frequency from the registration, G-30). Belcotax fiche
  per employee for a closed income year with an employee copy (rendition), CORRECTION and CANCELLATION (BE-014).
- Schema by submission date from signed content (G-31): VALIDATED only with signed version + archived XSD +
  mapping + XSD pass; otherwise DRAFT with the reason in validation_note. Approval / submission re-check the
  schema of their own date (30 Sep / 1 Oct boundary sends the filing back to DRAFT). Four-eyes approval (shared
  require_four_eyes + DB CHECK). Transmission adapter refuses (G3 not certified, D9); submission (reference,
  mandate, actor, time) and response (receipt / error codes, immutable) recorded by hand, idempotent per
  reference. Payload hash, rendition, response, timestamps, actor, mandate stored (BE-037); idempotency keys
  hash internal ids + payload hash (no personal data).
- Obligations: ONSS_QUARTER (balance after recorded advances), ONSS_ADVANCE per month from the ONSS notice
  (BE-018), WITHHOLDING, HOLIDAY_FUND; acceptance_status separate from status (BE-036: accepted-but-unpaid stays
  open); payments idempotent per bank reference; OVERPAID and CHANGED_AFTER_PAYMENT variances; reconcile and
  resolve are four-eyes; an ACCEPTED filing becomes SETTLED only when its obligations are paid. Due dates only from
  an Active, sourced calendar row (BE-035, G-32). Exception queue: rejected filing, late Dimona, not validated,
  overdue / unsourced obligation, open variance, payment failure.
- Run preflight: the Block B Dimona placeholder is replaced by a BLOCK when the line has no ACCEPTED Dimona IN
  (BE_DIMONA_IN_MISSING / _NOT_ACCEPTED / _CANCELLED). Correction snapshots now carry employerTotalDelta.
- Content: new kind "schema-version" (SLAB_KINDS; Super Admin slab form gains effectiveTo) and group "filing"
  with four keys (rule types BE_FILING_<FORM>_SCHEMA).
- 21 routes under /api/payroll/belgium (filings, dimona/events, dmfa/quarters/{q}/build,
  withholding-obligations/{p}/build, belcotax/{y}/build, validate / approve / transmit / submission / response /
  cancel, obligations, onss-advances, payments, reconcile, variances, filing-calendar, filing-exceptions).
  Registry diff: no existing route changed; 21 new BE routes (worker class, tenant scope; writes org admin, reads
  payroll operator); registry + inventory CSV regenerated (additive only).
- Frontend: Compliances/BEFilingSettlementPanel.jsx (exception queue, calendar, builders, filing centre,
  obligations / variances) in the Belgium Compliance Centre; payrollService BE filing functions; lint clean on new
  files; be-console validation 19 checks pass.
- Tests: test_belgium_filing.py (new, 25: on-time / late / rejected Dimona, linked update, OUT, cancel, state
  machine, four-eyes (service + DB), D9 refusal, idempotency + no PII, 30 Sep / 1 Oct boundary, the four
  DRAFT reasons, archive check, DmfA content, 2026/Q3 calendar row, overdue, accepted-but-unpaid, advances,
  variances, correction after an accepted quarter, FinProf, Belcotax). test_belgium_run_lifecycle: fixture adds
  contract start + accepted Dimona IN; new BE-033 block test (11). Belgium files: 495 passed, 1 skipped.
  tests/privacy: 294 passed, 13 skipped, 3 failed (the pre-existing health-route registry failures).
  Env: PAYROLL_DATABASE_URL=sqlite:///<scratchpad>/testdb_<ts>/zp_test.db, ZP_TEST_POSTGRES_URL unset.
- Open: G-30..G-33; real XSDs, mappings and codes (G-08); calendar rows; G3 channel.

## Block C2 — parallel run, golden, readiness, release (77de922)

- belgium_parallel.py: an independent payroll's CSV for a committed run (Approved / Authorized / Paid / Closed),
  matched per employee code and concept (gross, withholding, employee ONSS, social work bonus, net, employer
  contributions) against the frozen payslips; tolerance per concept only from signed content
  be_parallel_tolerance_<concept> (new group "parallel", six amount keys, seeded pending; unsigned = exact);
  explain then accept by another person; cycle accepted by someone other than the importer; files with an
  identifier header or a NISS / BIS (11 digits), enterprise-number (10 digits) or Belgian IBAN shaped cell are
  refused before anything is written. G4 = every launch employer (BE_CANARY_ORG_IDS) with accepted cycles in 2+
  distinct months.
- belgium_golden.py: authority examples (BE_AUTHORITY_EXAMPLE rows) now carry a replayable case
  "inputs => expected" (formula_expression; add_authority_example validates it); replayed exactly through the
  engine with the pack's own rows; recorded as the shared TestCertificationRun of BE (PASS / FAIL /
  NO_REAL_CASES). be_pack_activation_refusal now also requires the live replay to pass and the latest BE
  certification run to be PASS (wired through the BE hook; shared service.py untouched).
- belgium_readiness.py: G1-G7 from real evidence (see the runbook table); be_unmet_requirements returns the
  red gates + open launch-blocking decisions, so PLANNED -> AVAILABLE stays refused; the statutory summary
  (be_statutory_summary) reports MET / NOT MET per gate, gate details, status CERTIFIED / NOT_CERTIFIED.
- Registry diff (standing rule): the first regeneration showed 13 EXISTING routes changed (NZ / PL / MX
  parallel routes and MX readiness gained BE worker tables) — callgraph simple-name collisions with the new
  generic function names and with statutory_summary. Fixed by be_-unique names (all C2 functions;
  statutory_summary hook now maps to be_statutory_summary). Final diff: no existing route changed; 10 new
  routes (7 org parallel routes, worker / tenant_config; 3 Super Admin: golden-check, golden-certification
  platform; readiness = aggregate via a reviewed route_overrides entry — it returns counts and organisation ids
  only). Raw PayrollEmployee query avoided (organization_scoped).
- Frontend: BEParallelCyclesSection in the Belgium Compliance Centre; Overview shows real gate states, the failing
  checks and a golden-certification card (register an example with its case, replay, record the run).
- Docs: BELGIUM_ACTIVATION_RUNBOOK.md (canary, opening registration manually, rollback, §15 incident
  categories); BELGIUM_COVERAGE_MATRIX.md (BE-001..BE-040: 17 IMPLEMENTED, 19 BLOCKED-BY-CONTENT, 4
  BLOCKED-BY-EXTERNAL; G1-G7 evidence still needed).
- Tests: test_belgium_parallel_golden_readiness.py (new, 14); content / scaffold / slab-rows / super-admin tests
  updated for the new gates (fully signed content is now refused by the golden gate; status NOT_CERTIFIED).
  Belgium files + tests/privacy: 803 passed, 14 skipped, 3 failed (pre-existing health-route registry).

## End of Block C

- Backend full suite: PARTIAL, by the user's 2026-11-13 rule (full suite only at the end of the whole phase;
  more Belgium phases follow). Chunks 0 and 2-8 of 12 ran on 77de922 (PAYROLL_DATABASE_URL = fresh scratchpad
  SQLite per chunk, ZP_TEST_POSTGRES_URL unset, Python 3.11): 6,419 passed, 11 failed, 111 skipped, 2 xfailed.
  The 11 failures are the known pre-existing ones (5 test_engine_jurisdiction_db_integration ordering,
  5 Germany full-business ordering, 1 HK configuration CSV); none is a Belgium test. Chunk 1 (twice ended with
  no summary; the run was stopped while investigating it) and chunks 9-11 are NOT run: they run with the
  end-of-phase full suite.
- Per sub-step: all Belgium files 509 passed, 1 skipped; tests/privacy 3 failed (pre-existing health-route
  registry, from the uncommitted main.py).
- Frontend: build passed; lint clean on the Block C files; npm test all 9 scripts pass (be-console 19 checks).
- Merge gates before any push: CI PostgreSQL run (RLS of the five Block C tables, the filing / obligation CHECKs),
  Python 3.12, frontend build; the full chunked suite with reconciliation at the end of the phase.

## Block D1 — complete verification

### Full backend suite (end of the Belgium phase), on 9f18e28..b97c366 + D1 test changes

Env: PAYROLL_DATABASE_URL = a fresh scratchpad SQLite per piece (safe_env.sh), ZP_TEST_POSTGRES_URL unset,
Python 3.11. Collected = `pytest --collect-only` on the same files; executed = passed + failed + skipped + xfailed.

| Batch | Files | Collected | Passed | Failed | Skipped | xfail | Reconciled |
|-------|-------|-----------|--------|--------|---------|-------|------------|
| 0 | 1-40 | 667 | 663 | 0 | 4 | 0 | yes |
| 1 | 41-80 (4 pieces of 10) | 587 | 585 | 0 | 2 | 0 | yes (see note) |
| 2 | 81-120 | 1,637 | 1,624 | 10 | 1 | 2 | yes |
| 3 | 121-160 | 891 | 889 | 1 | 1 | 0 | yes |
| 4 | 161-200 | 942 | 941 | 0 | 1 | 0 | yes |
| 5 | 201-240 | 610 | 580 | 0 | 30 | 0 | yes |
| 6 | 241-280 | 384 | 354 | 0 | 30 | 0 | yes |
| 7 | 281-320 | 631 | 617 | 0 | 14 | 0 | yes |
| 8 | 321-360 | 783 | 751 | 0 | 32 | 0 | yes |
| 9 | 361-400 (5 pieces) | 1,309 | 1,305 | 0 | 4 | 0 | yes |
| 10 | 401-440 (4 pieces) | 712 | 711 | 0 | 1 | 0 | yes |
| 11 | 441-479 (2 pieces) | 624 | 623 | 0 | 1 | 0 | yes |
| 11x | golden + privacy dirs | 310 | 294 | 3 | 13 | 0 | yes |
| **Total** | 479 files + 7 dirs | **10,087** | **9,937** | **14** | **134** | **2** | **10,087 = 10,087** |

Batches 2-8 ran on 77de922 (identical non-test code; D1 changed only Belgium migration tests and CI); their
collected counts were re-taken now and match exactly. Batch 0 was re-run on the current tree (it holds the
two new PostgreSQL round-trip tests, skipped locally).

Batch 1 note: files 51-60 (Brazil inapp / phase1 / phase2 / rls / router / scaffolding, bs_report_forms,
bulk_employees, business_plan) reach 100% when run together and the process then exits without printing a
summary (a teardown problem, not a failure); each file run on its own passes (7+15+23+55+5+18+26+4+3+6 = 162 =
collected). This is why "chunk 1" never reported a result. No Belgium file is involved.

The 14 failures are all on the known pre-existing list: 5 test_engine_jurisdiction_db_integration (ordering),
5 test_germany_full_business_acceptance (ordering), 1 test_hong_kong_configuration (CSV), 3
tests/privacy/test_route_registry.py (health routes of the uncommitted main.py). No new failure; no baseline
run was needed.

### G-18 recorded
BELGIUM_GAPS_AND_DECISIONS.md: G-18 DECIDED + DELIVERED with every enforcement point (belgium_service
before_run_transition / _input_creators / be_approval_fingerprint / post_be_accumulators, the approve_*
four-eyes functions, uq_be_accum_payslip_accumulator) and the tests that prove them.

### CI
- `.github/workflows/backend-deploy.yml` (+ the staging copy): job `test` (Python 3.12, full `pytest -q` on
  SQLite: collects every test_belgium_*.py); job `privacy-isolation` (PostgreSQL 15 service,
  ZP_TEST_POSTGRES_URL, ZP_REQUIRE_POSTGRES_TESTS=1, Python 3.12) runs tests/privacy only — its
  test_postgres_guards builds the schema from the models + derived RLS, so every payroll_be_* table is
  covered by "every derived worker / tenant table has FORCE RLS"; `frontend-build.yml`: Node 20 `npm ci` +
  `npm run build`.
- Gap found: the Belgium PostgreSQL round trip (test_belgium_migrations) was never collected by the
  PostgreSQL job, and Blocks B / C had none; the Phase 2 test would also have failed on its first PostgreSQL
  run (it asserted that NO payroll_be_* policy remains after its own downgrade, but later Belgium tables keep
  theirs).
- Fix (additive): a shared `pg_round_trip()` helper checking only the revision's own tables; PostgreSQL
  round-trip tests for 2943a0490b5b and 8a1f5ef9fa5d; a last step in the privacy-isolation job of both
  workflows running the three Belgium migration test files on its PostgreSQL. Not runnable locally (no
  disposable PostgreSQL here): these run in CI only.
- Registry diff: no route changed.

## Block D2 — hardening review

- docs/belgium/BELGIUM_SECURITY_REVIEW.md: findings F1-F5 with fixes; identifier exposure review; the 98-route
  table generated from the registry and the live app; every shared-file hunk listed (all additive and
  BE-guarded; none flagged); numeric guard / no eval-exec / formula grammar; fail-closed audit of the 11 places
  a Belgian result can be produced.
- Fixes: F1 filing-calendar route pins the caller's organisation (be_org_router); F3 stale comments in the BE
  lines of engine/standard.py and service.py (comment only). F2 was fixed in D1; F4 / F5 in C2.
- Tests: tests/test_belgium_security_review.py (new, 5): a synthetic month with a NISS and an employer ONSS
  number scanned across snapshots, serialized payslip, filings, obligations, parallel rows, audit, access
  events, logs, the payroll-register CSV and error messages; route test (dormancy dependency, own org,
  org-admin writes, no org id input). Content + formula + security: 82 passed.
- Registry diff: no route changed.

## Block D3 — content intake tool

- be_content_workbook.py: export (XLSX via openpyxl; sheets Instructions, Scalar keys, Parallel tolerances, Slab
  keys (+ required fields, dimension format and one template line per key), Filing schema versions, Earning
  classification, Calendar rows (+ template), Owner decisions, Sources S1-S24 with archive status); every cell is
  text; content only. Import into a Draft pack only: dry run by default (every changed cell OK / ERROR with
  `Sheet!Cell` and the reason; validation through the same governed writers update_row / add_slab_row, then
  rolled back); a real import is all-or-nothing, needs a source per changed row, records the importer as the
  editor (audit before / after images), never signs, never activates; calendar rows are created Draft.
  Bulk signing: refused as a whole when the signer imported or edited any selected row; each row signed through
  update_row with its own reviewed, archived source and audited on its own.
- Routes (Super Admin, platform class): GET /compliance/belgium/packs/{id}/content-workbook,
  POST .../content-workbook/import (dry_run=true default), POST .../bulk-sign. Registry diff: no existing route
  changed.
- Guard finding fixed before commit: an Instructions example used the spec's employee ONSS rate as a sample
  number; the text now carries no figure.
- UI: Belgium Signing status tab gains Export / Import (dry-run preview table, then Confirm) / Bulk sign.
- Tests: test_belgium_content_workbook.py (new, 7): sheets and rows, no personal data, round trip without
  changes, cell-referenced vocabulary / source / dimension / date errors and nothing written, valid import writes
  unsigned rows + Draft calendar rows with the importer as editor, non-Draft pack refused, the importer cannot
  bulk-sign while another Super Admin can (one audit row per row). Content + workbook + super admin + slab rows:
  passing. Frontend: lint clean, be-console validation 19 checks.

## Block D4 — handover and merge package

- New docs: BELGIUM_SPECIALIST_PACK.md (generated from the catalogue: all 83 keys by group with kind, spec
  reference, what is needed, spec-proposed label, workbook sheet and gate; other content; open owner decisions
  G-01, G-02, G-06/17, G-11, G-12, G-13, G-16, G-21, G-26, G-30), BELGIUM_AUTHORITY_ONBOARDING.md (schemas +
  mappings, codes, channel / credentials, mandates, calendar rows, end-to-end evidence; owner and gate each),
  PR_DESCRIPTION.md (architecture, migrations in order, shared hunks, re-pin commits, test evidence, merge gates,
  rollback). BELGIUM_SECURITY_REVIEW.md came with D2.
- BELGIUM_COVERAGE_MATRIX.md: D2 / D3 tests added where they prove BE-038 / BE-039 / BE-040; all 19 cited test
  files exist; every Belgium test file run: 20 files, 521 passed, 3 skipped (PostgreSQL round trips, CI only).
- Final checks: single Alembic head 8a1f5ef9fa5d (1d76678ef1a1 <- efc56f3235e2, 2943a0490b5b <- 1d76678ef1a1,
  8a1f5ef9fa5d <- 2943a0490b5b); manifest / drift / metadata tests 13 passed; npm test all 9 scripts pass; lint
  clean on every Belgian frontend file; frontend build passed (16 s). No push.
