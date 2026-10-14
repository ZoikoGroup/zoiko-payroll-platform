# G4 — Edge cases: test report (DRAFT for review)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. Not accepted evidence.
**Gate:** HK-GATE-G4 — "60-day MPF, contribution holiday, non-monthly pay, 468 rule, SMW crossover, departure hold and SP/LSP transition tests pass" (wireframe v1.0 §16).

## How this was produced

| Item | Value |
|---|---|
| Command | `python -m pytest -v -p no:cacheprovider <50 node ids>` (full command is line 1 of `G4_test_run_output.txt`) |
| Started (UTC) | 2026-10-13T08:54:53Z |
| Code | branch `nikhil` at `e9da6d4` plus the working tree proposed for `feature/hk-launch-readiness` (see `../STATUS.md`) |
| Database | throwaway SQLite file (never the production or shared database) |
| Result | **50 passed, 0 failed** (1 unrelated deprecation warning) |
| Raw output | `G4_test_run_output.txt` |
| Output SHA-256 | `e68061ff2d8ee08978c2761c08f29a980861d51d20ab3a285e9329c4327b9f98` |

These are automated tests on test data. They show the engine and services behave as the wireframe describes. They do not certify the statutory content (G1) and are not parallel-run evidence (G3).

"End to end" here means the scenario goes in through the services an operator uses (employee and statutory profile, recorded timesheet hours, a payroll run generated and committed, eMPF / IRD / termination / entitlement services) and the outcome is read back from what those services stored. Every row now has at least one such test, in addition to the unit and golden-vector tests.

## Matrix row → tests (all PASSED in this run)

| # | Scenario → expected result | End-to-end test | Supporting unit / golden tests |
|---|---|---|---|
| R1 | Start 16 Jan 2026 → employer from day 1 once the 60-day test is met; employee contribution holiday; first due date | `test_hong_kong_e2e.py::test_e2e_runs_60_day_catch_up_pack_switch_no_withholding` (committed Jan–Mar runs: Jan pending 0/0; March employer catch-up; employee from March) | `test_60_day_rule_first_contribution_day_and_holiday_boundary` (60th day 16 Mar, holiday to 14 Feb, first contribution day 10 Apr 2026 — a Friday, so the Task 3 deferral does not move it); golden `case_e_*` |
| R2 | Relevant income HK$6,500 → employer 5%, employee nil | **new** `test_r2_r3_mpf_thresholds_end_to_end_through_a_committed_run` (committed April payslip: employer 325.00, employee 0.00, net 6,500.00) | `test_case_a_b_c_threshold_branches_from_pack_rows`; golden `case_a_below_minimum_6500` |
| R3 | Relevant income HK$45,000 → both capped at HK$1,500 | **new** same test (committed April payslip: 1,500.00 / 1,500.00, net 43,500.00) | golden `case_c_above_maximum_45000` |
| R4 | Wage period crosses 1 May 2026 → HK$42.10 before, HK$43.10 from | **new** `test_r4_smw_crossover_end_to_end_from_timesheet_through_a_payroll_run` (run 16 Apr – 15 May; recorded hours 10 h/day then 6 h/day; payslip assessment 150 h × 42.10 + 90 h × 43.10 = 10,194.00, 43.10 segment from 2026-05-01) | `test_case_g_*` (both, incl. the directional unequal-hours test) |
| R5 | One week < 17 h, 4-week total 70 → post-18-Jan-2026 68-hour limb qualifies | **new** `test_r5_468_rule_end_to_end_from_timesheet_through_payroll_to_entitlement` (timesheets for two employees: 16 h week → total 70 → CONTINUOUS; 13 h week → 67 → NOT_CONTINUOUS; February preflight shows `EO_CONTINUOUS_CONTRACT` / `EO_NOT_A_CONTINUOUS_CONTRACT`; committed Jan–Apr; holiday pay for 1 May 2026 ENTITLED vs NOT_ENTITLED) | `test_case_h_*`, `test_pre_18_january_2026_weeks_use_the_legacy_418_rule`, `test_468_*` |
| R6 | Departure 35 days ahead → IR56G deadline; covered amounts held until valid release | `test_hong_kong_e2e.py::test_case_i_ir56g_hold_bank_export_ledger_and_four_eyes_release`; `test_bank_export_leaves_out_held_payslips`; `test_changed_departure_keeps_holding_until_release` | `test_case_i_ir56g_states_and_release_rules` |
| R7 | IR56B after a prior IR56F for the same income/year → duplicate prevented, explainable message | `test_hong_kong_e2e.py::test_case_j_ir56b_suppressed_after_prior_ir56f` | `test_case_j_ir56b_suppressed_after_filed_ir56f_for_the_same_income` |
| R8 | Employed before 1 May 2025, terminates 2027 → SP/LSP split; offset cannot reduce the post-transition part | `test_hong_kong_e2e.py::test_case_k_termination_through_the_service_with_frozen_wage_and_four_eyes` | `test_case_k_*`, `test_post_transition_*`, `test_390000_cap_*` |
| R9 | Sickness allowance after a mixed paid/unpaid lookback → average excludes required periods/amounts; 4/5 rate | **new** `test_r9_sickness_allowance_end_to_end_after_a_mixed_paid_unpaid_lookback` (committed Jan–May; recorded hours; SICKNESS snapshot disregards 10 unpaid + 4 part-paid days and HK$2,400; allowance = 4/5 × average × 4 days; continuous contract CONTINUOUS) | `test_sickness_allowance_from_a_lookback_with_unpaid_and_part_paid_periods`; `test_case_l_*`; `test_average_wage_blocks_*`; `test_sickness_allowance_ld_example_2_*` |
| R10 | eMPF rejects one employee row → payroll stays committed; partial/rejected; correction never rewrites history | `test_empf_rejecting_the_employee_row_keeps_the_committed_run_and_payslip_unchanged`; `test_empf_batch_partial_rejection_does_not_touch_payroll`; `test_hong_kong_corrections.py::test_submitted_empf_period_gets_a_supplementary_batch_*`; `::test_correction_appends_a_linked_delta_*` | — |

