# Saudi Arabia golden-test fixtures (ZP-SA-ENG-001)

Run through the shared harness (`app/modules/payroll/hmrc_golden_harness.py`) by
`tests/test_saudi_arabia_golden.py` and by Super Admin's Test Certification
console (`run_golden_test_certification(jurisdiction_country="SA")`).

Every expected figure is **hand-computed from the specification**, never copied
from engine output. Each case carries the full Draft content the seed writes:
both 2026 new-system pension rows with their legal dates (9.5% to 2 Jul, 10% from
3 Jul), legacy 9%, SANED 0.75% / 0.75%, Occupational Hazards 2% employer for Saudi
and non-Saudi workers, the 1,500 / 400 minimums, the 45,000 maximum and the GOSI
earning classification.

| Fixture | Spec | What it proves |
|---|---|---|
| `f1_…` – `f5_…` | §17 F1–F5 | The specification's own worked fixtures |
| `transition_jul2026_*` | §4 SA-007 / SA-027 | A month containing the 3 Jul step BLOCKS while the selection rule is PENDING_G1; a signed rule selects one row; legacy is unaffected |
| `scope_gcc_blocks`, `scope_domestic_blocks` | §3, SA-001, SA-020 | Out-of-scope workers BLOCK, never default to Saudi/expat logic |
| `cohort_missing_blocks` | SA-006 | A Saudi cohort is never inferred |
| `below_minimum_*` | SA-010 | Below a branch minimum BLOCKS by default; FLOOR only when signed |
| `derived_wage_*` | §5, SA-012 | Without a registered wage the base is basic + housing; a REVIEW component BLOCKS |
| `non_saudi_with_loan` | §11 | A validated loan deduction reduces net pay |

Not covered here (they are not single result fields): EOS / final settlement
(`tests/test_saudi_arabia_eos.py`, spec F6), labour caps, overtime and hours
(`tests/test_saudi_arabia_labour.py`), and the WPS variance case F7 (service
preflight). A PASS satisfies only the certification gate; activation still needs
the G1–G8 evidence.
