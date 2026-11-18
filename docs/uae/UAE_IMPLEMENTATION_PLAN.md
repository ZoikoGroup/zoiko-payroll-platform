# United Arab Emirates (AE): Implementation Plan

Status: implemented (ZP-AE-ENG-001 v1.0). The earlier P1/P2 gate design was
replaced by the owner's simplified decision: the UAE is an ordinary payroll
jurisdiction, like Jamaica, with statutory values held in the Active canonical
rate pack.

## Scope

- Jurisdiction code `AE`, display name "United Arab Emirates", aliases `UAE`,
  `U.A.E.`, `Emirates`. Currency AED.
- Registration opens once an Active AE canonical pack with rates exists. There
  is no service registry row, dormancy flag, AE tenant setting, signing tab,
  evidence upload, second reviewer, or AE-specific approval gate.
- Pack `AE-PAYROLL-2026` holds all statutory values. Super Admins edit rates in
  the normal Rates tab; the platform's existing second-Super-Admin approval
  before Activate still applies.
- The calculator reads only rate-map values effective on the pay date. Missing
  values stop that employee with a named block reason; no silent defaults.
- No monthly income-tax / PAYE line. No WPS SIF generation, GCC home-country
  rates, part-time gratuity, leave encashment, or deduction caps in this scope.
- DIFC and ADGM are blocked by the employee's region; adding their own schemes
  needs a later spec and pack rows.

## Calculation rules

- Pension: GPSSA Law 7 / Law 57, ADPF in-service / new member and GCC extension
  read employee/employer/government shares, salary floor and cap from the pack.
  Government support applies only when eligible and is capped at the statutory
  limit; only the net employer cash pension is an employer cost line.
- Gratuity: expatriates use traditional days-per-year bands with a 24-month
  Total-Wage cap, or the savings-scheme subscription bands. Total Wage for the
  cap is Basic Wage + HRA + special allowance + other allowance; overtime is
  excluded. Unpaid absence days come from the payslip's attendance input.
- Overtime: statutory hourly minimums are a breakdown only; the overtime amount
  is already contributed by the ordinary payslip calculation.
- Emirati minimum: the AED 6,000 floor applies to UAE nationals only from the
  effective date carried by its pack row. Expatriates are not blocked.
- Rounding: half-up to 2 decimals (fils) per line.

## Files

- `backend/app/modules/payroll/engine/countries/uae.py` — orchestrator.
- `backend/app/modules/payroll/engine/jurisdictions/uae/` — errors, pack readers,
  pension, gratuity and overtime modules.
- `backend/app/modules/payroll/engine/countries/uae_content.py` — 27 rate rows.
- `backend/scripts/seed_uae_canonical_pack.py` — Draft pack seed.
- `backend/alembic/versions/ad01fc67ce44_ae_foundation.py` — one nullable
  `payslip_items.ae_calculation_snapshot` column.
- `backend/app/modules/payroll/employee_validation.py` — regular AE compliance
  fields; no duplicate UAE tables.
- `frontend/src/pages/JurisdictionCompliance/AECompliancePage.jsx` and
  `frontend/src/pages/ReportTemplates/AEReportTemplatesPage.jsx` — Super Admin
  workspaces on the shared layouts.
- `frontend/scripts/ae-scaffold-ui-validation.mjs` — front-end wiring checks.

## Verification

- `python -m pytest tests/test_uae_scaffold.py tests/test_uae_migrations.py
  tests/test_uae_calculator.py -q` — 48 passed.
- Targeted migration/drift tests — 211 passed, 1 skipped.
- `npm test` — all validation scripts pass, including UAE UI validation.
- `npm run check:undefined` — 738 files, no undefined names.
- `npm run build` — succeeds.
- `npm run lint` still fails on pre-existing repository-wide `react-hooks`
  and `no-useless-catch` findings; none are in the UAE-changed files.
