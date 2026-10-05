# Italy golden fixtures (ZP-IT-ENG-001)

`italy_golden_2026.json` is the acceptance set for `engine/countries/italy.py`,
run by `tests/test_italy_engine.py::test_golden_case`.

## Where the figures come from

Every expected figure was produced by a standalone calculator written straight
from the specification text (§2 baseline, §3 IRPEF, §4 deductions and tax
wedge, §5 local surtax, §6 INPS, §13 TFR). It shares **no code** with
`italy.py`, and the cases were not regenerated from engine output. Two cases
(`jan_1000`, `jan_2500`) were also checked by hand.

The scenario is held constant across cases: monthly payroll, Milan (Lombardia)
tax domicile, ordinary worker, INPS IVS 9.19% / 23.81%, no CIGS, an employer
covered by CIG (so no FIS), and 13 *mensilità* unless the case says otherwise.

| Rule | Figure used |
|---|---|
| IRPEF (§3) | 23% to €28,000; 33% to €50,000; 43% above |
| Detrazione lavoro (§4) | €1,955 (≤€15k, floor €690 permanent / €1,380 fixed-term); €1,910 + €1,190×(28,000−R)/13,000; €1,910×(50,000−R)/22,000; pro-rated days/365 |
| Wedge tax-free sum (§4) | 7.1% / 5.3% / 4.8% of period taxable income, band chosen on the annual forecast (≤€8.5k / €15k / €20k) |
| Wedge additional deduction (§4) | €1,000 (€20k–€32k), €1,000×(40,000−R)/8,000 (€32k–€40k), pro-rated |
| Extra 1% IVS (§6, IT-016) | cumulative above €56,224 contributory pay |
| Contribution ceiling (§6, IT-017) | €122,295 cumulative, cohort `POST_1995` only |
| INPS contributory minimum (§2/§6) | contributions on max(pay, €58.13 × 26 contributory days = €1,511.38) |
| TFR (§13) | actual pay / 13.5, less the 0.50% INPS offset on the contributory base |
| Lombardia surtax | 1.23 / 1.58 / 1.72 / 1.73% progressive (Draft — verify against MEF) |
| Milano surtax | 0.8% on the whole income above a €23,000 exemption (Draft — verify against MEF) |

Withholding is cumulative (IT-005): annual forecast = YTD taxable + this
period's taxable × remaining *mensilità*; period IRPEF = annual net tax ×
(mensilità paid incl. this one) / total − YTD withheld. The regional and
municipal amounts are this year's **liability**, which v1 traces but does not
withhold (instalment ledger not built yet). The tax-free sum is added to net pay
and is never netted against IRPEF (IT-009).

## Contributory minimum (2026-10-01)

`jan_1000`, `jan_1500`, `jul_hire_1000_partial_year` and
`oct_hire_1000_detrazione_floor` pay less than the 2026 INPS minimum for a full
month (€58.13 × 26 = €1,511.38), so their contributions are due on €1,511.38.
Their expected figures were re-derived by a second standalone calculator (no
engine code) that also reproduces the other six cases unchanged. IRPEF taxable
income stays actual pay minus the contributions actually deducted, and TFR
accrues on actual pay; only the 0.50% offset follows the raised base.

## What these are not

They are not the independently reviewed reference calculations required by spec
gate G1, and the local surtax rates are Draft. A PASS here means the engine
implements the spec's formulas, not that the content is law-verified.
