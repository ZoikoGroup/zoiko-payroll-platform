# US golden-test fixtures

ZP-TAX-US-2026-001 §13 ("Certification and Golden Test Suite"), gap-closure
Phase 8 (2026-09-12) — the US counterpart to `tests/fixtures/cra_golden/`,
reusing the exact same generalized harness (`hmrc_golden_harness.py`).

## What's here today

Six real (non-underscore-prefixed) cases, each taken directly from a test
ID and its expected invariant in ZP-TAX-US-2026-001 §13's own table (a
genuine P1 source per the document's own §14.1 authority hierarchy),
cross-checked against Appendix A's verified figures, and recomputed by
running the actual production engine (`build_context`/`calculate_payroll`)
at authoring time — not hand-derived, not guessed:

- `us_ky_formula_monthly_3270.json` (US-KY-001) — Kentucky's flat
  withholding formula ($3,360 standard deduction, 3.5% rate).
- `us_ca_sdi_covered_wages_10000.json` (US-CA-SDI-001) — California SDI.
- `us_ct_paid_leave_below_cap.json` (US-CT-PL-001) — Connecticut Paid Leave.
- `us_nj_fli_below_base.json` (US-NJ-FLI-001) — New Jersey Family Leave
  Insurance (isolated from NJ's other three worker programs).
- `us_wa_cares_gross_10000.json` (US-WA-CARE-001) — WA Cares Fund.
- `us_ny_pfl_annual_cap.json` (US-NY-PFL-001) — New York PFL's $411.91
  annual cap, proven within a single high-wage period rather than a
  literal multi-period CYTD replay (see that file's own description).

## Known scope limitations

The harness (`hmrc_golden_harness.py`'s `build_context`) has no YTD
accumulator and no `employer_tax_profiles` injection point. That rules
out, for this harness specifically:

- §13's federal CYTD-boundary cases (US-FED-001 through 005, US-FIT-001)
  — these assume an employee already at a specific year-to-date wage
  before the case's own pay period; already covered instead by direct
  unit tests in `tests/test_engine_standard.py` (e.g.
  `test_us_social_security_capped_at_wage_base`,
  `test_us_medicare_additional_above_threshold`), which construct that
  scenario directly.
- US-WA-PL-001 (WA Paid Leave, large employer) — the employer share is
  headcount-gated via `EmployerTaxProfile.covered_employee_count`, which
  this harness cannot express. Also covered by direct unit tests instead
  (`test_us_ma_pfml_headcount_gate_*` in `test_engine_standard.py` proves
  the identical headcount-gating mechanism for MA; the same mechanism
  drives WA/CO/ME/DE).
- US-PA-EIT-001 (PA resident/work EIT comparison) and US-LOCAL-001
  (locality change effective date) — both need the Locality
  Dataset/reciprocity layer, neither of which has real production data
  loaded yet (see the platform's own US gap-closure status notes).
- US-CO-001 (Colorado formula) and US-FIT-001 — the document doesn't give
  a fully worked literal answer for either (§13 only says "matches DR
  1098 calculation" / "select correct band," no dollar figure to assert
  against), so no case was authored rather than inventing an expected
  value.

None of these six cases were run through an official state calculator
(the document's own P2/P3 "independent calculation oracle" tier) — that
remains open, future work if an official cross-check is wanted on top of
the document-formula-derived verification these cases already have.

## Case JSON format

Identical to `tests/fixtures/cra_golden/`'s own format — `context` is fed
to `build_context`, `expected` is `{field_name: expected_value}` checked
by exact Decimal equality (no tolerance) against the real
`calculate_payroll` result.

## Running the harness

```
python -m pytest tests/test_us_golden.py -v
```

## Adding more cases

Same discipline as `cra_golden/README.md`: derive only from the
document's own tables/worked examples, hand-verify, then cross-check
against the real engine — never invent a number, and never assert a
figure this codebase hasn't independently reproduced at least once via
the actual production engine.
