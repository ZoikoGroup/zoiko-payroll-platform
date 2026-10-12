# Ireland (Revenue) golden-test fixtures

ZP-IE-ENG-001 — Ireland 2026 statutory build.

## What's here today

**No real golden cases exist yet.** This directory is intentionally
present but empty of cases, because Ireland's certification basis is
materially different from every other jurisdiction in this repo and cannot
be manufactured:

An Irish PAYE result is not derivable from a published rate table alone.
`engine/countries/ireland.py` reads the employee's standard-rate band, tax
credit, LPT instruction, prior year-to-date taxable pay and periods elapsed
from **Revenue's own per-employee RPN** — and it *blocks* rather than
falling back to a reference band when no RPN is in force (IE-005,
IE-031). So a "golden" PAYE case is only real if it carries a genuine RPN
instruction, and RPN instructions are per-PPSN, issued by Revenue, and
subject to their own approval workflow. Authoring one by hand would mean
inventing a Revenue instruction — precisely the thing this codebase's
authority-hierarchy rules forbid.

Until a real, approval-cleared RPN set is available, Ireland's numeric
coverage lives in `tests/test_engine_ireland.py` (calculator unit and
boundary tests over hand-computed statutory rates) and
`tests/test_ireland_statutory_catalog.py` (pack-content contract tests),
not here.

Consequently the Super Admin **Compliance > Ireland > Tests** tab reports
"0 real Ireland cases exist yet" and certifies nothing. That is the correct
reading, not a bug — pack activation must not be gated on a suite that
does not exist.

## The two open blocking divergences (G1)

These are real, and currently unresolved. They are preserved as
`xfail` (not skipped, not deleted) in `tests/test_engine_ireland.py` so
they stay visible in every run and cannot be quietly forgotten:

| Quantity | Spec (ZP-IE-ENG-001) | Engine | Status |
| --- | --- | --- | --- |
| PAYE on the worked example | `533.32` | `533.33` | `xfail` — rounding direction |
| Net pay on the worked example | `3157.61` | `3218.67` | `xfail` — rounding **and** an unresolved component difference of `61.06` |

The second one is not only a rounding question. A `61.06` gap is large
enough to be a genuinely different calculation rather than a half-cent
convention, so it must be traced to a specific component before anyone
changes a rounding constant. Both need an Irish statutory specialist
ruling against Revenue's published method; neither may be "fixed" by
adjusting an engine value to match the document.

## Source hierarchy for future cases

Cases must be sourced in this order, per the spec's own §2 authority
hierarchy, and the tier used must be recorded with the case:

1. Revenue's own published PAYE/USC/PRSI rate notices and the RPN
   specification.
2. Revenue-issued RPN instructions (per PPSN, approval-cleared).
3. Department of Social Protection sick-pay and minimum-wage notices.
4. NAERSA / Department of Finance MyFutureFund notices and the
   eRegistration status file.
5. The spec document's own worked examples — **last**, and only after the
   component-level trace above.

## Adding more cases

Same discipline as `au_golden/README.md`: derive from the authority, hand-
verify each component, then cross-check against the real production
engine (`build_context`/`calculate_payroll`) at authoring time. Never
invent a number, and never assert a figure the engine has not
independently reproduced.

A new Ireland case also needs a runner. There is no
`ie_golden_harness.py` yet — every other jurisdiction here reuses a
`test_<cc>_golden.py` entry point that calls the same `run_golden_case` /
`calculate_payroll` code the Super Admin Tests tab invokes. Whoever adds
the first real case must add that entry point too, and register `"IE"` in
it, otherwise the Tests tab will keep reporting zero regardless of how
many case files exist here.
