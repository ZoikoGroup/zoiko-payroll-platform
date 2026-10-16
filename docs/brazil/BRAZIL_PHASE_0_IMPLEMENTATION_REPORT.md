# Brazil (BR) — Phase 0 Implementation Report

Phase 0 go-ahead: 2026-10-15. Branch: `venu` (fast-forwarded to `origin/venu` `d59508c` before any change).
Status: **code complete, verification pending** (see §4). Not committed, not pushed. No database touched.

## 1. What Phase 0 guarantees

- **No Brazilian payroll is calculated anywhere.**
  - `brazil.calculate` raises `BR_ENGINE_NOT_CERTIFIED`.
  - The `calc_inputs` hook raises the same.
  - Simple mode raises `BR_SIMPLE_MODE_UNSUPPORTED`.
  - A run with Brazilian payslips cannot be approved, authorized or paid (`BR_RUN_NOT_SUPPORTED`).
  - All of these are handled 4xx errors.
- **No Brazilian pack, template or registry row can be activated or opened.**
- **No other jurisdiction changes.**
  - Hook loops in `service.py` reach Brazil only for runs that carry Brazilian payslips.
  - `retention_settings` answers inertly for every report download.
- **Brazil is visible as a schema** (`/api/jurisdictions/tax-schemas`) but **cannot be registered**: it is absent from `REGISTRATION_COUNTRIES`.

## 2. Changes

### Backend — new files

| File | Content |
|---|---|
| `app/modules/payroll/brazil_service.py` | 13 hooks, fail-closed (Mexico pattern) |
| `app/modules/payroll/brazil_router.py` | `GET /api/super-admin/compliance/brazil/readiness` (Super Admin only) |
| `app/modules/payroll/engine/jurisdictions/brazil/__init__.py` | Package docstring only |

### Backend — modified files

| File | Change |
|---|---|
| `brazil_schemas.py` | Adds `BRGateState`, `BRReadinessResponse` (draft schemas kept) |
| `brazil_content.py` | Adds `SPEC`, `PACK_STATUS`, `BR_2026`, `SOURCE_REFERENCES` S1–S20 and `GATES` G1–G8, verbatim from the spec. No statutory value changed. |
| `engine/countries/brazil.py` | `calculate()` blocks; draft body kept as `_calculate_draft()`; `BrazilCalculationError` removed |
| `engine/resolver.py` | BR simple-mode block raises the handled error; `brazil_inputs` parameter + splat |
| `engine/base.py` | `brazil_organization_id`; corrected the field comment (no "conservative defaults") |
| `engine/standard.py` | Comment only |
| `jurisdiction_hooks.py` | `"BR"` module |
| `core/jurisdiction.py` | `JURISDICTION_TAX_SCHEMAS["BR"]`, name maps |
| `service.py` | Currency maps (`R$`, `BRL`) |
| `main.py` | Router mount |
| `models.py` | `PayslipItem.br_calculation_snapshot`; `uq_br_employer_org`; establishment CNPJ unique per employer (`uq_br_establishment_employer_cnpj`, was platform-wide); profile CHECKs for category (101/103) and weekly hours (0 < h ≤ 44) |
| `alembic/versions/b7a1c9e3d5f2_…` | Rewritten — see the gap assessment §4. Single head `b7a1c9e3d5f2` (static check). |

### Frontend

- `components/jurisdiction/CountryFlag.jsx`: Brazil flag.

### Tests

| File | Change |
|---|---|
| `test_brazil_scaffolding.py` (new) | Mirror of `test_mexico_scaffolding.py` for BR: registry, schema patterns, currency, content identifiers, error class, dispatch, blocking in every mode, hook contract, refusals, registry gate, retention, readiness route, shared summary route |
| `test_brazil_phase1_foundation.py` | All `app.*` imports moved inside tests; uses conftest's `db` fixture (was a module-level `from app.database import Base` — the import pattern behind the live-DB leak incident). New constraint tests. INSS maximum as a strict xfail (BR-K1). |
| `test_brazil_phase2_engine.py` | Integration tests route BR to `_calculate_draft` via `monkeypatch` (production dispatch blocks). Known-wrong expectations replaced by strict xfails asserting the correct values (BR-K1 ×3, BR-K2 ×2), plus a test pinning the BR-K1 symptom. Simple-mode test uses the handled error. |

### Docs

`docs/brazil/`: implementation plan, Phase 0 gap assessment, this report, out-of-scope defects.

## 3. Not done in Phase 0 (by design)

- Statutory values — Phase 1.
- Registration — Phase 11.
- Any UI page — Phases 2–6.
- Merging `main` (Mexico) — awaiting a go-ahead.
- `extracted_doc_preview.txt` stays untracked. The spec `.docx` is not yet in `docs/brazil/`.

## 4. Verification

| Check | Result |
|---|---|
| Alembic heads (static parse of `versions/`) | single head `b7a1c9e3d5f2` |
| `py_compile` of the migration and all 17 changed/new Python files | OK |
| Test database target (checked before every run) | `sqlite` throwaway file in the session scratchpad (`PAYROLL_DATABASE_URL` override) |
| `python -c "import app.main"` | OK |
| `pytest` — the three Brazil files | 77 passed, 9 xfailed (exactly the strict known-defect markers: BR-K1 ×4, BR-K2 ×2, BR-K10 ×3) |
| `pytest` — full suite | 6004 passed, 1 failed, 39 skipped, 11 xfailed (0:20:25). The single failure is `tests/test_alembic_migration_manifest.py::test_no_migration_deleted_or_renamed_against_origin_main` (pre-existing branch divergence: `venu` lacks `5d2c8f1a7b3e_mx_foundation_m1.py` from `origin/main` because main was not merged into venu; this is expected and not caused by Brazil changes). All 4 alembic test baselines were updated and the Brazil migration registered in the manifest. |
| Production `alembic_version` (read-only SELECT, approved 2026-10-16) | `f4b8d2a6c9e1`; 0 `payroll_br_*` tables — the Brazil migration was never applied anywhere |
| `npm run check:undefined` | OK — 468 files, no undefined names |
| `npm run build` | OK |
| Migration upgrade/downgrade/upgrade on a throwaway local Postgres | pending (local Postgres 17 running; credentials not available in this environment; will run on go-ahead with credentials) |
