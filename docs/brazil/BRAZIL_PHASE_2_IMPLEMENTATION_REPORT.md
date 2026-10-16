# Brazil (BR) — Phase 2 Implementation Report (Super Admin)

Date: 2026-10-16. Branch: `venu` (on top of `2ded87b`, the merge of `origin/main` / Mexico 0–4b). Not pushed.

## 1. What Phase 2 delivers

A read-only Super Admin workspace for Brazil at `/super-admin/compliance/brazil`, the governed rates/slabs editor at `/super-admin/statutory-rates/brazil`, and the shared report-template lifecycle at `/super-admin/report-templates/brazil`. Nothing in Phase 2 can change a statutory value or calculate a payslip.

### Backend — `/api/super-admin/compliance/brazil` (`brazil_router.py`, Super Admin only)

| Route | What it does |
|---|---|
| `GET /organizations` | Organisations with Brazilian employees or a Brazil employer profile |
| `GET /employees?org_id=` | That organisation's Brazilian employees. `org_id` is required (422 without it, 404 if unknown); there is no default organisation |
| `GET /pack-rows?rule_type=&on=` | Canonical rows of the **Active** BR tax pack in force on `on`, for one of `BR_INSS_BAND`, `BR_IRRF_TABLE`, `BR_IRRF_REDUCTION`, `BR_MIN_WAGE`, `BR_SAL_FAMILIA`, `BR_FGTS_RATE`, `BR_CPP_RATE`. Always `editable: false`; organisation copies and Draft packs never show; no POST (405) |
| `GET /rubric-catalogue[?org_id=]` | The canonical eSocial Table 03 catalogue plus the content hash. With `org_id`, that organisation's rows are appended, tagged `source: organization`. Always carries the "codes unverified (D6 / BR-K3)" note |
| `GET /fpas-table` | `available: false` until Tabela 04 data is supplied (D6) |
| `GET /gates`, `GET /readiness` | G1–G8 states (all OPEN) and the readiness document |
| `POST /golden-check` | Runs the shared golden certification for BR. With only `br_golden/README.md` it records `NO_REAL_CASES`, which the BR activation gate never accepts as a pass |

Governance inherited from the shared pack lifecycle (opted in for BR in `service.py`):

- four-eyes: the approver is never the activator, and self-approval is refused
- refusals are audited
- the pack transition graph is enforced
- a linked Source Evidence artifact is required
- a golden run that reports PASS is required

### Frontend

- `BRCompliancePage`: an explicit organisation picker and these tabs, all read-only:
  - INSS employee bands, IRRF table, IRRF 2026 reduction (Law 15.270/2025), minimum wage, salário-família, FGTS, CPP
  - rubric catalogue, FPAS / Tabela 04
  - readiness G1–G8, golden vectors
- `BRStatutoryPage` / `BRReportTemplatesPage`: thin wrappers over the shared layouts.
- Routes in `App.jsx`, route maps, the `superAdminService` BR block, Test Certification and Engine Fallback entries, labels, flag.

## 2. Fixes made in this phase

- **One content module.** `modules/payroll/brazil_content.py` (an identical duplicate) was removed. Engine, service, router and tests now all read `engine/countries/brazil_content.py`. Rubric seeding moved to `brazil_service.seed_brazil_statutory_content`. This resolves the split brain noted in the status review.
- **Tab titles corrected:**
  - "INSS bands" holds the employee bands only; employer CPP and RAT are separate.
  - The *parcela a deduzir* belongs to the IRRF table; the reduction tab is the Law 15.270/2025 relief.
- **Golden tab:** a `NO_REAL_CASES` run now says "no vectors yet — not a pass" instead of "every vector passed".
- **Rubric tab:** the canonical catalogue shows without an organisation, a Source column distinguishes canonical from organisation rows, and the unverified-codes warning is displayed.
- **Tests:** new `tests/test_brazil_router.py`:
  - every route Super-Admin-only
  - explicit organisation scoping
  - pack rows read-only, Active-only, canonical-only and date-windowed
  - catalogue with and without an organisation
  - FPAS reported as unavailable
  - gates all open
  - golden check records `NO_REAL_CASES`

## 3. Open (not Phase 2 work, or blocked)

| Item | Blocked on |
|---|---|
| Pack-backed tabs show "No Active Brazil pack" | Phase 1 seed (needs saved, VERIFIED official sources — D6) |
| FPAS / Tabela 04 rows | D6 |
| Brazil employee validator active, while Mexico keeps its validator dormant until onboarding | Phase 3/4 (no Brazilian employer can register, so it is unreachable today) |

## 4. Verification

| Check | Result |
|---|---|
| Brazil + Mexico + Alembic + snapshot + Singapore F2 tests (throwaway SQLite, local target confirmed) | 473 passed, 12 skipped, 9 xfailed (BR-K1/K2/K10 strict markers) |
| `npm run check:undefined` / `npm run build` | 506 files clean / OK |
| Full suite | see the commit message |
| Browser check (2026-10-16, Playwright + Chromium) | Pass — details below |

### Browser check

**Why it ran locally.** It was **not** run against production. App startup there is not read-only: it seeds reference content and starts the trial, dunning, token-cleanup, assisted-access, assist and BWM schedulers with `run_now=True`.

**Setup:**
- backend on `127.0.0.1:8000` with `PAYROLL_DATABASE_URL` pointing at a throwaway SQLite file
- frontend on `127.0.0.1:5174` with `VITE_API_BASE_URL=http://localhost:8000`
- synthetic data: a local Super Admin, "Local Brazil Test Ltda" with one Brazilian employee and one organisation rubric, and an Active `BR-LOCAL-TEST-2026` pack holding four *synthetic* INSS rows

**Results:**
- Login works and lands on the Super Admin dashboard.
- `/super-admin/compliance/brazil` renders. The picker lists only the organisation with Brazil payroll.
- With the pack selected, all 11 Brazil tabs open with and without an organisation:
  - INSS bands lists exactly the 4 rows of the Active pack, read-only, with the corrected title.
  - The rubric catalogue shows the "codes unverified (D6, BR-K3)" warning and 14 canonical rows; with the organisation selected, it adds `ORG_BONUS` as `organization`.
  - Running the golden check shows "NO_REAL_CASES — 0 / 0 passed … this is not a pass".
- `/super-admin/statutory-rates/brazil` and `/super-admin/report-templates/brazil` render.
- No error from any Brazil endpoint.

**Known local-only noise:** the only failures were two 500s from `/api/super-admin/dashboard/charts`. It uses Postgres `date_trunc`, which SQLite lacks — an artefact of the local database, not of Brazil.
