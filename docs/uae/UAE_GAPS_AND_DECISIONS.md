# United Arab Emirates (AE): Gaps and Decisions Register

Plan: `docs/uae/UAE_IMPLEMENTATION_PLAN.md`
Spec: ZP-AE-ENG-001 v1.0 (synthetic worked examples only; no signed legal
source is represented by the seeded values).

The original gap register described a gated P1/P2 rollout. That design was
replaced by the owner's simplified decision, so the old G1–G7 release gates,
registry row, dormancy flag, signing tab, evidence review and free-zone schemes
are closed as out of scope, not pending.

## Decisions

| ID | Status | Description |
|---|---|---|
| D1 | DECIDED | Follow the ordinary-country pattern (Jamaica-style). An Active AE pack with rates is the only registration gate. |
| D2 | DECIDED | Keep the platform-wide second Super Admin approval before a pack becomes Active. No AE-specific four-eyes flow. |
| D3 | DECIDED | All statutory values live in the Active pack and are editable in the normal Rates tab; no signing, source-upload or reviewer tabs. |
| D4 | DECIDED | Pension contribution salary is capped at the pack's maximum and blocked below the pack's minimum. |
| D5 | DECIDED | Government support applies only when the employee is marked eligible and is capped at the pack's support limit. |
| D6 | DECIDED | Monthly gratuity / savings subscription accrual is an employer cost line. No final-settlement workflow in this scope. |
| D7 | DECIDED | Unpaid absence days are derived from payslip attendance, not typed as an employee fact. |
| D8 | DECIDED | DIFC and ADGM are blocked with a named reason. Their schemes need a later spec and pack rows. |
| D9 | DECIDED | GCC home-country rates are out of scope; a GCC national without a configured rate is blocked. Part-time gratuity is likewise blocked. |
| D10 | DECIDED | No WPS SIF file, bank transmission, leave encashment, deduction caps, or public-holiday calendar in this scope. |
| D11 | DECIDED | Currency AED, half-up rounding to 2 decimals per line, no income-tax line. |
| D12 | DECIDED | Jurisdiction code `AE`, name "United Arab Emirates", aliases `UAE`, `U.A.E.`, `Emirates`. |
| D13 | DECIDED | AE has real Compliance and Report Templates Super Admin pages so neither grid shows "Coming soon". |

## Worked examples

The calculator tests mirror the synthetic F1–F7 examples: 3/7-year traditional
gratuity, savings bands, Law 57 and ADPF splits, overtime minimums and the
Emirati minimum-salary cutover. They are regression fixtures, not legal values.

## Follow-ups (later spec)

| Topic | Reason |
|---|---|
| DIFC / ADGM workplace savings | Separate regimes; currently blocked. |
| GCC extension rates | Need home-country schedules from a signed source. |
| Part-time gratuity | No formula in the current spec. |
| WPS SIF layout and transmission | External agent/bank format not in scope. |
| Final settlement, leave encashment, notice pay | Separate workflow. |
| Public-holiday calendar | Source must be supplied; never seed code dates. |
