# CRA/Revenu Quebec golden-test fixtures

ZP-TAX-CA-2026-001 §20 ("Test Lab")/AC-29, gap-closure Phase 8 (2026-09-11) —
generalizes the UK-only harness in `hmrc_golden_harness.py` to also run
Canada cases.

## What's here today

Three real (non-underscore-prefixed) cases, derived directly from
ZP-TAX-CA-2026-001's own published 2026 rate/bracket tables (Sections 6,
8, 10, 11, 12 — a genuine P1 source per the document's own §2 authority
hierarchy), computed by hand against those tables and then cross-checked
by running the actual production engine (`build_context`/
`calculate_payroll`) at authoring time:

- `federal_only_flat_gross_4000.json` — federal income tax + CPP + EI,
  no province configured.
- `ontario_gross_8000.json` — adds Ontario's provincial brackets. Its
  `state_income_tax` expected value ($448.83) matches a figure this
  project independently verified live against a real database in an
  earlier session (2026-09-07) — a genuine cross-check, not a fresh guess.
- `quebec_gross_6000.json` — Quebec's own independent module (QPP/QPIP,
  Revenu Québec brackets), not the generic provincial path.

None of these were run through CRA's PDOC or Revenu Québec's WebRAS (the
document's own P2 "independent calculation oracle" tier) — that remains
open, real, future work if an official-calculator cross-check is wanted
on top of the formula-derived verification these cases already have.

## Known scope limitation

These three cases exercise the "core" federal/provincial/QPP/CPP/EI/QPIP
calculation only. They do NOT cover: BC/NL/PE's H1-vs-H2 mid-year
overrides, CPP2/QPP2 corridor behavior, any of the 9 dormant
`_CA_*_ENABLED_COUNTRIES` correctness switches (all still OFF by
default, matching what these cases assume), employer levies (EHT/HE
Levy/HAPSET/HSF/WSDRF), POE resolution scenarios, or non-periodic
payments. Each of those would need its own additional case(s) — this is
a starting scaffold proving the harness itself works for Canada end to
end, not a complete certification suite.

## Case JSON format

Same shape as `hmrc_golden_harness.py`'s own module docstring documents,
with the Canada-specific additions: `context.country` (defaults to "UK"
if omitted — every existing UK case predates this field), plus
`work_state`/`state_rate_map`/`state_slabs`/`td1_claim_amount`/
`provincial_td1_claim_amount`/`qc_tp1015_claim_amount` for the
province/Quebec layer. Comparisons are exact Decimal equality — no
tolerance.

## Running the harness

```
python -m pytest tests/test_cra_golden.py -v
```

Or trigger a run from the Super Admin UI (Compliance > Test Certification,
select "Canada (CRA/Revenu Quebec)" from the jurisdiction dropdown) — both
paths call the exact same `run_golden_case`/`calculate_payroll` code.

## Adding more cases

Follow the same "derive from the document's own tables, hand-verify, then
cross-check against the real engine" discipline these three used — never
invent a number, and never assert a figure this codebase hasn't
independently reproduced at least once via the actual production engine.
