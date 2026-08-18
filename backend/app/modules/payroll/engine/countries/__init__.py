"""
modules/payroll/engine/countries
----------------------------------
One file per country's Standard-strategy compliance calculator, plus a
`shared.py` for the genuinely cross-cutting helpers (the generic bracket
calculator, the safe formula evaluator, and the rate_map override
lookups). Extracted out of the previously-monolithic engine/standard.py
so that adding or auditing one country's formulas never requires reading
or touching the other five.

Every module here exports a single `calculate(ctx: PayrollContext) -> dict`
function with the exact same signature/contract the old `_calc_*`
functions in engine/standard.py had — engine/standard.py re-exports each
of them under their original private names (`_calc_india`, `_calc_us`, ...)
so every existing caller (engine/enterprise.py, this test suite) keeps
working completely unchanged; only the implementation moved.
"""
