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

- Commit: see the A1 entry appended after the commit.
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
