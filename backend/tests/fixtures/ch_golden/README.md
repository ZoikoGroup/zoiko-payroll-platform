# Switzerland golden-test fixtures

CH spec: Switzerland 2026 statutory build (Step 16).

## What's here

There are 12 golden cases (`*.json`), one per spec §16 engine scenario:

| Case | What it pins |
|---|---|
| `alv_cap_mid_year` | ALV ceiling reached mid-year: only 8,200 of 15,000 is insurable; AHV continues; BVG capped at the upper salary |
| `bvg_threshold_below` / `bvg_threshold_crossed` | BVG entry threshold, and the Art. 8 para 2 minimum coordinated salary |
| `nbu_7_5_hours` / `nbu_9_hours` | NBU only from 8 h / week; BU always |
| `qst_canton_zh_march` / `qst_canton_be_april` | QST canton change: each month on its own canton tariff, never blended |
| `qst_corrected_tariff` | The same month on a corrected tariff file |
| `geneva_floor_met` / `_shortfall` / `_out_of_scope` | Canton minimum applies only in its canton; a shortfall BLOCKS (`expected_blocked_key`) |
| `fak_canton_above_minimum` | Canton FAK amount above the federal minimum, paid per approved entitlement |

The service-level scenarios are in `tests/test_switzerland_golden.py`: corrected-tariff delta, ELM rejection, certificate regeneration and 2027 rule isolation. They run on a real generated payroll and are checked against the same reference figures.

## Where the expected values come from

`calc_reference.py` is an independent, standalone calculator. It uses only the standard library and **imports nothing from `app`** (a test enforces this). It re-derives every figure from the Swiss rules written out in its docstring. No expected value was copied from engine output.

Run `python calc_reference.py --write` to rewrite the cases. `test_switzerland_golden.py` fails if a fixture drifts from what the reference computes.

All data is SYNTHETIC: the QST tariff tables, BVG / UVG / KTG plan rates, the compensation-office admin cost, canton FAK amounts and the Geneva floor. The federal 2026 parameters are typed from the published sources and are still `needs_g1`.

## What these cases are not

They prove that the engine agrees with an independent reading of the rules on synthetic data. They are **not** gate evidence:

- No case is an authority-published example.
- Readiness counts a PASS certification run only as supporting information. Every gate G1–G7 still needs its own reviewed `CH-GATE-Gn` evidence.

## Found by these cases

The engine capped the BVG **coordinated** salary at the upper salary (90,720) instead of capping the **annual** salary before the coordination deduction (BVG Art. 8). That over-insured every salary above about 87,000. It was fixed in CH Step 16, and `test_bvg_coordinated_salary_is_bvg_art_8` guards it.
