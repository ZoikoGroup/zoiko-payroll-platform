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

## Block E — product decisions

- G-11 MONTHLY only, G-12 high-risk list, G-13 operator English recorded DECIDED in BELGIUM_GAPS_AND_DECISIONS.md.
- G-12 verified against the code: every listed change is four-eyes. Finding F-G12-1 (recorded, not changed — the
  signing code stays as built): one Super Admin can edit and sign the same row in a single console call; content
  four-eyes is enforced at pack approval / activation and in bulk sign.

## Block E1 — AI-drafted statutory content

- docs/belgium/content/BE_2026_AI_DRAFT.xlsx: the D3 workbook of BE-PAYROLL-2026 with a proposal for every row and
  the review columns proposedValue / sourceUrlOrSpec / retrievalDate / confidence / reviewerNote; sheets Draft
  sources (11 references D01-D11), Band proposals (post code list), Decision proposals (G-01, G-02, G-06/17,
  G-13, G-16, G-21, G-26, G-30 — all OPEN), NOT FOUND.
- Counts: HIGH 9, MEDIUM 36, LOW 187 (180 of them earning classes), NOT FOUND 72. Sources: the spec first; ONSS
  2026/3 instructions, DmfA deadline table and 2026/3 glossary, Royal Observatory holiday calendar; Securex /
  Partena as secondary (conflicts noted). Web searches on 2026-11-13; no value invented: Annex III, reductions,
  rounding, BSSC, day bands, schema versions other than DmfA, tolerances and most calendar rows are NOT FOUND.
- The generator stayed in the scratchpad (no statutory value in repository code); the workbook is the artifact.

## Block E2 — import as unsigned drafts

- be_content_workbook import gains two portability features (Belgium-only): sourceDocumentId may be a source
  REFERENCE (SourceArtifact.form_number, e.g. ZP-BE-AI-DRAFT D02) as well as an id; an optional "Draft sources"
  sheet creates missing references as UNVERIFIED, unarchived sources (they can never be used to sign).
- Import run on a fresh local SQLite copy of the Draft BE-PAYROLL-2026 (seeded by the canonical seed script; no
  shared or production database touched): dry run 261 changes, 0 errors (nothing to fix); real import written,
  261 changes, 0 rows signed, pack still Draft, 35 scalar rows with a value, 194 slab rows. The import in a real
  environment is done by a Super Admin in the console (the importer becomes the editor for four-eyes); no account
  was created.
- Tests: test_belgium_content_workbook.py +2 (source reference and draft sources; the committed AI draft imports
  with 0 errors and signs nothing). Workbook + content: 32 passed. Registry diff: no route changed.

## Block E3 — reviewer pack

- docs/belgium/BELGIUM_REVIEWER_GUIDE.md: counts (HIGH 9 / MEDIUM 36 / LOW 187 / NOT FOUND 72); the NOT FOUND list
  and LOW items first with what to check and where; the three conflicts found (RMMMG periods, 1.60% vs 1.69%,
  10.27% year); 10 worked payslips (white-collar / manual; low / median / high; with / without dependants; weekday
  and Sunday overtime; double holiday pay) line by line from drafted values only — withholding, work bonus and BSSC
  are shown as NOT DRAFTED, so each stops at "net before withholding and BSSC"; the two-reviewer import / review /
  bulk-sign procedure; the explicit note that these examples do not satisfy golden certification.

## Block E4 — DEMO pack (non-production only)

- belgium_demo.py: BE-DEMO-2026 "DEMO — NOT FOR PAYROLL" built from the AI-drafted workbook; NOT FOUND rows take
  clearly fake placeholders from docs/belgium/content/BE_DEMO_PLACEHOLDERS.json (generated from the synthetic
  TEST ONLY engine pack; no value in code). Every row labelled DEMO, signed and Active ONLY via be_seed_demo_pack.
- Guards: new settings BE_DEMO_PACKS_ENABLED (default false) and BE_DEMO_ORG_IDS; production = ENVIRONMENT /
  APP_ENV production / prod / live, or none set with DEBUG false -> demo refused everywhere. Calc inputs refuse a
  DEMO pack for a non-demo organisation; _be_pack_for returns no pack (preflight BE_PACK_MISSING); governed
  activation refuses DEMO packs; assignment refused unless every organisation is a demo organisation (shared
  assign_pack_to_organizations BE branch now passes the organisation ids — additive, BE-guarded).
