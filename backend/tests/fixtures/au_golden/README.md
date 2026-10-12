# Australia (ATO) golden-test fixtures

ZP-TAX-AU-2026-27-001 §26-27 ("Golden Test and Certification Matrix" /
"Mandatory Boundary Test Examples"), Phase 7 (2026-09-17) — generalizes
the UK-only harness in `hmrc_golden_harness.py` to also run Australia
cases, alongside the existing UK/Canada/India/US support.

## What's here today

Sixteen real (non-underscore-prefixed) cases, derived directly from
ZP-TAX-AU-2026-27-001's own published 2026-27 coefficient/threshold
tables (Sections 6, 7, 8, 10, 15, 17 — a genuine P1 source per the
document's own §2 authority hierarchy), computed by hand against the
document's own `y = a·x − b` formula and boundary rules, then
cross-checked by running the actual production engine
(`build_context`/`calculate_payroll`) at authoring time:

- `scale1_weekly_gross_1000.json` / `scale2_weekly_gross_1000.json` /
  `scale3_foreign_resident_weekly_gross_3000.json` /
  `scale4_no_tfn_resident_weekly_gross_1000.json` /
  `scale4_no_tfn_nonresident_weekly_gross_1000.json` /
  `scale5_full_medicare_exemption_weekly_gross_1000.json` /
  `scale6_half_medicare_exemption_weekly_gross_1000.json` — one ordinary
  case per Schedule 1 Scale (1/2/3/4/5/6), each landing in a different
  coefficient band to prove correct band selection per scale.
- `scale2_zero_region_boundary.json` / `scale2_medicare_transition_
  boundary.json` — the two Scale 2 boundary cases §27 names explicitly
  ($362 zero region; $538/$673 Medicare shade-in transition).
- `stsl_claimed_or_foreign_with_scale2_weekly_gross_2000.json` /
  `stsl_not_claimed_with_scale1_weekly_gross_2100.json` — Schedule 8
  STSL, both declaration families, each combined with its corresponding
  Schedule 1 scale on the same gross to prove AU-AC14 (PAYG and STSL
  independently calculated, not folded together).
- `sg_mcb_crossing.json` — the §27 "SG MCB crossing" boundary case:
  YTD qualifying earnings near the $270,830 Maximum Contribution Base,
  this period's SG correctly capped at the remaining room.
- `nsw_payroll_tax_threshold_boundary.json` — the §27 "NSW threshold"
  case ($1.2m boundary), exercising the bracket-table state-tax path
  (`state_slabs`, shared with NSW/TAS/ACT).
- `wa_payroll_tax_taper_boundary.json` — the §27 "WA taper" case
  ($1m/$7.5m boundaries, 2/13 taper), exercising the rate-map parameter
  state-tax path (shared with QLD/VIC/NT/SA).
- `extra_pay_calendar_53_week.json` / `extra_pay_calendar_27_fortnight.json`
  — the §7 "Extra-pay calendar" additional-withholding top-up, both
  calendars, added Phase 7 (2026-09-17) as a previously-missing engine
  feature closed alongside this golden-test suite.

None of these were run through the ATO's own PAYG withholding calculator
(the document's own P2 "official calculator" tier) — that remains open,
real, future work if an independent-oracle cross-check is wanted on top
of the formula-derived verification these cases already have.

## Known scope limitation

These sixteen cases exercise Schedule 1 (all six scales), Schedule 8
STSL (both families), Payday Super's MCB cap, and two of the eight
state/territory payroll-tax mechanisms (bracket-table and taper-formula
shapes — the other six states reuse one of those same two mechanisms,
see `engine/countries/australia.py`'s own `_AU_STATE_PAYROLL_TAX_ANNUAL_FN`
dispatch table). They do NOT cover: Working Holiday Maker PAYG, Special
PAYG Schedules 2/3/4/5/6/12/13 (all raise `AuScheduleNotYetImplementedError`
— no published rate table exists in the source document for any of
these), VIC/QLD/ACT/NT/SA/TAS's own individual boundaries, VIC/QLD's
national-payroll-banded surcharges, cross-employer group/interstate wage
aggregation (§AU-D07), or any of the 3 dormant `_AU_*_ENABLED_COUNTRIES`
correctness switches (all already `{"AU"}` — see `shared.py` — so these
mechanisms are genuinely live, not dormant). Tax offsets (§5 step 4) are
a deliberate, disclosed non-implementation — see
`engine/countries/australia.py`'s own module docstring — since the
source document names them without ever publishing an actual offset
schedule.

## Case JSON format

Same shape as `hmrc_golden_harness.py`'s own module docstring documents,
with the Australia-specific additions: `au_tfn_status`,
`au_residency_status`, `au_tax_free_threshold_claimed`,
`au_medicare_levy_exemption`, `au_withholding_variation_pct`,
`au_extra_pay_calendar`, `ytd_sg_qualifying_earnings_before`,
`au_state_payroll_tax_ytd_remuneration_before`,
`au_payroll_tax_regional_status` — plus `work_state`/`state_rate_map`/
`state_slabs` (already generic, reused as-is for the 8-state
payroll-tax layer) and `study_loan_plan`/`study_loan_balance` (already
generic, reused for AU_HELP). Comparisons are exact Decimal equality —
no tolerance.

## Running the harness

```
python -m pytest tests/test_au_golden.py -v
```

Or trigger a run from the Super Admin UI (Compliance > Australia > Tests
tab), which calls the exact same `run_golden_case`/`calculate_payroll`
code as this pytest entry point.

## Adding more cases

Follow the same "derive from the document's own tables, hand-verify,
then cross-check against the real engine" discipline these sixteen
used — never invent a number, and never assert a figure this codebase
hasn't independently reproduced at least once via the actual production
engine.
