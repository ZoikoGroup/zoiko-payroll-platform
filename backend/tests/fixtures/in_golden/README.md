# India (CBDT/EPFO/ESIC/state PT/LWF) golden-test fixtures

ZP-TAX-IN-2026-27-001 §20 ("Test Lab")/§21 (golden test IDs), gap-closure
Phase F (2026-09-11) — generalizes the UK/Canada-only harness in
`hmrc_golden_harness.py` to also run India cases, the same way Canada's
`cra_golden` fixtures did in an earlier phase.

## What's here today

Seven real (non-underscore-prefixed) cases, each mapped directly to one
of the doc's own §21 golden test IDs and derived from either the doc's
own worked numbers or the engine's real seeded statutory data
(`hardcoded_defaults.py`), then cross-checked by running the actual
production engine (`build_context`/`calculate_payroll`) at authoring
time:

- `new_regime_gross_106250_full_rebate.json` — IN-TAX-001 (New Regime,
  Section 87A rebate fully cancels tax at the rebate-limit boundary).
- `epf_ceiling_gross_20000.json` — IN-EPF-001 (EPF wage base capped at
  the ₹15,000 statutory ceiling).
- `esi_gross_20000.json` — IN-ESI-001 (ESI employee/employer
  contribution at 0.75%/3.25%).
- `karnataka_pt_gross_30000.json` — IN-PT-KA-001 (Karnataka flat-bracket
  Professional Tax).
- `maharashtra_pt_male_gross_12000_february.json` /
  `..._march.json` — IN-PT-MH-001 (Maharashtra's gender-differentiated,
  February-adjusted Professional Tax bracket), both the February and a
  non-February month, since the doc's own single test ID actually
  specifies two distinct expected figures depending on the month.
- `chennai_half_year_pt_gross_15000.json` — IN-PT-CHN-001 (Greater
  Chennai Corporation's local half-yearly-assessed Professional Tax).
- `karnataka_lwf_january.json` — IN-LWF-KA-001 (Karnataka's annual
  Labour Welfare Fund, charged only in its configured collection month).

None of these were run through an official government calculator (the
document's own P2 "independent calculation oracle" tier) — that remains
open, real, future work. Every figure here was either taken verbatim
from the document's own §21 worked example, or derived from the real
seeded rates in `hardcoded_defaults.py` (reproduced verbatim in each
fixture's own `context`, not omitted, so a case is self-contained and
doesn't silently break if those defaults ever change).

## Known scope limitation — golden IDs NOT represented as JSON fixtures here

The doc's §21 list also names IN-TAX-002, IN-TAX-003, IN-TAX-004,
IN-WAGE-001, IN-CAP-001, IN-RETRO-001, and IN-SOURCE-001. These are
covered instead by `tests/test_india_golden_certification.py` as
ordinary pytest functions, for two distinct reasons documented in that
file itself:

1. **IN-TAX-002/003/004** are specified by the document as *annual*
   figures that are not evenly divisible by 12 once the standard
   deduction is added back (e.g. IN-TAX-002's implied annual gross,
   ₹1,325,000, is ₹110,416.66̄7/month — a repeating decimal). Routing
   these through the JSON harness's `gross`-per-period → ×12 pipeline
   would introduce sub-paisa rounding noise unrelated to the actual tax
   logic being tested. They instead call
   `engine/countries/india.py::_calculate_annual_tax_in` directly with
   the doc's own exact annual figures — still the real per-payslip
   computation function (the same one `calculate()` calls), just
   exercised at the annual-figure level instead of round-tripping
   through a monthly gross that can't represent these numbers exactly.
2. **IN-WAGE-001, IN-CAP-001, IN-RETRO-001, IN-SOURCE-001** are not
   single numeric golden vectors at all — they're behavioral/
   integration assertions (a wage-base computation helper's return
   value; a boolean compliance flag; date-based pack-version
   resolution; a registry status check), which this JSON harness's
   `expected: {field: decimal}` shape (exact `Decimal` equality against
   a `PayrollResult` field) cannot represent.

## Case JSON format

Same shape as `hmrc_golden_harness.py`'s own module docstring/
`tests/fixtures/cra_golden/README.md` document, with the India-specific
additions (gap-closure Phase F): `context.tax_regime` ("New"/"Old"),
`context.gender` (Maharashtra's gender-differentiated PT), and two new
`GoldenSlab` fields — `adjustment_amount` and `assessment_basis` — for
India's PT_FLAT bracket rows (`work_state`/`state_rate_map`/
`state_slabs` were already generic from Canada's own extension).
Comparisons are exact Decimal equality — no tolerance.

## Running the harness

```
python -m pytest tests/test_in_golden.py -v
```

Or trigger a run from the Super Admin UI (Compliance > Test
Certification, select "India (CBDT/EPFO/ESIC)" from the jurisdiction
dropdown) — both paths call the exact same `run_golden_case`/
`calculate_payroll` code.

## Adding more cases

Follow the same "derive from the document's own tables/worked examples,
hand-verify, then cross-check against the real engine" discipline these
seven used — never invent a number, and never assert a figure this
codebase hasn't independently reproduced at least once via the actual
production engine.
