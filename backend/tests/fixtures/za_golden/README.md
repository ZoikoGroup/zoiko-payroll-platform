# South Africa golden-test fixtures (ZP-ZA-ENG-001)

Run through the shared harness (`app/modules/payroll/hmrc_golden_harness.py`) by
`tests/test_south_africa_golden.py`. "ZA" is South Africa ("SA" is Saudi Arabia).

Every expected figure is **hand-computed from the specification**, never copied
from engine output; each case's `source` shows the arithmetic. Each case carries
the Draft content the seed writes (`south_africa_content.py`): the scalar rows in
force on the pay date, the seven 2027 PAYE bands, the full earning
classification, and (for ETI cases) the six `ZA_ETI_BAND` rows. The fixture files
were generated from that content so their inputs cannot drift from the pack;
regenerate them if the content changes.

| Fixture | Spec | What it proves |
|---|---|---|
| `f1_…`, `f2_…` | §12 F1, F2 | The specification's own worked fixtures (PAYE, rebates, medical credit, UIF ceiling, SDL, net) — unchanged by Phase 4 |
| `f3_eti_first_twelve_months_r5000_is_r1500` | §12 F3 | The employer's ETI is R1,500 while the employee's PAYE/UIF/net are unchanged |
| `f4_travel_allowance_uif_unsigned_blocks` | §12 F4, §4 | PAYE takes 80% of the allowance, but its UIF treatment is unsigned — the run BLOCKS (PAYE inclusion is pinned in `test_south_africa_engine.py`) |
| `uif_below_ceiling_band_1`, `below_tax_threshold`, `band_boundary_age_77_three_rebates`, `top_band_r200000` | §2 | Band edges, the rebate threshold, all three rebates, the top band |
| `retirement_contribution_*` | §2 | 27.5% / R430,000 retirement deduction within limits and capped |
| `medical_three_dependants` | §2 | Medical tax credit for additional dependants |
| `sdl_exempt_employer`, `uif_excluded_with_reason` | §4, ZA-011 | Employer- and employee-level exemptions are facts, not inference |
| `eti_second_twelve_months_r5000_is_r750` | §4, F3 | Months 13–24 use the second-12 band set |
| `eti_below_2500_pct` | §4, F3 | The sub-R2,500 PCT band (R2,000 × 60% × hours un-normalisation) — the fixture overrides the NMW row to R12.50 so the PCT arithmetic is isolated |
| `eti_below_nmw` | §4 | The same R2,000 split at the real R30.23 NMW is INELIGIBLE; ETI is zero, pay is unchanged |
| `eti_hours_normalised_below_full_month` | §4 | R4,000 / 120h normalises to R5,333.33, R1,500 is un-normalised to R1,125 |
| `eti_age_17_ineligible`, `eti_age_30_ineligible`, `eti_month_25_ineligible` | §4 | Age window 18–29 and the 24-month maximum are INELIGIBLE |
| `eti_band_boundary_r7500` | §4 | R7,500 is the first normalised remuneration with no band: ELIGIBLE, R0 |
| `eti_not_registered_ineligible` | §4, ZA-010 | A non-registered employer is NOT_REGISTERED; the employee's pay still computes |
| `directive_fixed_percentage_25` | ZA-007 | An approved FIXED_PERCENTAGE directive replaces ordinary PAYE |
| `directive_fixed_amount_8000` | ZA-007 | An approved FIXED_AMOUNT directive replaces ordinary PAYE |
| `directive_expired_computes` | ZA-007 | An expired directive is ignored and ordinary PAYE computes |
| `directive_unapproved_blocks`, `directive_other_employee_blocks`, `directive_other_tax_year_blocks`, `directive_lump_sum_blocks`, `directive_ambiguous_blocks`, `directive_missing_window_blocks` | ZA-007 | Captured-only, wrong employee/tax year, unsupported lump sums, overlapping directives and a missing window all BLOCK rather than guess |
| `bonus_timing_unsigned_blocks` | §4, ZA-006 | A bonus earned in the **previous** month is outside the pay period; the PENDING_G1 timing basis BLOCKS |
| `bonus_same_period_uif_review_blocks` | §4, ZA-006 | A bonus earned **inside** the pay period passes the derived 7B check, then BLOCKS on its unsigned UIF treatment |
| `*_blocks` | §1, ZA-005/006/011 | Weekly pay, non-residents, non-standard employment, missing tax number / date of birth / employer registration / content row, an unrecorded director UIF status and a cross-tax-year payment all BLOCK — never guessed |

Not covered here: weekly / fortnightly tables and the certified SARS periodic
algorithm itself. The PAYE method is the annualised-monthly cross-check over the
published bands (spec §3 calls the bands validation anchors); a PASS satisfies
only the certification gate — activation still needs the G1–G7 evidence,
including the full SARS deduction-table corpus.

PENDING_G1 recorded, not decided: directive vs medical-credit sequencing; whether
a zero-ETI month uses a qualifying month; and the SARS ETI hours-normalisation
rule (the configured 160-hour normaliser is used as written).
