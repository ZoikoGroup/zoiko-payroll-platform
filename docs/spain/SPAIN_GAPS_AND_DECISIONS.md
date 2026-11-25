# Spain (ES): Gaps and Decisions Register

Plan: `docs/spain/SPAIN_IMPLEMENTATION_PLAN.md`
Spec: ZP-ES-ENG-001 v1.0 (22 September 2026), sections 1–24, rules ES-001 to ES-063, fixtures F1–F6, gates G1–G8.

On 2026-11-24 the owner chose a **simplified design**, the same as the United Arab Emirates and Jamaica:
- Every statutory value is an ordinary pack row in Super Admin.
- Calculation is exact, and a missing value blocks the employee with a named reason.
- The spec's production gates G1–G8, its signing and evidence workflows, and its government-exchange modules are **out of scope**, not pending.

No statutory value is invented. Where the spec gives no figure, the value is recorded below as a gap. The employee concerned is blocked until a Super Admin adds the row from an official source.

## Decisions

| ID | Status | Description |
|---|---|---|
| D1 | DECIDED | **Registration.** Ordinary-country pattern: an Active `ES-PAYROLL-2026` pack with rates is the only registration gate. No registry row is required, there is no dormancy flag and no country hook. |
| D2 | DECIDED | **Approval.** Keep the platform-wide second Super Admin approval before a pack becomes Active. There is no Spain-specific four-eyes, signing, golden-check or evidence tab. |
| D3 | DECIDED | **Where values live.** All values live in the Active pack (Contribution Rates rows: employee / employer fractions, flat amounts, row-level `effective_from`) and are editable in the normal Rates tab. A missing row blocks with `ES_RATE_MISSING:<key>`. |
| D4 | DECIDED | **IRPF source.** The IRPF withholding values come **only** from the official AEAT document "Algoritmo de cálculo de retenciones 2026", which the owner will provide.<br>- There are two versions: rows `irpf_a_*` apply until 2026-09-09 and rows `irpf_b_*` from 2026-09-10, selected by pay date through row `effective_from` (ES-015).<br>- The version used is stored on each payslip (ES-016, ES-039).<br>- Until the rows exist, IRPF blocks. |
| D5 | DECIDED | **Contribution bases.**<br>- Common base = ordinary contributable pay, without overtime, plus the monthly extra-pay prorrata (ES-006).<br>- AT/EP base = common base + overtime.<br>- Both are clamped to the group minimum and to the maximum (€5,101.20/month). |
| D6 | DECIDED | **Solidarity contribution.** Remuneration above the maximum base is split into the three 2026 tranches, as a separate line, with employee and employer shares (ES-011). Thresholds are prorated by days in alta ÷ 30 for a partial month (ES-012). |
| D7 | DECIDED | **Extra payments.** Policy `PRORATED_12` (cash already monthly, so no prorrata) or `SEPARATE_14` (annual extra-pay total ÷ 12 added to the bases only). Extra-pay cash is paid as gross in its month and is never added to the base a second time (F5). |
| D8 | DECIDED | **Unemployment rate.** The general or temporary rate follows the employee's `contract_type`. A conversion applies from its effective date and is never retroactive (ES-009). |
| D9 | DECIDED | **Short-contract surcharge.** The €33.62 surcharge is an employer cost, charged when a TEMPORARY contract shorter than 30 days ends in the period, unless the employee is flagged as an exception (ES-010). |
| D10 | DECIDED (revised P5) | **AT/EP.** AT/EP is an employer-only rate. Because the premium tariff depends on the employer's activity **and the employee's occupation** (ES-008), it is stored **per employee** (`at_ep_rate`, a fraction such as 0.015, taken from the employer's own tariff). There is no universal default; a missing rate blocks with `ES_AT_EP_RATE_MISSING`. |
| D11 | DECIDED | **Minimum wage.** SMI is checked for full-time monthly employees (€1,221/month, prorated by days). Below it, payroll blocks with `ES_BELOW_SMI`. Collective-agreement minimums are not modelled in this scope (ES-044). |
| D12 | DECIDED | **Employer costs and net pay.** Employer-only charges (employer SS, FOGASA, AT/EP, the employer share of solidarity, the surcharge) never reduce employee net pay (ES-042). |
| D13 | DECIDED | **Codes, currency and pages.** Code `ES`, name "Spain", aliases "españa", "espana", "kingdom of spain" (no bare "es"). Currency EUR, half-up rounding to 2 decimals per line. Real Compliance and Report Templates pages in Super Admin. |
| D14 | DECIDED | **Payslip mapping.**<br>- `tds` = IRPF; `social_security` = employee Social Security total; `employer_social_security` = employer Social Security total; `employer_occupational_hazard` = AT/EP; `employer_payroll_tax` = short-contract surcharge.<br>- The full breakdown is stored in `payslip_items.es_calculation_snapshot`. |
| D15 | DECIDED (P5) | **Pay inputs.** Ordinary pay = basic + HRA + special allowance, minus this run's unpaid days, plus `additional_compensation` as ordinary variable pay. Exception: for a `SEPARATE_14` employee, in a month listed in `extra_pay_months` (for example 6,12), `additional_compensation` is the **cash extra pay**: it is gross pay but never enters the bases a second time (F5). Overtime = the run's overtime amount. |

## Values seeded from the spec

| Area | Value | Spec |
|---|---|---|
| Common contingencies | employee 4.70% / employer 23.60% | §2, §4 |
| MEI | 0.15% / 0.75% | §2 |
| Unemployment, general | 1.55% / 5.50% | §2 |
| Unemployment, temporary | 1.60% / 6.70% | §2 |
| FOGASA | employer 0.20% | §2 |
| Training | 0.10% / 0.60% | §2 |
| Overtime, force majeure | 2.00% / 12.00% | §4 |
| Overtime, other | 4.70% / 23.60% | §4 |
| Solidarity tranche 1 (€5,101.21–5,611.32) | 0.19% / 0.96% | §5 |
| Solidarity tranche 2 (€5,611.33–7,651.80) | 0.21% / 1.04% | §5 |
| Solidarity tranche 3 (above €7,651.80) | 0.24% / 1.22% | §5 |
| Maximum base | €5,101.20/month, €170.04/day | §2 |
| Minimum base, groups 4–7 | €1,424.40/month | §2 |
| Minimum base, groups 8–11 | €47.48/day | §2 |
| SMI | €1,221/month, €40.70/day, €17,094/year | §2, S1 |
| Short-contract surcharge | €33.62, contracts under 30 days | §2, ES-010 |

## Gaps (no figure in the spec, so nothing is invented)

| ID | Gap | Until resolved |
|---|---|---|
| G-01 | **IRPF algorithm parameters for both 2026 versions:** scale, personal and family minimums, work-income reduction, expenses, minimum rates, rounding and regularisation | IRPF blocks (`ES_RATE_MISSING:irpf_*`). Resolved by the owner's AEAT document (D4). |
| G-02 | Minimum bases for contribution groups 1–3 (the spec says only "higher minima") | Employees in groups 1–3 block until rows `es_base_min_group_1/2/3` exist |
| G-03 | The AT/EP premium rate (CNAE / occupation tariff) | Per-employee field `at_ep_rate` (D10); payroll blocks until it is entered |
| G-04 | Hourly minimum bases for part-time employees | Part-time employees block (`ES_PART_TIME_NOT_SUPPORTED`) |
| G-05 | Solidarity and base logic for daily contributors (groups 8–11) | Daily-contributor groups block (`ES_DAILY_GROUP_NOT_SUPPORTED`) until the official rule is given |
| G-06 | The exact Modelo 145 fact list and its effect on the minimums | Fields from §7 are captured; their values come from the AEAT document |

## Out of scope (owner decision; later phases on request)

| Topic | Spec |
|---|---|
| SLD / SILTRA file exchange, TGSS tramos, RNT / RLC lifecycle | §9 |
| CRA concept mapping and transmission | §10 |
| Modelo 111 / 190 filing files and the AEAT payment lifecycle (report-template summaries only) | §11 |
| CCC readiness, collective-agreement (convenio) salary tables and working-time rules | §12, §15 |
| Temporary incapacity (IT), birth/care benefits, delegated payment | §17 |
| Termination: severance, vacation settlement, final extra-pay accrual | §18 |
| Vacation and holiday calendars | §16 |
| SEPA bank file and bank settlement states, accounting journals | §19 |
| Production gates G1–G8 and the parallel-payroll evidence | §22, §23 |
| Excluded regimes: household, agricultural, maritime, artists, public sector, expatriate tax regimes, A1 postings | §1 |

## Fixtures used as regression tests

| Fixture | Control | Phase |
|---|---|---|
| F1 | €5,500: base capped at €5,101.20; €398.80 in solidarity tranche 1 | P3 / P5 |
| F2 | €8,000: base capped; excess split across all three tranches | P3 / P5 |
| F3 | IRPF on 9 Sep vs 10 Sep 2026 uses versions A vs B | P4 (needs the AEAT document) |
| F4 | Temporary contract under 30 days: temporary unemployment rates + €33.62 employer surcharge | P3 / P5 |
| F5 | 14 payments: monthly prorrata in the base, extra-pay cash not counted twice | P3 / P5 |
| F6 | IT common illness | Out of scope (blocked) |
