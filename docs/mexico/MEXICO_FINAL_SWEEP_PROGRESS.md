# Mexico — Final engineering sweep: progress

> **Review required: Rugvedh (ZP-PRIV) before merge.**
> **Do not merge until reviewed — branch protection does not enforce this (C17).**
> Why: S1 adds migration `efc56f3235e2` with three columns on the SHARED `payroll_employee_statutory_profiles` table. It also changes governance: optional four-eyes on Mexico general availability, on retiring Active content, and on organisation-side configuration. And it adds an optional `before_pack_status` hook call to the shared `service.set_jurisdiction_pack_status`.

The sweep has five steps: S1 decisions as configuration; S2 source sweep; S3 incapacity records (**held** by the user, waiting for ZP-PRIV and legal); S4 PTU Art. 127 II; S5 production setup rehearsal. Each step is committed locally on `nikhil` and never pushed.

---

## S1 — Decisions as configuration

**What changed.** An APPROVED answer in Super Admin → Mexico → Decisions now *is* the configuration:

- One Super Admin proposes, a second approves; every step is audited and versioned.
- The answer takes effect immediately: the engine, the reports and the CFDI read it through `engine/jurisdictions/mexico/decisions.switch()`. `mexico_decision_config.applying(db)` applies the register's APPROVED / TRANSCRIBED answers for each calculation, CFDI, receipt, PTU allocation, sandbox run and IMSS movement check.
- Pack-row decisions (D-01, D-03, D-17) fill the row only where the Draft pack has none, so a transcribed row always wins.
- Unanswered, every case still blocks with its own code.

Each payslip records the answers it was calculated with (`snapshot.decisions`). Their fingerprint is part of the input hash, so a committed run whose answers have since changed is flagged stale.

