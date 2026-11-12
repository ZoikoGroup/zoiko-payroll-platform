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

- Commit: see the A2 commit (`feat(belgium): block A2 applicability resolver`); hash recorded in the A3 entry.
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
