# Belgium payroll jurisdiction (ZP-BE-ENG-001) — engineering complete, dormant

## Summary

Adds Belgium as a fail-closed payroll jurisdiction following the Poland gen-2 pattern: employer / worker
statutory records with an encrypted identifier vault, an applicability resolver, the calculation engine
(withholding, ONSS, wages and working time, holiday pay, absence), the run lifecycle with four-eyes commit,
corrections and SEPA payment, authority filings (Dimona, DmfA, FinProf, Belcotax 281.10) with obligations and
reconciliation, parallel-run acceptance, golden certification and the G1-G7 release gates, plus a content
intake workbook for the Belgian specialist.

**Belgium stays dormant.** It is not in `REGISTRATION_COUNTRIES`; every `/api/payroll/belgium` route answers
404 unless `BE_TENANT_ONBOARDING_ENABLED` is on or the organisation is on `BE_CANARY_ORG_IDS`; the seeded pack
is Draft with every row `[PENDING G1]`; no statutory value is in code; the engine blocks with a named reason
until content is signed; the registry row stays PLANNED while any gate is red. Merging this changes nothing
for any existing customer.

## Architecture

- `belgium_service.py`: the 13 jurisdiction hooks, statutory records (versioned, four-eyes), resolver,
  calc inputs, run lifecycle hook (preflight, G-18 four-eyes and commit idempotency, ledger at commit G-29),
  corrections, payslip snapshot. `be_identifiers.py`: AES-GCM vault (own keyring). `be_org_router.py`: the
  organisation API (dormancy guard, own org only).
- Engine: `engine/countries/belgium.py` orchestrates `engine/jurisdictions/belgium/*` (pack reader with
  signed-row-only access, restricted formula grammar, applicability, bases, ONSS, withholding, wages, working
  time, holiday, absence, declarations).
- `belgium_payment_service.py` (pain.001 via the existing bank_export, unchanged); `belgium_filing.py`;
  `belgium_parallel.py`; `belgium_golden.py`; `belgium_readiness.py`; `be_content_workbook.py`;
  `be_super_admin.py` (governed signing console).
- Content: `engine/countries/belgium_content.py` (catalogue, vocabularies, spec-proposed labels only).
- Frontend: Belgium Compliance Centre (setup, records, filing centre, parallel cycles), run preflight / payslip /
  payment panels, Super Admin Belgium console (rows, slabs, joint committees, signing status with workbook and
  bulk sign, overview with gates and golden certification).

## Migrations (in order; single head 8a1f5ef9fa5d)

| Revision | Name | Down revision | Content |
|----------|------|---------------|---------|
| 1d76678ef1a1 | be_foundation | efc56f3235e2 | 9 Belgian tables (vault, access events, registrations, units, profiles, schedules, classifications, declarations, ledger) + 2 nullable shared columns (payslip_items.be_calculation_snapshot, payroll_runs.be_approval_fingerprint); RLS |
| 2943a0490b5b | be_absence_holiday_payment | 1d76678ef1a1 | 5 tables (absence episodes, holiday certificates, payment batches / items, component mappings) + decision columns on 3 Belgian tables; RLS |
| 8a1f5ef9fa5d | be_filing_parallel | 2943a0490b5b | 5 tables (filings, obligations, reconciliation variances, parallel imports / differences); RLS |

All additive, literal names, idempotent both ways, listed in MIGRATIONS_MANIFEST.txt, deploy drift filter
explains every object.

## Shared-file hunks

All additive and keyed to Belgium; listed and reviewed in `docs/belgium/BELGIUM_SECURITY_REVIEW.md` §3
(config flags, jurisdiction aliases, bank routing, employee validation, engine context / dispatch, tax
resolver registry tuple, jurisdiction hooks, router include, service.py opt-in tuples and `country == "BE"`
branches, models, Super Admin routes, route registry / overrides, manifest, CI workflows, frontend BE branches).
None flagged.

## Re-pin commits (exact-list pins only, standing rule)

- `922491a` test: re-pin exact country lists for BE (SG snapshot, SG F2 opt-in, MX governance tuples, MX dormant strategies, MX bank routing)
- `abd5b22` test: re-pin alembic head / table lists for BE
- `e4065bc` test: re-pin alembic head, revision count and drift-filter pending sets for BE Block B
- `7d1f735` test: re-pin NZ migrations drift-filter pending tables for BE Block B
- `b188ee0` test: re-pin alembic head, revision count and drift table sets for BE block C
- (also `63feb4b` carried one BE entry in the Mexico hook-module test)

## Test evidence

- Full backend suite (Block D1, end of phase): **10,087 collected = 10,087 executed** — 9,937 passed, 14
  failed, 134 skipped, 2 xfailed. The 14 failures are all known and pre-existing, none Belgian: 5
  test_engine_jurisdiction_db_integration (ordering), 5 test_germany_full_business_acceptance (ordering), 1
  test_hong_kong_configuration (CSV), 3 tests/privacy/test_route_registry (health routes from an uncommitted
  local main.py — not in this branch). Per-batch table in `docs/belgium/PROGRESS.md`.
- Belgium tests after D2-D4: 20 files, 521 passed, 3 skipped (the PostgreSQL round trips, CI only).
- Frontend: lint clean on Belgian files; `npm test` all 9 scripts pass; build passes locally.
- Route registry: regenerated after every sub-step; no existing route's class, roles or data categories changed.
- Environment: every local run used a fresh scratchpad SQLite (`PAYROLL_DATABASE_URL`), `ZP_TEST_POSTGRES_URL`
  unset, Python 3.11.

## Merge gates (required before merge)

1. CI `privacy-isolation` job (PostgreSQL 15): RLS of every Belgian table plus the new Belgium migration round
   trips (last step of the job) — never run locally.
2. CI `test` job on Python 3.12 (full suite).
3. CI frontend build.
4. Two-heads check against main at merge time (head must remain single).

## Rollback

- Behaviour: Belgium is dormant; to close it again set the registry row to PLANNED, `BE_TENANT_ONBOARDING_ENABLED=false`
  and clear `BE_CANARY_ORG_IDS` (`docs/belgium/BELGIUM_ACTIVATION_RUNBOOK.md` §3).
- Schema (only if a deploy fails before any use), newest first:
  `alembic downgrade 2943a0490b5b` (drops the 5 Block C tables) → `alembic downgrade 1d76678ef1a1` (drops the 5
  Block B tables and the decision columns) → `alembic downgrade efc56f3235e2` (drops the 9 foundation tables and
  the 2 shared columns). Each downgrade removes only its own objects (tested on SQLite; PostgreSQL in CI).

## Docs

`docs/belgium/`: BELGIUM_IMPLEMENTATION_PLAN.md, BELGIUM_GAPS_AND_DECISIONS.md, PROGRESS.md,
BELGIUM_COVERAGE_MATRIX.md, BELGIUM_ACTIVATION_RUNBOOK.md, BELGIUM_SECURITY_REVIEW.md,
BELGIUM_SPECIALIST_PACK.md, BELGIUM_AUTHORITY_ONBOARDING.md, PR_DESCRIPTION.md (this file).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