| Decision | Options built (all selectable) | What answering changes | Still needs a value / a source |
|---|---|---|---|
| D-01 rounding | `MODE:QUANTUM`: HALF_UP:0.01, HALF_EVEN:0.01, HALF_DOWN:1 (whole pesos, CFF Art. 20) | the `mx_rounding_rule` row: every emitted amount | — · *not built:* "totals only" (the CFDI carries 2-decimal lines; see the decision panel) |
| D-02 pay frequency 01 | DAILY, WEEKLY_7, DECENAL_10, QUINCENAL_15, MONTHLY, UNMAPPED | Diario uses the chosen Art. 96 tariff period | — |
| D-03 CEAV band 1 | GENERAL, ZONE, UMA | unit of band 1's "1.0 SM" bound (and clears the ZLFN band-1 block) | — |
| D-04 interpretations | record (confirm / reject) | nothing: a confirmation | a rejected interpretation → that row re-transcribed (VALUE) |
| D-05 48-hour Jan–Apr | record | nothing: a confirmation | if rejected, the Jan–Apr row (VALUE) |
| D-06 CDMX ISN base | IN / OUT for each of vacation payout, separation payment, indemnity | CDMX ISN base of those finiquito lines | — |
| D-07 / D-07b wage unit | UMA, ZONE_MIN_WAGE | Art. 93 exempt limits / Art. 486 cap | — |
| D-08 special-pay withholding | RLISR_174, ART_96_MONTHLY, PER_EMPLOYER | method for aguinaldo / PTU in their own run | PER_EMPLOYER: each employer's choice on its labour policy (new field) |
| D-09 monthly income | 30, 30.4, CALENDAR_MONTH | RLISR 174 II and separation withholding | — |
| D-10 CDMX ISN benefit | record only | nothing | **SOURCE**: the SAF general rules (eligibility, proof) — *not built*: both readings of "1%"; building them without the rules would invent eligibility |
| D-11 extra termination reasons | record | nothing | each reason's components from S26 (VALUE) |
| D-12 indemnity salary | POLICY_INTEGRATED, IMSS_SBC, OPERATOR_ENTERED | LFT Art. 89 daily salary for Arts. 48, 50, 54 | OPERATOR_ENTERED: the figure + evidence per termination (new fields) · *not built:* Art. 89 ¶2 30-day variable-pay average (no per-day variable-pay record; OPERATOR_ENTERED carries it) |
| D-13 part years | PROPORTIONAL, COMPLETED | LFT Arts. 50, 54, 162 | — |
| D-14 PTU cap | EXCESS: UNDISTRIBUTED / REDISTRIBUTED; AVERAGE: OVER_THREE / OVER_YEARS_RECEIVED | Art. 127 VIII excess and average | — |
| D-16 business days | LFT_74_715, CFF_12 | non-business days IMSS deadlines skip (2026 lists from S26 / S35) | each later year's dates (VALUE) |
| D-17 hourly rate | DAILY_SALARY_OVER_JORNADA_HOURS, WEEKLY_HOURS_OVER_DAYS, EMPLOYER_DAILY_HOURS | overtime hourly rate | the weekly schedule / the employer's daily-hours figure on the labour policy (new field) |
| D-18 fixed SBC item | PERIOD_DAYS, ANNUALISED_365 | LSS Art. 30 I daily amount | ANNUALISED_365: an earning's payments per year (no input carries it yet) |
| D-19 termination period days | FIXED_DAYS_PRORATED, CALENDAR_DAYS_WORKED | salary days of a fixed-days period ending at termination | — |
| D-20 QR total | TEXT, PADDED | printed receipt QR `tt` | — |
| D-21 time-zone offsets | SAME_LABEL, SWAPPED, KEEP_REFUSING | how an inconsistent c_CodigoPostal row is read | *not built:* (d) offsets from the time-zone law — **SOURCE** not saved |
| D-22 finiquito payout | MONTHLY_TOTAL_LESS_WITHHELD, INCREMENTAL_MONTHLY | vacation payout withholding | — |
| D-23 gate owner | INTERIM_SECOND_SUPER_ADMIN | nothing (confirms the interim control) | *not built:* a gate-owner role (a privileged role is ZP-PRIV's; none invented) |
| D-24 variance threshold | MXN amount, PERCENT of the prior figure, both, per line (NET= / EMPLOYER_TOTAL=) | MX-RUN-VARIANCE high-value flags | the figure (VALUE) |
| D-25 materiality | MXN amount, PERCENT of the legacy amount, both, per concept | parallel-payroll "clean" verdict | the figure (VALUE) |
| D-26 GA four-eyes | SINGLE, FOUR_EYES | second Super Admin to make Mexico generally available | — |
| D-27 retiring content | SINGLE, FOUR_EYES | second Super Admin to retire an Active pack / archive an Active classification | — |
| D-28 org-side four-eyes | per item (employer version, establishment, IMSS registration, INFONAVIT model, labour-policy activation, credential): SINGLE, FOUR_EYES, FOUR_EYES_WHEN_LIVE | second org admin for that change ("live" = a payroll run APPROVED or beyond — the brief does not define it; stated on the panel) | *not built:* effective dating of establishments / INFONAVIT model (a data-model change, not a switch) |
| C4 CFDI SDI | LFT_84_INTEGRATED, IMSS_SBC, OPERATOR_ENTERED | `SalarioDiarioIntegrado` source | OPERATOR_ENTERED: SDI + evidence per worker (new fields) |
| C5 SAT codes | record | nothing (codes go through CFDI system concepts) | three SAT codes (VALUE, S28) |
| C12 Sindicalizado | OMIT, FROM_PROFILE | CFDI `Sindicalizado` | FROM_PROFILE: union membership per worker (new field) |

D-15 is not configured: it was resolved by sources (S36). Its section in `DECISIONS_PENDING.md` is now updated to say so.

**Two-person governance (D-26 / D-27 / D-28)** is implemented in `mexico_two_person.require`:

- The first call records a `…:proposed` audit row (who, a digest of the change) and is refused with `MX_FOUR_EYES_PROPOSED`.
- A different person repeating the identical change within 7 days is recorded `…:confirmed` and the action runs.
- The same person repeating it is refused with `MX_FOUR_EYES_REQUIRED`.

No new table and no new role. Unanswered (or SINGLE), every action runs as before.

**Migration `efc56f3235e2` (m21).** Seven nullable columns, additive and guarded, under `SET LOCAL lock_timeout = '5s'`, single head, no RLS change:

- `payroll_mx_terminations`: `indemnity_daily_salary`, `indemnity_salary_evidence_ref`;
- `payroll_mx_labor_policies`: `hourly_rate_daily_hours`, `special_pay_withholding_method`;
- `payroll_employee_statutory_profiles` (SHARED): `mx_union_member`, `mx_sdi_operator_entered`, `mx_sdi_evidence_ref`.

Measured on PostgreSQL 17 (`tests/test_mexico_decision_inputs_migrations.py`, 5/5):

- in flight, ACCESS EXCLUSIVE is held on the three tables only, for about 145 ms;
- `organizations` and `payroll_employees` stay readable;
- with a reader holding the shared profiles table, the upgrade gives up after 5.1 s with nothing applied;
- the real CLI path and `check_schema_drift` pass.

**Production effect on merge:** the migration runs. Mexico stays dormant: no tenant reaches a Mexican calculation, and the register holds no answer, so nothing changes for anyone. Other jurisdictions: the shared pack-status call gains an optional hook that only Mexico registers.

**Tests:**

- `tests/test_mexico_decision_config.py`: one test per option path, plus governance, threshold grammar, the payslip record, and the sandbox with approved D-01 / D-03;
- `tests/test_mexico_parallel.py`: D-25 percentage and per-concept rules;
- migration and pin tests.

**Browser (installed Chrome, headless, current build):**

- `RESULTS-S1.md` 8/8: unanswered → blocked at D-01; D-28 chosen part by part with its configuration panel; self-approval refused; a second Super Admin approves and the answer is "In force"; the sandbox CALCULATES with approved D-01 / D-03, no candidates, and names the answers and the pack rows they filled.
- `RESULTS-S1-FORMS.md` 7/7 (org admin): union member and SDI + evidence on the profile (refused without evidence); indemnity salary on the termination form; daily hours and the special-pay method on the labour policy, recorded and read back.

Screenshots: `s1_0*.jpg`, `s1f_0*.jpg`.

**Route registry** regenerated with no diff. The decisions are applied inside the Mexico `calc_inputs` hook without adding a call level, so the call graph's depth-bounded table lists are unchanged.