**Non-monthly pay** (named in the gate text): golden `case_d_weekly_above_maximum` / `case_d_weekly_within_levels`, and the R4 non-calendar wage period above.

**MPF contribution day (Task 3 governed deferral, [G1] UNVERIFIED rule):** `test_contribution_day_deferral_weekend_holiday_chain_and_disruption`, `test_payroll_trace_applies_the_governed_deferral_from_the_pack`, `test_recorded_signal_day_defers_the_empf_deadline_and_is_audited`, `test_the_deferral_rule_is_a_governed_unverified_value`, plus the general-holiday tests (third pass): `test_deferral_uses_only_general_holidays_and_flags_an_unloaded_list`, `test_general_holiday_loader_records_the_source_digest_and_drives_the_empf_deadline` and `test_empty_general_holiday_list_keeps_weekend_deferral_and_is_flagged`. All PASSED. The 11 golden vectors were **not edited** and still pass: their expected values are amounts only, which the contribution day does not affect.

## Tests added for this report

* Earlier pass (2026-10-13 morning): `test_case_g_unequal_hours_*`, `test_sickness_allowance_from_a_lookback_*`, `test_empf_rejecting_the_employee_row_*`.
* This pass: `test_r2_r3_*`, `test_r4_*`, `test_r5_*`, `test_r9_*` (end to end), plus the four contribution-day tests above.

Expected values come from the formulas the engine documents and cites. Wages, hours and dates in the tests are test data, not statutory values.

## Limits a reviewer should know

* Tests run on SQLite with synthetic employees. They show behaviour, not production configuration.
* The statutory figures the tests rely on (5%, HK$7,100 / 30,000, HK$42.10 / 43.10, 4/5, 60 days, 17 / 68 hours, the contribution-day deferral rule) are G1 content. They count as certified only once G1 is accepted.

## Sign-off (leave blank until reviewed)

QA reviewer — Name / Role / Date / Signature: ________
Independent Super Admin reviewer (platform) — Name / Role / Date / Signature: ________