- Watermark and money / authority stops: payslip snapshots carry demo + "DEMO — NOT FOR PAYROLL"; DEMO payment
  batches can be built and approved but never submitted, never released as pain.001, never given a bank result;
  filings built from DEMO payslips (and a demo organisation's Dimona) carry demo, the rendition starts with the
  DEMO label, transmission and submission are refused. A demo organisation's run replaces the Dimona IN block by a
  non-blocking BE_DEMO_DIMONA_SIMULATED item (its Dimona is never transmitted). UI: DEMO watermark on the payslip
  stub and breakdown, DEMO badge on payment batches and filings.
- scripts/seed_belgium_demo.py: local / staging only (_local_db_guard, flag, non-production); creates the demo
  pack, a demo organisation (BE-DEMO), two demo employees (white-collar 495, manual 015) and one demo month
  (setup -> preview -> approve -> payslips -> DRAFT payment batch -> DmfA draft). Creates NO user account: it needs
  two existing, different user ids (--preparer, --approver).
- Registry diff: 10 existing Belgian routes changed, all intended (demo checks read payslip snapshots / payment
  items): 9 gain scan tables only; GET /payment-batches tenant_config -> worker (the list flags DEMO batches;
  stricter, principals unchanged). Registry + inventory regenerated.
- Tests: test_belgium_demo.py (new, 8): off by default and refused in production (incl. DEBUG-off default),
  seed refused when disabled / production, demo pack labelled / signed / Active while the real pack stays Draft and
  unsigned, governed activation and assignment refuse it, a non-demo organisation never calculates with it,
  end-to-end demo month never paid or transmitted, switching demo off blocks the demo organisation, the seed never
  creates accounts. Belgium files + privacy: 825 passed, 16 skipped, 3 known health-route failures.

## Block E5 — authority onboarding drafts

- docs/belgium/authority/: README (index, owners), 01 Dimona / DmfA channel access + test environment (ONSS),
  02 FinProf + Belcotax-on-web access (FPS Finance), 03 XSD / technical documentation download list (URLs found on
  2026-11-13) + request, 04 mandate template per launch employer. Every company value [TO FILL]; every address not
  verified in this session [TO CONFIRM]. Nothing sent.

## Block F1 — F-G12-1 fixed

- be_super_admin: update_row refuses signing when the same call changes a value ("never edited and signed in one
  action") and when the signer edited the row in this pack version (be_row_editors: created it or changed a value;
  signing alone is not an edit); changes are now collected and applied only after the check (nothing is mutated on
  refusal). add_slab_row refuses specialistVerified: new rows are always added PENDING. Bulk sign and activation
  rules unchanged; other countries' consoles untouched.
- UI: the Belgian row editor refuses sign-with-changes before sending ("Sign (no changes)"); the add-row form never
  sends the signing flag.
- Tests: test_belgium_signing_four_eyes.py (new, 8); super-admin and slab-row tests moved to edit-then-sign by a
  second user. Belgium files: 539 passed, 3 skipped (PostgreSQL round trips). PL / NZ console tests pass. Registry
  diff: no route changed. BELGIUM_SECURITY_REVIEW.md and the gaps register record F-G12-1 as FIXED.

## Block F2 — source acquisition list

- docs/belgium/sources/DOWNLOAD_LIST.md: 30 documents in 7 groups (A Annex III withholding incl. the 24 Jul 2026 and
  27 Sep 2026 / 1 Nov 2026 versions and the quarterly-declaration threshold; B ONSS 2026/3 instructions, quarterly
  rate files by EC x WC, BSSC scale, work bonus, structural / target-group reductions, company car; C manual-worker
  holiday contributions for the current holiday year and holiday-pay rules; D guaranteed-salary day bands,
  maternity / birth leave; E RMMMG dated amounts, index-centime law, working time, public holidays + substitution;
  F Dimona / DmfA 2026/2-2026/3 / FinProf / Belcotax 281.10 schemas, codes, deadline table; G legal sources for
  G-13 / G-16 / G-21), each with publisher, version, URL found or official site + section, and workbook rows filled.
- docs/belgium/sources/inbox/README.md: "save downloaded files here unchanged; do not rename" (+ optional meta file).

## Block F3 — inbox parse run

- Inbox at the time of the run: **0 documents** (only README) — nothing parsed, no workbook value changed, confidence
  counts unchanged (HIGH 9 / MEDIUM 36 / LOW 187 / NOT FOUND 72).
- scripts/be_source_inbox.py (rerun whenever files arrive): hashes every inbox file, writes
  docs/belgium/sources/INBOX_MANIFEST.md (size, SHA-256, DOWNLOAD_LIST id, official flag from <file>.meta.txt) and,
  with --register on a local / isolated database, records each file as a SourceArtifact (form number
  ZP-BE-SRC-<hash prefix>); only a file marked official is archived (checksum + file path), others are
  [UNVERIFIED]; idempotent by checksum. Value extraction stays a reviewed step with page / section references.
- Annex III grammar: not assessed (no key-formula document yet); no grammar change.
- D3 dry-run import of the committed workbook: 0 errors (test_belgium_content_workbook). Conflicts still listed
  for the reviewer (no official dated document yet).
- Tests: test_belgium_source_inbox.py (new, 2). DOWNLOAD_LIST count corrected to 30 documents.

## Block F4 — reviewer efficiency

- Workbook: new "Patterns" sheet — the 180 earning-class cells form 8 patterns (components with the same
  INCLUDED / EXCLUDED treatment in all ten obligations), each with member cells (sheet!cell), reason, source,
  confidence and a reviewerDecision column. Console Bulk sign: "Earning-class patterns" list selects a pattern's
  pending cells (each cell still signed and audited individually; four-eyes unchanged).
- Fix found on the way: the E1 sheet "Band proposals (after code lists)" was 33 characters (Excel's limit is 31,
  so Excel could refuse the file); renamed "Band proposals (post code list)" in the workbook and the demo seed.
- Worked payslips: all 10 still PARTIAL (no withholding / BSSC / work-bonus source yet).
- BELGIUM_REVIEWER_GUIDE.md: review-in-this-order list (withholding, ONSS, BSSC, work bonus, holiday, absence, …),
  the patterns table, the conflicts, examples status; counts unchanged (HIGH 9 / MEDIUM 36 / LOW 187 / NOT FOUND 72).
- Tests: +1 workbook test (sheet names <= 31, patterns cover the 180 cells exactly once); workbook + demo: 18 passed.
  Frontend: lint clean, be-console validation 19 checks.

## Block F5 — merge readiness (STOP for decision)

- `git fetch origin` (read-only): origin/main `6081174` is 6 commits past the base 1af3d44 (payslip templates PR
  #158 etc.); nikhil is 42 commits ahead. Main adds migration f3a9c1d7e2b4 (child of efc56f3235e2) — a plain merge
  would give two heads → re-chain 1d76678ef1a1 onto f3a9c1d7e2b4 inside the merge commit.
- `git merge-tree` simulation: 13 conflicting files (models.py, PayslipStub.jsx, 11 migration pin tests), all
  additive "both sides" conflicts.
- Trial in a scratch copy of the merge tree (branch untouched): resolutions for models.py / test_alembic_metadata +
  the re-chain + manifest SHA → single head 8a1f5ef9fa5d; Belgian migration tests + alembic metadata / manifest:
  72 passed, 3 skipped. Main's payslip-template tests need its new packages (mammoth, pdfplumber, xhtml2pdf) locally.
- docs/belgium/MERGE_PLAN.md (merge commit recommended over rebase; exact steps); PR_DESCRIPTION.md updated with
  Blocks E / F and the demo flags. Nothing merged, rebased, re-chained on the branch or pushed.

## Block H1 — post-merge secret / PII scan and payslip render paths

- H1a scan of every file added / changed in 1af3d44..a1e4914 (176 files; content at a1e4914): no private key,
  cloud / payment / VCS token, JWT, password assignment, .env file or file > 5 MB. Two connection strings are the
  disposable CI PostgreSQL service (`zp_privacy:zp_privacy@localhost`, test-only, pre-existing job pattern). One
  mod-97-valid NISS shape: `85073003328` in tests/test_belgium_scaffold.py (refusal-test fixture, the published
  Belgian documentation example 85.07.30-033.28, not a real person's record) — replaced by the checksum-invalid
  `85073003300`. docs/belgium/authority/: placeholders only ([TO FILL]), no company data.
- H1b render paths after PR #158 (payslip templates):
  | Path | Before | Now |
  |------|--------|-----|
  | GET /payslips/{id}/download, run ZIP, payslip e-mail (generate_payslip_pdf_bytes) | template PDF or generic reportlab layout — no §11 content, no DEMO watermark | Belgian §11 PDF (belgium_payslip_pdf.py): snapshot only, masked NISS, DEMO watermark every page; no snapshot → 409 BE_PAYSLIP_NO_SNAPSHOT |
  | GET /payslips/{id}/rendered (template HTML) | rendered a BE payslip through an assigned template | 409 TEMPLATE_NOT_REPRESENTABLE (UI falls back to the BE §11 view) |
  | template xhtml2pdf PDF (render_payslip_pdf / template_pdf_or_none) | possible for BE | refused / None |
  | template create / update / assign / import-from-PDF with country BE | allowed | 400 "do not apply to Belgium" |
  | template preview / preview PDF (sample data) for BE | generic sample | 400 refused |
  | freeze_run_templates at approval | pinned BE payslips to a template | BE skipped |
  | GET /payslips/{id} (on-screen PayslipStub BE branch) | §11 from beCalculationSnapshot, masked, demo label | unchanged |
  | mammoth / pdfplumber import (analyze-pdf) | builds a template from an upload; renders no payslip | BE scope refused at save |
- Tests: tests/test_belgium_payslip_render_paths.py (5, incl. demo PDF: watermark on every page, no NISS shape).
  Guard: belgium_payslip_pdf.py layout numbers registered. Registry: fresh == stored (0 changed).

## Block H2a-c — deploy rehearsal, production-like startup, seed entry points

- H2a `backend/scripts/be_deploy_rehearsal.py` (throwaway SQLite only): production-like state at f3a9c1d7e2b4
  (create_all minus the 19 payroll_be_* tables and the 2 shared columns, stamped) → read-only drift check: 21 BE
  drift lines, all explained by scripts.drift_pending_filter f3a9c1d7e2b4 (unexplained: none) → `alembic upgrade
  head` → 8a1f5ef9fa5d, 19 tables + 2 columns, drift check exit 0 → second upgrade head: no-op, drift 0 → the
  orphan-path stamp walk finds 8a1f5ef9fa5d after / f3a9c1d7e2b4 before the upgrade (never stamps over pending
  migrations) → downgrade 2943a0490b5b (14 tables) → 1d76678ef1a1 (9) → f3a9c1d7e2b4 (0 tables, 0 columns) on
  empty tables → drift again explained → re-upgrade clean. RLS is PostgreSQL-only (CI privacy-isolation job).
- H2b `tests/test_belgium_production_startup.py`: fresh interpreter, real app WITH lifespan, ENVIRONMENT=production,
  every BE_* unset, throwaway SQLite → starts; every /api/payroll/belgium route (method × path) answers 404 to a
  Belgian org's own admin; Super Admin console packs / decisions / joint-committees / readiness answer 200 (empty);
  0 BE packs, 0 payroll_be_* rows, no BE registry row after startup.
- H2c seed entry points (none automatic):
  | Entry point | Writes | Trigger |
  |-------------|--------|---------|
  | app startup `initialize_database` → `_seed_reference_content` | Assist KB / capabilities only | every start (not Belgian) |
  | `scripts/deploy_migrate.sh` / backend-deploy.yml | migrations + read-only drift checks; no seed | deploy |
  | BE migrations 1d76678ef1a1 / 2943a0490b5b / 8a1f5ef9fa5d | schema + RLS only (one DELETE in a downgrade of the ledger accumulator list) | deploy |
  | `scripts/seed_belgium_registry.py` | PLANNED registry row (create-only) | manual; `_local_db_guard` |
  | `scripts/seed_belgium_canonical_packs.py` | Draft BE-PAYROLL-2026 `[PENDING G1]` + PLANNED row | manual; `_local_db_guard` |
  | `POST /api/super-admin/compliance/belgium/seed-draft` | same Draft pack + PLANNED row (only while no BE pack; reason; audited) | Super Admin click |
  | `scripts/seed_belgium_demo.py` | BE-DEMO-2026 + demo org / month | manual; refused unless BE_DEMO_PACKS_ENABLED and not production; `_local_db_guard`; needs 2 existing users |
  | `belgium_service.seed_be_individual_account_template` | Draft individual-account report template | no caller in app (tests only) |
- H2d docs/belgium/DEPLOY_NOTES.md: pre-merge checklist, what the deploy changes, read-only verification SQL,
  rollback, first manual steps. Rollback ORDER deviates from the brief on purpose: schema downgrade (empty tables
  verified) BEFORE the code revert. After a code revert the three revision files are gone (alembic cannot
  downgrade), and check_schema_drift refuses the next deploy on the two shared columns the reverted models do not
  declare. The "already reverted" recovery path is documented.

## Block H3 — staging rehearsal; CI fix

- docs/belgium/STAGING_REHEARSAL.md: staging-only switches (+ staging-only identifier keys for the NISS steps),
  seed command, 17-step click-through with expected results, turning the demo off, clean-up (restore preferred;
  read-only inventory SQL; no scripted delete).
- Fix found while writing it: the demo organisation was created as a PRODUCTION workspace without a plan → the
  plan guard would answer 403 on every payroll screen. scripts/seed_belgium_demo.py now creates it as EVALUATION
  (test asserts it); demo PDFs then also carry the evaluation watermark.
- CI privacy-isolation failure (user report): the Belgian PostgreSQL round trips' single `DROP SCHEMA public
  CASCADE` over the privacy suite's 373-table schema exhausted the lock table ("out of shared memory"). Reproduced
  on a disposable local PostgreSQL with CI defaults (max_locks_per_transaction 64, 100 connections); fixed with
  pg_reset_public_schema (25 tables per transaction). The 3 BE migration files: 69 passed, round trips executed.

## Block I1 — rollback decision

- Default rollback (owner decision) = revert the code, keep the additive schema. Proof:
  `scripts/be_rollback_orm_check.py` runs main's pre-Belgium code 6081174 against CONTROL (its own schema) and
  BELGIAN (8a1f5ef9fa5d: 19 tables + 2 columns + Draft BE pack). Basic IN payroll operations (org, employees, run,
  generate 2 payslips, advance, read / list / PDF, updates) are identical → ORM compatible.
- Finding: a PLAIN revert is not deployable. `alembic upgrade head` → "Can't locate revision 8a1f5ef9fa5d";
  deploy_migrate.sh → orphan path → "Refusing to stamp" on payslip_items.be_calculation_snapshot /
  payroll_runs.be_approval_fingerprint → exit 1 before the restart.
- `scripts/belgium_rollback_shim.py` (run after `git revert -m 1`): restores the 3 revision files + manifest
  lines (sorted), the 2 nullable column declarations and the 10 re-pinned alembic / drift-set tests; idempotent,
  dry-run, refuses a file changed on main after the merge. Revert + shim: deploy_migrate.sh exit 0, drift clean,
  operations identical, 135/135 pin tests in the shim tree. tests/test_belgium_rollback_shim.py (2).
- DEPLOY_NOTES §4 rewritten: 4.0 behaviour only, 4.1 default revert + shim (exact commands), 4.2 what stays,
  4.3 schema removal only if required (checks → downgrade with the files present → revert without the shim).
  Supersedes the H2d rollback order.

## Block I2 (fixes) + I3 — scale fixes, observability, operations runbook

- I2 fixes (Belgian code only; numbers in docs/belgium/PERFORMANCE.md):
  - acknowledge_be_run_exception re-ran the whole-run preflight per acknowledgement (O(N²): 100 employees =
    553 s / 907 statements per item) → reads only that employee's payslip (4 statements, flat);
  - preflight: pack resolved once per run (pack= on resolve_be_classification), acknowledgements set built once;
  - ledger posting at approval: one read of already-posted entries + employees (was a query per entry, each
    autoflushing the pending inserts);
  - DmfA: worker block built once per employee (setdefault evaluated _worker() — a vault query — per ledger
    entry); payslips read once for employer totals + demo flag. Belcotax: entries grouped once (were rescanned
    three times per employee);
  - preview: the Active pack row cached per session / pay date (whole pack was resolved per employee);
  - session read cache for plain Belgian record lists (classifications, schedules, declarations, profiles,
    absence episodes, holiday certificates) and the component-mapping index: one org-wide read per table,
    cleared on commit / rollback / any flush writing a Belgian record, pending Belgian records flushed first.
  - Registry: POST /belgium/runs/{run_id}/exceptions/acknowledge reads fewer tables (no preflight) — intended,
    narrower; registry + inventory regenerated (fresh == stored).
- I3: belgium_observability.py — `be_log_event` on logger zoiko.belgium, allow-list of fields (event, code, ids,
  form, state, count); anything else raises and the event is dropped (never a NISS, name, IBAN or amount). Events:
  be.calculation.blocked (engine), be.run.approval_refused (per code + count), be.filing.state (SQLAlchemy listener
  on PayrollBeFiling.status — every transition), be.filing.refused (_conflict), be.payslip.pdf_refused,
  be.identifier.reveal (REVEAL_REQUESTED / REVEAL_APPROVED / REVEALED). No metrics library exists in the platform
  → structured logs only (log pipeline counts by event / code; correlation id added by core/correlation.py).
- OPERATIONS_RUNBOOK.md generated by scripts/belgium_ops_runbook.py: 92 codes discovered from the code (21
  identifiers excluded: settings, rule types, report types, channels) with kind / meaning / cause / owner / fix +
  support playbook. tests/test_belgium_ops_runbook.py (3): undocumented code, stale entry or stale file fails.
- Tests: test_belgium_observability.py (3, real flows captured: no NISS / name / IBAN / amount in any record);
  all Belgian tests green (guard: observability regex shapes registered).

## Block I4 — user guides (docs/belgium/guides/)

- SUPER_ADMIN_GUIDE.md: content lifecycle (Create the Draft pack → Export workbook → Dry run / Confirm import →
  Earning-class patterns / Select pending cells → Sign N selected (second person) → Register example / Record
  certification run → Approve → activation runbook → Assign Organizations), release gates, demo pack.
- ORG_ADMIN_GUIDE.md: employer registration, establishment units, special contribution (workforce test) status,
  pay component mappings, employee statutory records, contracts and Dimona, NISS reveal, running payroll and the
  Belgium preflight, payment batches, filing centre, obligations, parallel cycles.
- PAYSLIP_EXPLAINER.md: each payslip section in plain English with its be.payslip.* content keys (nl / fr / de
  ready; header / net keys marked as proposed — not yet content-keyed in the code).
- Every screen label taken from the UI code (BEComplianceCentreTab, BEFilingSettlementPanel, BEParallelCycles,
  BelgiumStatutoryProfilePanel, BEIdentifierField, BERunPreflightPanel, BEPaymentPanel, BEOverviewDashboard,
  BESigningStatusTab, JurisdictionLayout / OrgsTab).

## Block I5 — post-deploy setup command

- `backend/scripts/belgium_post_deploy_setup.py`: `--environment <name>` (must match ENVIRONMENT / APP_ENV),
  `--confirm` to write, `--dry-run` plan + checks. Create-only: PLANNED registry row (existing row never changed),
  Draft BE-PAYROLL-2026 when no Belgian pack exists (audited), S1-S24 sources; then the DEPLOY_NOTES §3 checks
  (PASS / FAIL, exit 1 on a failure, 2 on a refusal). Never signs / approves / activates / assigns, sets no
  setting, never creates the DEMO pack (refuses BE_DEMO_PACKS_ENABLED in production), no other country, no
  create_all. `be_register_evidence_sources` extracted from seed_belgium_pack (same behaviour).
- tests/test_belgium_post_deploy_setup.py (4): refusals, dry run writes nothing, create-only + idempotent + nothing
  signed / Active / assigned / DEMO + other country and settings untouched, a non-Draft pack never re-seeded.
  CLI exercised on a throwaway SQLite at the head: dry run 8 PASS; no --confirm refused (exit 2); confirm DONE x3
  + 8 PASS; second run "nothing to do".
- DEPLOY_NOTES §5 step 1 is now this command (console "Create the Draft pack" kept as the alternative).

## Block I2 (measurement, guard, report)

- Harness tests/perf/be_scale_harness.py (synthetic DEMO org, throwaway SQLite; wall time, statements, statements
  per item, statement kinds, tracemalloc peak with --memory, process peak via psutil). Before = export of edfec72.
- Before: acknowledging exceptions O(N^2) — 457 → 907 statements per item (50 → 100 employees), 104 s → 553 s; a
  500-employee before-run was stopped after 16 min. After: every step flat in statements per item 50 → 2,000.
- Extra fix found at 2,000: Belcotax fiche lookup scanned the year's fiches per employee (index has no subject) →
  `_latest_by_subject` one read + `upsert_filing(latest=…)`: 17.05 s / 5.0 → 13.19 s / 4.0.
- Main capacity finding (not fixed, owner decision): ~240 KB snapshot per payslip (frozen pack copy + used rows
  stored twice) → approval peak 1.1 GB at 500 (tracemalloc), process peak 4.3 GB at 2,000. Recommendation:
  content-addressed pack reference + used rows once (audit-format change); meanwhile size workers ~2.2 MB/employee.
  Also recommended: bulk acknowledge (per-click acknowledgement is O(N) through the JSON list).
- tests/perf/test_belgium_scale.py (slow; skipped unless ZP_BE_SCALE=1; tests/perf/conftest.py): statement ceilings,
  no growth small → large, per-employee time ceilings. Ran once: 1 passed (76 s). Default run: skipped.
- docs/belgium/PERFORMANCE.md: method, before / after table, memory, fixes, remaining super-linear causes,
  PostgreSQL / RLS items for CI / staging. Registry unchanged (fresh == stored).

## Block J1 — rollback shim proven in CI

- The shim was already committed in I1 (backend/scripts/belgium_rollback_shim.py, a5809df, with
  tests/test_belgium_rollback_shim.py); DEPLOY_NOTES already used that path.
- New tests/test_belgium_rollback_proof.py (ZP_BE_ROLLBACK_PROOF=1): runs scripts/be_rollback_orm_check.py — ORM
  identical with the Belgian schema; plain revert refused by deploy_migrate.sh; revert + shim → deploy_migrate.sh
  exit 0, drift clean, operations identical, pin tests passed >= 135 (now reported as pinTestsPassed). Local run:
  1 passed (172 s, Git Bash, throwaway SQLite).
- CI: two additive steps at the end of privacy-isolation (gates deploy) in backend-deploy.yml and
  backend-deploy-staging.yml: fetch the pre-Belgium commit 6081174 (depth 1), run the proof. The proof's
  subprocesses drop ZP_TEST_POSTGRES_URL / DATABASE_URL / ZP_REQUIRE_POSTGRES_TESTS (SQLite only).
- Limitation: the proof simulates the revert as "main before the Belgium merge"; a later main migration chained
  after 8a1f5ef9fa5d would need its own rollback review (the shim also refuses files changed after the merge).

## Block J2 — snapshot version 2 (memory)

- `"snapshot_version": 2`. frozenContext.version 2 = packRef (pack row id, packVersion, exact rate / slab row
  ids, rowsHash) instead of the rate / slab copy; usedRows stored once (trace.contentUsedRef) in a lossless compact
  form (usedRowsFormat "compact", nulls omitted; expansion hashes to the engine's hashes.content). Version 1 stays
  readable; a version-2 replay resolves the reference and refuses a changed / missing row (fail closed). No
  migration; engine output unchanged.
- Readers: be_snapshot_facts (JSON-path extraction) for preflight, approval hook, fingerprint, ledger, DmfA /
  Belcotax / FinProf totals, payment demo check, parallel import; be_calculation_snapshot deferred (models.py,
  BE column only); undefer where Belgian code loops; freeze_run_templates skips BE in SQL; payslip API through
  be_payslip_view (full used rows, same shape for v1 / v2).
- tests/test_belgium_snapshot_v2.py (6) with the captured version-1 fixture tests/fixtures/belgium_snapshot_v1.json
  (synthetic DEMO; no IBAN / NISS / names).
- Memory (tracemalloc, 500): generate 651 → 236 MiB (0.47 / employee), approve 1,100 → 231 MiB (0.46); preflight /
  DmfA / Belcotax / parallel 642-651 → 4-12 MiB. Process peak at 2,000: 4,323 → 1,435 MiB; marginal 0.39 MiB /
  employee. Snapshot 238 KB → 50 KB. Statements per item flat (view / PDF +1: deferred load).
- Guard: memory ceiling 0.6 MiB / employee (generate, approve) added to tests/perf; ceilings view 4 / PDF 7.
  ZP_BE_SCALE=1: 2 passed. Registry: fresh == stored (an aliased model name hid payslip_items from the scanner —
  fixed by using the real name).

## Block J3 — bulk acknowledge

- `POST /api/payroll/belgium/runs/{run_id}/exceptions/acknowledge-bulk` {items: [{employeeId, code}], reason}: same
  dependencies as the single route (get_current_org_admin + the router's require_be_tenant), same registry policy
  (worker / create / org_admin / tenant / payslip_items). Shared implementation `_be_acknowledge`: one presence read
  (snapshot paths), one write of the approval record, one audit row per item identical to one-by-one; all or
  nothing; duplicates collapsed. The single route now calls the same implementation (one item).
- Screen (BERunPreflightPanel): checkbox per exception, "Select all exceptions (N)", "Acknowledge selected (N)" with
  one reason; one selected row uses the single route; the per-row Acknowledge stays. UI check added
  (be-scaffold-ui-validation: 9 checks); lint clean; vite build passes.
- 2,000 employees, 4,000 exceptions: bulk 2.36 s (3 SELECT + 1 UPDATE + 4,000 audit INSERTs) vs one by one 31.4 s
  (after J2) / 41.4 s (after I2).
- tests/test_belgium_bulk_acknowledge.py (3): bulk == one-by-one (approval record + audit rows), all-or-nothing +
  refusals (other organisation, approved run, malformed / empty / no reason), route authorization identical.
- Registry: only the new route (fresh == stored after regeneration). ORG_ADMIN_GUIDE + runbook playbook updated.

## 2026-11-16 — merge of origin/main and the rollback decision

- origin/main (Belgium PR #161 up to edfec72 + Malaysia, merge revision cf348b09db2b) merged into nikhil (a2eb94c,
  user-approved; no conflicts). Single head cf348b09db2b; registry fresh == stored; Belgium + migration + Malaysia
  tests 883 passed, 4 skipped.
- The J1 rollback proof then FAILED (revert + shim: drift on payroll_runs.my_approval_fingerprint; 13 pin tests):
  main's merge revision builds on the Belgian head and main keeps changing files Belgium touched, so a code-only
  revert cannot stay deployable. **Owner decision: rollback = dormancy + fix-forward; the Belgian schema is
  permanent.** CI rollback-proof steps removed from both workflows; tests/test_belgium_rollback_proof.py deleted;
  belgium_rollback_shim.py / be_rollback_orm_check.py marked SUPERSEDED (kept as tools); DEPLOY_NOTES §4 rewritten
  (4.1 switch off, 4.2 fix forward, 4.3 superseded record).

## Block K0 — self-audit

Scan of belgium*.py, be_*.py, engine/countries/belgium*, engine/jurisdictions/belgium/, the Belgian frontend and
docs/belgium/*.md for TODO / FIXME / "not yet" / NOT_BUILT / stub / placeholder / NotImplementedError, plus the
plan's deliverables (§5 reused tables, §7 decisions D1-D15).

| # | Item | Where | Class |
|---|------|-------|-------|
| 1 | Individual account: a Draft ReportTemplate record only, no content or rendering | belgium_service.seed_be_individual_account_template | Engineering → K1 |
| 2 | 281.10 employee copy: a plain-text rendition, no template | belgium_filing.employee_copy | Engineering → K1 |
| 3 | Holiday certificate (BE-027): no rendering at all | — | Engineering → K1 |
| 4 | Gate evidence: only a reviewed SourceArtifact tag (no status, no rejection, no gate field, no history, no UI) | belgium_service._evidence, belgium_readiness | Engineering → K2 |
| 5 | Owner decisions: state derived from BE-DECISION-* evidence tags; no proposal / decided value / approver / history | belgium_service.owner_decisions, BEOwnerDecisionsTab | Engineering → K3 |
| 6 | Filing payload renderers (canonical payload → official XSD) empty | belgium_filing.RENDERERS | Authority content (G-08 / G-31 / G-33) |
| 7 | Transmission: only UncertifiedAdapter (abstract base raises NotImplementedError) | belgium_filing | Authority (gate G3, D9) |
| 8 | Employee-document labels nl / fr / de: content keys only | content keys (D10) | Translation content + decision G-13 |
| 9 | Release-1 scope exclusions (several lines, non-resident, reductions, benefit in kind, special statuses, contracts / categories outside the signed list) | engine blocks; runbook "Engineering (not built)" | Human decision — DECIDED (G-27); not stubs |
| 10 | BSSC never computed (exception only) | engine | Specialist content (G-06 / G-17, D7) |
| 11 | BE_ENGINE_NOT_BUILT: reserved code, raised nowhere | engine errors.py | None (documented in the runbook) |
| 12 | Payslip header / net-pay labels not yet content-keyed | payslip view | Engineering, small (not in Block K scope) |
| 13 | Stale: unused NOT_BUILT_MESSAGE, belgium_service docstring ("statutory_summary reports NOT_BUILT"), preflight-panel comment ("Dimona placeholder until Block C") | belgium_service.py, BERunPreflightPanel.jsx | Fixed in K0 |

Confirmed for K1-K3: items 1-5 are genuine engineering. Correction: the Block H payslip integration uses NEITHER
template engine (a dedicated Belgian PDF renderer; main's PR #158 payslip templates refuse Belgium), so K1 reuses
payroll_report_templates / payroll_generated_reports (plan §5) with a Belgian renderer, gated by
template_activation_refusal. K2 / K3 need two new tables (SourceArtifact cannot carry status / rejection / decided
value) → one migration on main's head cf348b09db2b.

## Block K1 — employee document templates

- Mechanism: payroll_report_templates (+ components / fields) and payroll_generated_reports (plan §5), the same as
  the other bespoke jurisdiction generators (Mexico); NOT main's PR #158 payslip templates (they refuse Belgium) and
  not the Block H payslip PDF (a dedicated renderer). `belgium_reports.py`:
  - be_seed_report_templates(year): three DRAFT templates (INDIVIDUAL_ACCOUNT reusing BE-INDIVIDUAL-ACCOUNT,
    BELCOTAX_EMPLOYEE_COPY, HOLIDAY_CERTIFICATE) with components / fields (labels = nl / fr / de content keys, D10;
    document versions BE-INDIVIDUAL-ACCOUNT-A, BE-FICHE-COPY-A, BE-HOLIDAY-CERTIFICATE-A). An existing template is
    never changed.
  - Data from committed data only: individual account = approved runs' payslips (gross / net / employer
    contributions as stored) + the committed ledger per payslip (totals by component = ledger sums; ONSS employee,
    work bonus, withholding from the ledger); 281.10 copy = the fiche payload (employee-facing amounts, coding) +
    dependants frozen in the year's committed payslips + lineage (ORIGINAL / CORRECTION / CANCELLATION, corrects);
    holiday certificate = the certificate row (direction, service year, amounts, prior employer, status).
  - Preview (JSON / PDF) now, marked "PREVIEW — TEMPLATE NOT APPROVED" (+ DEMO for demo organisations); generation
    needs an Active template (service.require_active_report_template; activation unchanged:
    template_activation_refusal), supersedes the previous live document, never edits; a holiday certificate is
    issued only when APPROVED (immutable — the table's existing rule).
- Routes: GET /belgium/reports/individual-account, /reports/belcotax-copies/{id}, /reports/holiday-certificates/{id}
  (worker, tenant, org admin + payroll admin), POST /belgium/reports/{type}/generate (worker, org admin), POST
  /super-admin/compliance/belgium/report-templates/seed (platform). Registry: 5 new, no existing route changed
  (explicit dispatch so the call graph sees the data builders → worker class, not tenant_config).
- Tests: test_belgium_reports.py (5): seeded Draft with layout + gate unchanged; individual account from committed
  data (totals = ledger sums), required fields, NISS masked, PDF; 281.10 copy fields, dependants, lineage after a
  correction, non-Belcotax refused; holiday certificate draft preview, issue refused until APPROVED, approved
  immutable, stable rendering; generation refused until Active, then supersedes. Guard: layout numbers registered.
- UI: API only in this block (no screen); the shared Report Templates screens show the seeded templates.

## Block K2 + K3 — gate evidence and decision records

- Migration b7e4c2a9d5f1 be_gate_evidence_decisions (child of main's merge head cf348b09db2b; single head; manifest
  regenerated, one line added): payroll_be_gate_evidence and payroll_be_decisions, platform-level (no organisation,
  no RLS policy — like payroll_source_artifacts); four-eyes CHECKs in the database (decider <> recorder / proposer;
  DECIDED needs a value; SUPERSEDED needs its successor). tests/test_belgium_block_k_migration.py (6).
- K2 `belgium_governance.py`: evidence for G1-G7 against the exact tags the readiness checks require (BE-CONNECTIVITY-*,
  BE-FILING-E2E, BE-SIGNOFF-*, BE-OWNER-*; taken from belgium_readiness) or SUPPORTING (never counted); PENDING ->
  ACCEPTED / REJECTED by another Super Admin, then immutable; history kept. belgium_readiness._be_evidence_check
  counts an ACCEPTED row only for that exact tag (the reviewed-artifact path stays). Every other gate check is still
  derived from data: G7 (owner evidence only) becomes eligible once its five tags are accepted; G6 stays NOT MET
  with accepted sign-offs while the keys / G-21 decision are missing.
- K3: decision records per gap (G-01, G-02, G-06/17, G-11, G-12, G-13, G-16, G-21, G-26, G-30): proposal, sources,
  linked content keys, decided value; PROPOSED -> DECIDED by another person; a later decision supersedes (linked).
  "Import drafted proposals" creates PROPOSED rows from the AI-draft workbook's Decision proposals sheet (8) and the
  gaps register (G-11, G-12); nothing is decided. owner_decisions (readiness) = RECORDED once a DECIDED record exists.
  Engine link confirmed: G-02 feeds be_rounding_onss / _withholding / _holiday and G-26 be_wht_taxable_basis_rule —
  the engine reads only the SIGNED pack rows; a decision changes no row (content four-eyes is not bypassed); the
  record shows whether its rows are signed. A G-26 decision for a different allocation METHOD than the engine's
  proportional allocation would need an engine change.
- UI: Overview → "Evidence" panel per gate (record, accept / reject, history); Owner decisions tab → decision records
  (import proposals, propose, decide by another person, history, linked content state). Lint clean, vite build ok,
  be-console validation 19.
- Routes: 7 new Super Admin platform routes; registry: no existing route changed.
- Tests: test_belgium_governance.py (8). Re-pins (separate commit): alembic head b7e4c2a9d5f1 / count 269, deploy
  drift sets, NZ x5, PL, ZA pending sets gain the two tables.

## Block L1 — the new rollback proof (dormancy)

- tests/test_belgium_dormancy_proof.py (5): full schema (21 payroll_be_* tables) + Belgium off by every setting
  (onboarding unset, canary empty, demo off, identifier keys unset, no Active pack): every /api/payroll/belgium route
  404 (with the Draft pack and Belgian records present); calculate_payroll for BE blocked in standard and simple
  mode and a Belgian preview refused (a refusal type, not a crash); Super Admin console (packs, decisions, joint
  committees, readiness, gate evidence, decision records) 200 with zero INSERT / UPDATE / DELETE; Australia (DB:
  add_payslip_item), Poland and Malaysia (engine dispatcher; Malaysia with its tests' PCB stand-in, PCB not built)
  identical with the Belgian tables empty and full (>= 8 tables holding rows); app startup with no Belgian setting
  (runs tests/test_belgium_production_startup.py). Local: 5 passed.
- CI: "Belgium rollback proof (dormancy)" as the last step of privacy-isolation in both deploy workflows (the only
  rollback proof). DEPLOY_NOTES §4.1 names it as the guarantee; belgium_rollback_shim.py header marked HISTORICAL
  (Malaysia's migrations build on the Belgian ones).
- Limit: Poland / Malaysia are compared through the engine dispatcher, not a full database run (their DB runs need
  their full content fixtures); Australia covers the shared database path.

## Block L2 — payslip label keys; marker rescan (04b30d0, 1bdf227)

- Item 12 closed: `BE_PAYSLIP_LABELS` (frontend bePayslipLines.js) and `BE_PAYSLIP_LABEL_KEYS` (belgium_payslip_pdf.py)
  share one key set — `be.payslip.header`, `be.payslip.net`, `be.payslip.section.{bases,employee,employer,obligations}`;
  the on-screen breakdown renders `data-content-key` on each label. PAYSLIP_EXPLAINER.md no longer says "proposed".
  Pinned by tests/test_belgium_payslip_labels.py (3).
- Rescan (TODO / FIXME / XXX / "not yet" / stub / placeholder / NotImplemented over belgium*.py, be_*.py,
  engine BE files, components/jurisdiction/belgium/, docs/belgium/*.md): one stale comment fixed
  (PREFLIGHT_PENDING). Every other hit is by design or classified content: DEMO placeholders (E4), HTML input
  placeholders, structural NOT NULL placeholder columns, `[PENDING G1]` seed rows, the abstract
  TransmissionAdapter (authority, G3 / D9), BSSC G-17 (specialist, G-06), sector agreement content (specialist),
  and dated historical log lines later resolved (Phase 2 PG RLS — runs in CI; Phase 3A slab entry — add_slab_row
  in 3B). **No further engineering blocks identified.**

## Block L3 — source inbox

docs/belgium/sources/inbox/ holds README.md only — nothing to register; skipped.

## Block L4 — final state

- Alembic: single head `b7e4c2a9d5f1` (`alembic heads` → one line); manifest test passes (chunk 0).
- Route registry: a fresh generation equals the committed registry (0 added / 0 removed / 0 changed, comparing
  without the 4 health routes of the uncommitted main.py — the same 3 known privacy-registry failures below).
- Frontend: `npm test` all scripts pass (be-console 19, be-scaffold 9 checks); `npm run build` passes; the
  Belgian files and every file changed in Block L lint clean. `npm run lint` over the whole repo reports 169 errors
  in 95 files, none Belgian and none touched by Block L (pre-existing elsewhere in the repo).
- Full backend suite, 13 chunks of 40 files (+ the test sub-directories in the last chunk), each chunk on a fresh
  temporary SQLite (PAYROLL_DATABASE_URL from scratchpad safe_env.sh; ZP_TEST_POSTGRES_URL unset, so the
  Postgres-gated tests skip): **10,627 collected = 10,627 executed** (per-chunk collect-only matches every chunk) —
  **10,479 passed, 10 failed, 136 skipped, 2 xfailed.**
- The 10 failures are all known and pre-existing: 5 test_engine_jurisdiction_db_integration (ordering),
  1 test_hong_kong_configuration (configuration CSV), 3 privacy/test_route_registry (health routes of the
  uncommitted main.py), and 1 timing flake, test_communications_dispatch::test_deactivate_organization_response_
  precedes_email_send (passes 3/3 alone and on a full rerun of its chunk; its own comment notes the middleware
  ordering race). The 5 germany_full_business ordering failures of D1 did not occur. Nothing new.

### Closing summary — every phase and block

| Phase / block | Final commit(s) | Delivered |
|---|---|---|
| Phase 0 | 114c2cd, d46478d | Implementation plan, gaps / decisions register, spec + plan errata |
| Phase 1 | 63feb4b, 922491a | Fail-closed scaffold: BE registration, routes 404 unless enabled, calculation blocked |
| Phase 2 | 1215a56, abd5b22 | Database foundation (migration be_foundation, RLS on every tenant table) |
| Phase 3A | 01795d0 | Content model, BE pack reader, Super Admin governance (sign / four-eyes) |
| Phase 3B | 0696bb4 | Governed slab rows (add / retire) and the Super Admin console |
| Phase 4 (in Block A) | 02f4891, 720d74b | A1 identifier vault + statutory setup; A2 applicability resolver and endpoint |
| Phase 5 (in Block A) | 800c464, 8abb230, dab42ae | A3 core engine (bases, ONSS, withholding); A4 organisation / employee screens |
| Phase 6 (in Block B) | 8432510, 23c02ac | B0 decisions G-22..G-29 + migration; B1 sector wages, indexation, working time |
| Phase 7 (in Block B) | 6933789 | B2 holiday pay and absence engines |
| Phase 8 (in Block B) | ed734a1, 38e07bc | B3 run lifecycle, payslip, corrections, SEPA payment |
| Phase 9 (in Block C) | 952284b, 1403aa5, 143175c | C0 migration; C1 Dimona / DmfA / withholding / Belcotax builders, obligations (transmission behind G3) |
| Phase 10 (in Block C) | 77de922, 9f18e28, b97c366 | C2 parallel run, golden checks, readiness gates G1–G7, release |
| Block A | 02f4891 … dab42ae | Phases 4–5 (above) + full-suite reconciliation |
| Block B | 8432510 … 38e07bc | Phases 6–8 (above) |
| Block C | 952284b … b97c366 | Phases 9–10 (above) |
| Block D | 0299909, 1300f95, b9d270f, b2d2858 | Complete verification, hardening review, content intake workbook + bulk signing, handover |
| Block E | 405b93d, ae49748, 5064d57, 1c8fd7a, 92ec1df | AI-drafted content workbook (unsigned), import as Draft rows, reviewer guide, DEMO pack (non-production), authority onboarding drafts |
| Block F | 53b77a8, 1cf3a65, 46fb0f4, fa800d0, 42ac810 | Per-row four-eyes fix, source download list + inbox register, reviewer efficiency, merge plan |
| Block G | — | Not issued (the sequence went from F5 to the main merge a1e4914, then H) |
| Block H | a1e4914, 845dd99, 472e150, a2d31ed, e6ea0b3, d5bf560 | Main merge; Belgian payslip PDF on every render path; deploy rehearsal, production startup test, deploy notes; CI PG teardown fix; staging rehearsal |
| Block I | a5809df, d5369cb, 609ace2, a3e4912, 9351222, e6478fe | Rollback study (shim, later superseded); scale fixes + harness; structured events + ops runbook; user guides; post-deploy setup command |
| Block J | f11b6c2, a267d70, 970ae0d | Rollback proof in CI (later retired); snapshot v2 (pack by reference); bulk acknowledge |
| Block K | b88340e, 6684da5, ddeb2e2, f5fe44d, 38e8ac6, 7e4de5f, 874647a | Merge with Malaysia; rollback = dormancy + fix-forward; self-audit; employee document templates; gate evidence + decision records (b7e4c2a9d5f1); 21 tables |
| Block L | 6be331f, 04b30d0, 1bdf227 and the commit adding this entry | Dormancy rollback proof in CI; payslip label keys; marker rescan; final state |

Engineering is complete. What remains is not engineering: specialist content signing (G1), authority
access and transmission certification (G3), owner decisions recorded through the decision records, and the
release gates G1–G7 met by real evidence.

## 2026-11-16 — source parse run: B1, B2, B3, B5 (ONSS 2026/3)

- Fetched by GET from socialsecurity.be and archived in docs/belgium/sources/inbox/ with a `.meta.txt` each
  (URL, HTTP 200, retrieval date): B1 contributions, B3 BSSC, B5 work bonus (HTML, 2026/3 edition) and B2 the
  official DmfA rate files 2026 Q1-Q4 (ZIP: XML + XSD; plus the .xlsm workbooks). A1-A3 (FPS Finance, Moniteur
  belge) NOT fetched: both sites answer automated requests with a human-verification (CAPTCHA) page.
- `scripts/be_source_inbox.py`: manifest regenerated (11 documents). B1 / B3 / B5 and the four ZIPs ARCHIVED; the
  .xlsm files UNVERIFIED by the owner's rule (only the extraction source is archived). B2 extracted from the ZIP
  XML in memory (no unpacking, lxml without entities / network); cross-checked read-only against the .xlsm sheet
  TB1 (no macro run): 0 differences in every common record, all four quarters.
- Workbook BE_2026_AI_DRAFT.xlsx: confidence HIGH 9 → 20, NOT FOUND 71 → 63 (305 importable rows). New dated
  proposal sheets (not imported): employer base 19.88 % + two fund contributions per quarter, the BSSC 2026/3
  scale, the work-bonus tables (1 Jul / 1 Sep 2026). Engine gaps recorded: BSSC never computed (no key), work
  bonus needs a category dimension and S at 100 %, no wage moderation on the 1.60 %.
- D3 dry run on a fresh LOCAL SQLite copy (canonical seed + registered sources): 264 changes, 0 errors; import
  written, every row still [PENDING G1], pack Draft; nothing signed, no account. Defect found (not fixed, code):
  be_content_workbook._norm stores the code `000` as `0`.
- BELGIUM_REVIEWER_GUIDE.md: counts before / after, sources, conflicts, the 10 examples recomputed to 'net
  before withholding' with sourced ONSS / work bonus / BSSC / employer lines — all 10 still stop at withholding
  (A1-A3). Tests: workbook + content + inbox 35 passed; privacy scan 0 new findings.

## 2026-11-16 — importer fix: leading-zero codes

- be_content_workbook: text columns (textValue, dimension, name, formulaText, version, treatment) are compared and
  written as the exact string, never through Decimal (`000` stayed `0` before); a numeric cell for a code-list key
  is an ERROR ("enter the codes as TEXT"); a stored `0` vs a `000` cell is now a change, so a re-import repairs it.
  Number columns are still normalised.
- Tests (test_belgium_content_workbook.py, +7): leading-zero round trip through import, storage, export and
  re-import for 000, 000,001,010, 015 and 010,015,027,046 (real code shapes from the B2 rate file: 83 of 232
  employer categories, 23 of 117 worker codes start with 0); repair; numeric-cell refusal; numbers still
  normalised. Against the old importer 4 of them fail; with the fix 17 / 17 pass.
- Fresh LOCAL copy re-run: dry run 264 changes, 0 errors; stored be_onss_supported_employer_categories = '000'
  (text). Nothing signed, pack Draft, no account; the real pack untouched.
- Reviewer guide + workbook Instructions carry the employer-base-rate conflict note (24.92 % vs 19.88 %).
  BELGIUM_GAPS_AND_DECISIONS.md gains Block M: M-BSSC, M-WORKBONUS, M-ECWC with their blocked keys.

## Block M-ECWC — the ONSS rate table (structure only; owner decisions 2026-11-16)

- Source B9 archived: ONSS DmfA glossary 2026/3 (complete PDF, sha256 b8d7f2b2…, reference ZP-BE-SRC-b8d7f2b2b985).
  Zone 00083 "type de cotisation" (p. 38): with the contribution worker code it identifies the contribution, whether
  it is due and its rate; the allowed values per code are in annex 3 (p. 292).
- Migration `e9c4b7a2d6f3` (single head, additive): four platform tables (`payroll_be_onss_rate_files`,
  `payroll_be_onss_rates`, `payroll_be_onss_code_combinations`, `payroll_be_onss_type_rules`; codes TEXT, four-eyes
  CHECKs) and six columns on `payroll_be_employer_registrations` (closure-fund sector, workforce class, wage-moderation
  status — UNKNOWN by default — each with an evidence reference). 25 Belgian tables (19 tenant + 6 platform).
- belgium_onss_rates.py: register an ARCHIVED quarterly rate ZIP (checksum verified; every record loaded as
  REFERENCE) → attest authenticity (another Super Admin; checksum re-verified) → mark the supported subset live
  (codes must be in the pack's code lists) → sign each row / combination (not the registrar, not who made it live).
  Type rules: add → sign (another person). Draft packs only. 10 Super Admin routes (platform, super_admin only).
- Engine (engine/jurisdictions/belgium/onss_table.py): `be_onss_employer_base_rate` and `be_onss_fund_contributions`
  signed `RATE_TABLE` read the table by (employer category, worker code, ContributionType, quarter); SLAB_ROWS keeps
  the EC x WC band path; a mix blocks. A row is used only when the file is ATTESTED and the row SIGNED. Every type
  comes from a signed rule over the worker's PAY_100 / PAY_108 basis and the employer facts (UNKNOWN or missing
  evidence blocks); none / ambiguous / pending rules block; NOT_DUE skips a combined code. Flat amounts, quarterly
  minimums and personal shares on combined codes block (not built). The table is frozen with the payslip.
- Tests: test_belgium_onss_rate_table.py (25: unsigned row in a signed file blocks; missing fact / evidence blocks;
  809 across sector x workforce x moderation -> 0 / 2 / 4 / 5 / NOT_DUE; four-eyes; text codes; REFERENCE never
  reaches the engine) and test_belgium_block_m_migration.py (6). SYNTHETIC rates only — the real B2 rates are NOT
  imported as live content (reference-only decision).
- Found while testing: the pushed parse-run commit 78a8fd5 broke the DEMO seed (2 demo tests, 1 observability
  test fail on 884f656): sourced rows with only a proposed text were taken as drafted values, and the dated band
  proposals were read without their windows. Fixed in belgium_demo.py (separate commit).

## Block M-ECWC follow-up — Decision 1: rate-table versioning independent of the pack lifecycle (2026-11-16)

- Owner decision: a new quarter's ONSS rate file is registered, attested and signed even when the pack is Active;
  no new pack version. belgium_onss_rates no longer refuses non-Draft packs (rate files, live subset, type rules);
  the pack must still be Belgian. The only gates stay the file attestation and the row / combination / rule
  signing (four-eyes each).
- Because several quarters now coexist on one pack: a file's window must lie inside its own published quarter
  (header <Quarter>, e.g. 20271 -> 2027-01-01 .. 2027-03-31) and windows on one pack never overlap, so the pay date
  picks exactly one file (one file per pack and quarter was already unique).
- Tests (+3, SYNTHETIC rates): Q3 2026 and Q1 2027 files registered, attested and signed while the pack is Active;
  the engine lookup picks the quarter of the pay date (BASE 33.30 at 3.33 % in August 2026, 77.70 at 7.77 % in
  February 2027; no file for November 2026 -> no table, the engine blocks); attestation / signing four-eyes still
  refuse on an Active pack; a window outside its own quarter is refused. Against the previous service the new
  tests fail ("BE-PAYROLL-2026 is Active: … Draft pack only", window not refused).
- Production verified by the owner before this change (main 9735dca deployed): RLS on the 19 organisation tables,
  none on the platform ONSS tables; 0 rows in every payroll_be_* table in system mode (orgs_visible = 49); no Active
  Belgian pack; no Belgian registry row. The skipped "Post-deploy privacy smoke" is the configured HP-10 condition
  (secret ZP_SMOKE_BASE_URL unset) — an open control owned by the repository admin / ZP-PRIV owner, not Belgian.

## 2026-11-16 — A1 parse run: withholding from 1 January 2026 (B10 + B11)

- Inbox: two documents downloaded by the owner from finances.belgium.be — B10, the official Annex III to the Royal
  Decree of 11 December 2025 (rules for income paid from 1 Jan 2026, 44 p.), and B11, the FPS Finance Formule-clé
  ESS-SR/2025-0928 (from 1 Jan 2026, 31 p.). Archived unchanged (sha256 b7c7d3af… / fca89350…). All 35 regular-pay
  figures are identical in both. No 2026 amendment in either; B11 n° 2 warns the formula may be adapted during 2026.
  A2 (from 1 Aug) and A3 (from 1 Nov) remain NOT FOUND.
- Workbook: withholding NOT FOUND 19 -> HIGH 8 / NOT FOUND 11. be_rounding_withholding = CENT_HALF_UP (importable,
  n° 12). Scale (n° 28, 31-34), family reductions (n° 38-41), fiscal work bonus (n° 46), exceptional / holiday pay
  (n° 53-57) and overtime (n° 45) on the new proposal sheet — engine gap M-WHT (the engine applies one band to the
  monthly pay; the law annualises and applies the annual scale). Period strategy and taxable basis as proposed text
  (no vocabulary).
- Fresh LOCAL copy: dry run 265 changes, 0 errors; import written; every row still [PENDING G1]; pack Draft.
- The 10 worked examples now reach FULL NET PAY for July 2026 (the month every archived source applies); August 2026
  onwards still stops at withholding.

## 2026-11-17 — A2 / A3 parse run: the 2026 amendments to Annex III (B12 + B13)

- Inbox: two decrees saved by the owner from the official gazette site (ejustice.just.fgov.be; NL browser prints) —
  B12 = A2, Royal Decree 24 Jul 2026 (numac 2026005690, published 30 Jul 2026, sha256 49b8cd3a…), B13 = A3, Royal
  Decree 27 Sep 2026 (numac 2026007167, published 2 Oct 2026, sha256 f8947967…). Meta files written (official: yes);
  manifest regenerated (16 documents). Saved unchanged under their downloaded names.
- Findings: fiscal work bonus component B **63 %** from 1 Aug 2026 (A2 art. 4; component A unchanged). The scale
  (n° 31) is **not** amended; A3 sets new values from 1 Nov 2026 (exempt amount 11,550 / 3,089.63, marital-quotient
  cap 11,780 or 12,790, 6,179.26, children table, 648 / 636, n° 54 limits, n° 4.2 threshold). Method steps unchanged;
  two NEW conditions in A3 (spouses' age for the cap; spouse's study-grant income). A2 art. 2 (overtime 180 h) is
  **retroactive to 1 Jan 2026**; art. 3 from 1 Apr 2026.
- Workbook: proposal sheet renamed 'Annex III 2026 (proposal)' with effectiveFrom / effectiveTo / status columns;
  B10 rows dated (29 in force all year, 27 superseded from 1 Nov, 1 from 1 Aug, 1 retroactively); 35 new A2 / A3 rows
  (29 from 1 Nov). Withholding HIGH 8 / NOT FOUND 11 -> **HIGH 9 / NOT FOUND 10** (be_wht_annex3_amendment_2026).
  Secondary-source notes replaced by the decree text. Not archived: the FPS Finance key formulas for 1 Aug / 1 Nov.
- The 10 July 2026 examples: **figures unchanged** (A2 art. 4 and A3 start after July); Assumption 4 now reads 180 h
  and the 29°/1 exception. Decree-only sensitivity added (reviewer guide §3.0a).
- Readiness report: the 'SOURCE_NOT_ARCHIVED' blocker for A2 / A3 replaced by KEY_FORMULA_NOT_ARCHIVED (owner) and
  the new specialist questions SQ-WHT-3 (retroactive overtime limit, 29°/1) and SQ-WHT-4 (age-based cap, study grant).
- Fresh LOCAL copy: dry run 265 changes, 0 errors; B12 / B13 registered ARCHIVED; every row still [PENDING G1]; pack
  Draft. Registry diff 0 changed. Engine work (M-WHT / M-WORKBONUS / M-BSSC) still ON HOLD.

## 2026-11-17 — Phase closing: production deploy of PR #168 verified

Belgium deploy PR #168 (merge 2e45e202) confirmed green and verified dormant in production, 2026-11-17. Checks:
(1) Super Admin console loads correctly, shows expected empty state — no Belgian pack exists; (2) system-mode
row-count query confirms 0 rows across all checked payroll_be_* tables, verified under genuine full visibility
(orgs_visible=49); (3) no stray/misspelled Belgian pack exists under any country/pack_id variant. Privacy smoke step
skip confirmed as the known HP-10 gap, unrelated to this change.

Evidence:
- GitHub Actions on 2e45e202: "Build Zoiko Payroll Frontend" 44014178210 success (04:03 UTC); "Deploy Zoiko Payroll
  Backend" 44014178197 success (04:39 UTC) — test, privacy-isolation (incl. Belgium PostgreSQL RLS round trip and
  rollback/dormancy proof) and deploy jobs green; single Alembic head e9c4b7a2d6f3 (no migration in this PR).
- Console (owner, production): /super-admin/compliance/belgium is BECompliancePage — the shared JurisdictionLayout
  with the Belgium tabs, which appear only once a pack is selected; with no BE pack the page correctly shows "No tax
  packs for this jurisdiction yet". The live bundle /assets/index-Dal7WkNG.js contains the Belgium console
  (including "Activation readiness" and be-readiness-verdict).
- Pack query (owner, production): 0 rows in payroll_jurisdiction_packs matching pack_id 'BE-%' or jurisdiction_country
  'BE%' / 'Belg%'. Nothing seeds a Belgian pack in production (seed_belgium_canonical_packs refuses non-local
  databases); creating the real Draft pack there is a governed owner decision, not part of this phase.
- Privacy smoke: step "Post-deploy privacy smoke" skipped because HAS_SMOKE is false (secret ZP_SMOKE_BASE_URL unset,
  backend-deploy.yml lines 106 / 202), identical to the previous deploy (e3c2c722, run 43872507564); workflow file
  unchanged since 6be331fc. Open control HP-10, owned by the repository admin / ZP-PRIV owner.
- Still open after this phase: specialist answers SQ-WHT-1..4 (all blocking, G1); FPS Finance key formulas for
  1 Aug / 1 Nov 2026; golden source G-34; engine items M-WHT / M-WORKBONUS / M-BSSC on hold until the specialist and
  Venu respond.
