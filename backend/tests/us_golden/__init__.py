"""
tests/us_golden
------------------
US state-program/withholding golden-test integration harness (ZP-TAX-US-
2026-001 §13, gap-closure Phase 8, 2026-09-12) — the US counterpart to
tests/cra_golden/, generalized from the same underlying harness (see
app/modules/payroll/hmrc_golden_harness.py).

See tests/fixtures/us_golden/README.md for what's here today, how the
cases were derived from the document's own §5/§13/Appendix A worked
examples, and known scope limitations (the harness has no YTD/employer-
headcount injection, so CYTD-boundary and headcount-gated program cases
from §13's table are out of scope here — covered instead by
tests/test_engine_standard.py's direct unit tests). Per the same
"no tolerance" rule the UK/CA harnesses use, every comparison is an
exact Decimal equality check.
"""
