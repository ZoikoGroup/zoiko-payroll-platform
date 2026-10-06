# Hong Kong golden vectors (ZP-HK-ENG-001 §16)

Two independent vector sets guard the Hong Kong statutory content:

| Set | Location | Covers | Test |
|---|---|---|---|
| Payroll (MPF) golden vectors | `tests/fixtures/hk_golden/*.json` (11) | MPF thresholds, 60-day rule, holiday, non-monthly, exemptions, YA effective dating | `test_hong_kong.py` (embedded rows and each pack's own rows); Super Admin Test Certification; pack-activation gate |
| Salaries Tax vectors (informational estimate) | `tests/fixtures/hk_salaries_tax_vectors/vectors.json` (32 + 3 attribution) | every band boundary, standard-rate tiers, allowances, deduction ceilings incl. the elected additional ceilings, donations, the 2025/26 one-off reduction, current vs historical YA, part-year income, YA attribution | `test_hong_kong_salaries_tax_vectors.py` |

## Where the expected values come from (independence)

- **MPF vectors:** the expected figures are stated by hand from the published MPFA rules ("Mandatory Contributions — Employees"; "MPF Coverage"). They were never copied from engine output.
- **Salaries Tax vectors:** each one is marked `verification`:
  - `OFFICIAL_EXAMPLE` — the expected figures are the IRD's own published numbers (2026-27 Budget worked examples 1–4, `ird_example2627`, sha256 `52aea360…`).
  - `DERIVED_FROM_STATUTORY_PARAMETERS` — derived by hand from IRD PAM 61(e) (sha256 `357f13eb…`), with every band portion, rate and cap written out in `derivation`.
- Rules that rest on an unverified interpretation are listed in `unverifiedRules` and marked G1. Example: allowances are not apportioned for part-year employment (ST-26, ST-27).
- No expected value in either set is computed by Zoiko code. The Salaries Tax test:
  1. re-adds each vector's own derivation without importing the calculator;
  2. checks that every statutory parameter the vector uses equals the seeded pack row for that year of assessment, and that the row's source artifact is the IRD document;
  3. only then compares the production estimate.

## Regenerating

Only the **embedded pack rows** of the MPF fixtures are ever regenerated: `context.rate_map`, `context.slabs` and
`context.hk_rule_segments`. They mirror the canonical seed so that both runs prove the pack — the embedded-rows run
in every test, and the pack-bound run at activation.

```
# check only (reports STALE fixtures, writes nothing)
PAYROLL_DATABASE_URL=sqlite:///<scratch>.db python -m scripts.regenerate_hk_golden_fixtures
# rewrite the embedded rows after a reviewed seed change
PAYROLL_DATABASE_URL=sqlite:///<scratch>.db python -m scripts.regenerate_hk_golden_fixtures --write
```

- **Database:** the regenerator refuses non-local databases (`scripts/_local_db_guard`). Always point it at a
  disposable SQLite file, never `backend/.env`.
- **What it preserves:** it writes back `description`, `source`, `pack` and `expected` **verbatim**, so it cannot
  change an answer. Diff the fixtures afterwards: only `context` may move.
- **Salaries Tax vectors:** these have **no generator**. They are edited by hand only.

## When regeneration is appropriate, and when manual review is mandatory

| Change | Action |
|---|---|
| A seed change that does not alter any value a vector depends on (new row, relabel, provenance) | run `--write`; the tests must still pass unchanged |
| A statutory value changes for an **existing** year of assessment (an official correction) | **manual review**: update the source artifact, the seed, the affected vectors' parameters / derivation / expected — by hand, from the new official source — and record why |
| A **new** year of assessment (new allowances, bands, MPF levels) | add a new pack and **new vectors** for the new year; keep every earlier year's vectors unchanged (they prove historical replay) |
| A test fails after a seed or engine change | treat it as a defect until proven otherwise — never edit an expected value to make it pass |

**Statutory-version changes never flow into these files automatically.** The parameter check in
`test_hong_kong_salaries_tax_vectors.py` fails as soon as a pack value stops matching a vector's stated
statutory value, which forces the review above.

## Files

- MPF: `case_a_below_minimum_6500`, `case_b_within_levels_20000`, `case_c_above_maximum_45000`,
  `case_d_weekly_within_levels`, `case_d_weekly_above_maximum`, `case_e_pending_before_60th_day`,
  `case_e_60_day_catch_up_march_2026`, `case_f_leaves_before_60_days`, `exempt_age_66`, `exempt_orso_with_evidence`,
  `ya_2025_26_april_2025`.
- Cases G–L (SMW crossover, 468 rule, IR56G, IR56B after IR56F, SP/LSP transition, average wage with excluded
  periods) need more than one payslip or a non-payslip calculation. They live as tests in `tests/test_hong_kong.py`
  and `tests/test_hong_kong_e2e.py`.
