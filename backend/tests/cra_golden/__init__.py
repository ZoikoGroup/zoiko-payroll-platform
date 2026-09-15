"""
tests/cra_golden
------------------
CRA/Revenu Quebec golden-test integration harness (ZP-TAX-CA-2026-001
§20/AC-29, gap-closure Phase 8, 2026-09-11) — the Canada counterpart to
tests/hmrc_golden/, generalized from the same underlying harness (see
app/modules/payroll/hmrc_golden_harness.py).

See tests/fixtures/cra_golden/README.md for what's here today, how the
cases were derived and cross-checked, and the known scope limitations.
Per the same "no tolerance" rule the UK harness uses, every comparison
is an exact Decimal equality check — never an approximate/rounded match.
"""
