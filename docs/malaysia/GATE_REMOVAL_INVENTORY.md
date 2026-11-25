# Malaysia — gate-removal inventory (P0)

Plan: remove the dormancy / registry / sign-off / evidence gates and keep the documented content (Spain model, owner decision 2026-11-25). Generated from `backend/app/modules/payroll/engine/countries/malaysia_content.py`. Read-only: nothing in code or DB changed yet.

Dispositions: **Accept** = spec value kept as-is, `[PENDING G1]` marker dropped. **P** = proposed policy value — approve or edit. **S** = public statutory value the spec does not give — filled only if you approve, otherwise stays blocked. **G** = row exists only for a removed gate — dropped. **B** = stays a narrow named calculation block until you supply a source.

## A. Documented values — accepted as-is (44)

| Key | Value | Source | Label |
|---|---|---|---|
| `my_supported_pay_frequencies` | text=MONTHLY | S2 | Pay frequencies certified in release 1 (decision D6) |
| `my_supported_contract_types` | text=CONTRACT_OF_SERVICE | S2 | Worker types in release 1 (spec §1: contracts of service) |
| `my_min_wage_monthly` | flat=1700 | S10 | Minimum wage per month (RM) |
| `my_pcb_remittance_day` | flat=15 | S2 | PCB remitted by this day of the following month |
| `my_pcb_non_resident_rate` | ee=30 | S4 | Non-resident employment income rate (%) |
| `my_tp1_retention_years` | flat=7 | S3 | TP1 document retention (years) |
| `my_epf_wage_band_threshold` | flat=5000 | S5 | EPF employer-rate wage boundary (RM) |
| `my_epf_schedule_upper_wage` | flat=20000 | S5 | Third Schedule table controls up to this wage (RM) |
| `my_epf_rate_my_pr_low` | ee=11, er=13 | S5 | EPF Malaysian/PR below 60, wages up to the boundary (%) |
| `my_epf_rate_my_pr_high` | ee=11, er=12 | S5 | EPF Malaysian/PR below 60, wages above the boundary (%) |
| `my_epf_rate_60_plus` | ee=0, er=4 | S5 | EPF Malaysian aged 60 and over (%) |
| `my_epf_rate_pr_hist_60_plus_low` | ee=5.5, er=6.5 | S5 | EPF PR / pre-1998 non-Malaysian 60+, lower band (%) |
| `my_epf_rate_pr_hist_60_plus_high` | ee=5.5, er=6 | S5 | EPF PR / pre-1998 non-Malaysian 60+, upper band (%) |
| `my_epf_rate_non_malaysian` | ee=2, er=2 | S6 | EPF non-Malaysian members after 1 Aug 1998 (%) |
| `my_epf_age_threshold` | flat=60 | S5 | EPF age at which the 60-and-over member classes apply |
| `my_socso_wage_ceiling` | flat=6000 | S7 | PERKESO Act 4 / EIS Act 800 contribution wage ceiling (RM) |
| `my_socso_employee_rate_ref` | ee=0.5 | S7 | Act 4 standard employee contribution reference (%) |
| `my_eis_rate_ref` | ee=0.2, er=0.2 | S9 | EIS contribution reference (%) |
| `my_eis_min_age` | flat=18 | S9 | EIS coverage lower age |
| `my_eis_max_age` | flat=60 | S9 | EIS coverage upper age |
| `my_fw_lindung_employee_rate` | ee=0.75 | S8 | Foreign-worker LINDUNG 24 JAM phase 1 employee component (%) |
| `my_hrd_rate_compulsory` | er=1 | S14 | HRD levy, compulsory category (%) |
| `my_hrd_rate_optional` | er=0.5 | S14 | HRD levy, optional registered category (%) |
| `my_hrd_compulsory_min_employees` | flat=10 | S14 | HRD compulsory category: Malaysian employees at least |
| `my_hrd_optional_min_employees` | flat=5 | S14 | HRD optional category: Malaysian employees at least |
| `my_cp22_days_after_start` | flat=30 | S2 | CP22 within days after employment starts |
| `my_cp22a_days_before_cessation` | flat=30 | S2 | CP22A at least days before cessation |
| `my_cp22a_days_after_death` | flat=30 | S2 | CP22A within days after learning of a death |
| `my_cp21_days_before_departure` | flat=30 | S2 | CP21 at least days before departure |
| `my_clearance_hold_max_days` | flat=90 | S2 | Tax-clearance hold, at most days |
| `my_ea_due` | text=END_FEBRUARY | S2 | EA/EC to employees |
| `my_form_e_due` | text=END_MARCH | S2 | Form E + CP8D to HASiL |
| `my_weekly_hours_max__PEN` | flat=45 | S11 | Statutory weekly working hours — PENINSULAR_LABUAN |
| `my_ot_exclusion_wage__PEN` | flat=4000 | S11 | Non-manual employees above this monthly wage (RM) excluded from overtime — PENINSULAR_LABUAN |
| `my_maternity_days__PEN` | flat=98 | S11 | Maternity leave (days) — PENINSULAR_LABUAN |
| `my_paternity_days__PEN` | flat=7 | S11 | Paternity leave (days) — PENINSULAR_LABUAN |
| `my_weekly_hours_max__SBH` | flat=45 | S12 | Statutory weekly working hours — SABAH |
| `my_ot_exclusion_wage__SBH` | flat=4000 | S12 | Non-manual employees above this monthly wage (RM) excluded from overtime — SABAH |
| `my_maternity_days__SBH` | flat=98 | S12 | Maternity leave (days) — SABAH |
| `my_paternity_days__SBH` | flat=7 | S12 | Paternity leave (days) — SABAH |
| `my_weekly_hours_max__SWK` | flat=45 | S13 | Statutory weekly working hours — SARAWAK |
| `my_ot_exclusion_wage__SWK` | flat=4000 | S13 | Non-manual employees above this monthly wage (RM) excluded from overtime — SARAWAK |
| `my_maternity_days__SWK` | flat=98 | S13 | Maternity leave (days) — SARAWAK |
| `my_paternity_days__SWK` | flat=7 | S13 | Paternity leave (days) — SARAWAK |

## B. Policy rows and empty rows — need your decision (48)

| Key | Today | Disposition | Proposed value | Basis | Label |
|---|---|---|---|---|---|
| `my_rounding_pcb` | PENDING_G1 | **B** Stays blocked |  | PCB is a stub until the HASiL spec (MY P4) | PCB statutory rounding (S1 specification) |
| `my_rounding_epf_direct` | PENDING_G1 | **P** Proposed policy | RINGGIT_UP | EPF direct calculation rounds up to the next ringgit | EPF rounding on the direct-calculation branch |
| `my_rounding_socso` | PENDING_G1 | **P** Proposed policy | SEN_HALF_UP | schedule controls; direct branch only | PERKESO rounding (schedule controls) |
| `my_rounding_eis` | PENDING_G1 | **P** Proposed policy | SEN_HALF_UP | schedule controls; direct branch only | EIS rounding (schedule controls) |
| `my_rounding_hrd` | PENDING_G1 | **P** Proposed policy | SEN_HALF_UP |  | HRD levy rounding |
| `my_min_wage_daily_rule` | PENDING_G1 | **P** Proposed policy | MINIMUM_WAGES_ORDER_2024 (by workdays per week) | vocab confirmed in P4 | Minimum wage daily equivalent rule |
| `my_min_wage_hourly_rule` | PENDING_G1 | **P** Proposed policy | MINIMUM_WAGES_ORDER_2024 (monthly x 12 / 52 / normal weekly hours) | vocab confirmed in P4 | Minimum wage hourly equivalent rule |
| `my_pcb_spec_version` | PENDING_G1 | **B** Stays blocked |  | needs HASiL computerised MTD spec | HASiL computerised MTD specification version in force |
| `my_epf_direct_calc_rule` | PENDING_G1 | **P** Proposed policy | NON_MALAYSIAN_PART_F_ONLY | only value supported | When EPF may be calculated directly instead of by table |
| `my_epf_age_transition_rule` | PENDING_G1 | **P** Proposed policy | FROM_MONTH_AFTER_BIRTHDAY | EPF: new rate the month after age 60 | Which wage month the age-60 EPF class change applies from |
| `my_eis_age_rule` | PENDING_G1 | **P** Proposed policy | AGE_AT_WAGE_MONTH_START | EIS cover 18-60 | How the EIS age bounds are measured |
| `my_fw_lindung_phase_rule` | PENDING_G1 | **B** Stays blocked |  | LINDUNG 24 JAM phase boundaries not in docs | LINDUNG 24 JAM phase boundaries and shares |
| `my_hrd_base_rule` | PENDING_G1 | **P** Proposed policy | BASIC + FIXED ALLOWANCES (PSMB Act wages) | vocab confirmed in P4 | HRD levy base inclusions / exclusions |
| `my_hrd_non_malaysian_rule` | PENDING_G1 | **P** Proposed policy | MALAYSIAN_EMPLOYEES_ONLY | PSMB levy on Malaysian employees | Whether non-Malaysian employees' wages are in the HRD levy base |
| `my_epf_due_rule` | PENDING_G1 | **P** Proposed policy | DAY_15_NEXT_MONTH | vocab confirmed in P4 | EPF contribution payment due-date rule |
| `my_socso_due_rule` | PENDING_G1 | **P** Proposed policy | DAY_15_NEXT_MONTH | vocab confirmed in P4 | PERKESO / EIS payment due-date rule |
| `my_hrd_due_rule` | PENDING_G1 | **P** Proposed policy | DAY_15_NEXT_MONTH | vocab confirmed in P4 | HRD levy payment due-date rule |
| `my_transfer_split_rule` | PENDING_G1 | **P** Proposed policy | TERRITORY_AT_PERIOD_END | only value supported | Pay-period split when a worker changes labour territory |
| `my_record_retention_years` | empty | **S** Statutory value (not in spec) | 7 | Income Tax Act / EPF records | Payroll / filing record retention (years) |
| `my_reconciliation_tolerance` | empty | **G** Remove (gate-only) |  | gate-only | Statutory reconciliation tolerance (RM) |
| `my_parallel_materiality_amount` | empty | **G** Remove (gate-only) |  | gate-only (parallel run) | Parallel-cycle materiality per employee per concept (RM) |
| `my_ot_multiplier_workday__PEN` | empty | **S** Statutory value (not in spec) | 1.5 | Employment Act s60A / Sabah and Sarawak ordinances | Overtime multiplier, normal working day — PENINSULAR_LABUAN |
| `my_ot_multiplier_rest_day__PEN` | empty | **S** Statutory value (not in spec) | 2.0 | s60(3) | Overtime multiplier, rest day — PENINSULAR_LABUAN |
| `my_ot_multiplier_public_holiday__PEN` | empty | **S** Statutory value (not in spec) | 3.0 | s60D(3) | Overtime multiplier, public holiday — PENINSULAR_LABUAN |
| `my_ot_rate_divisor_rule__PEN` | PENDING_G1 | **P** Proposed policy | MONTHLY_BASE_DIV_DAYS_DIV_DAILY_HOURS | only value supported | Ordinary / hourly rate divisor rule — PENINSULAR_LABUAN |
| `my_ot_rate_days_divisor__PEN` | empty | **S** Statutory value (not in spec) | 26 | s60I ordinary rate of pay | Days divisor for the ordinary rate of pay — PENINSULAR_LABUAN |
| `my_sick_leave_tiers__PEN` | PENDING_G1 | **P** Proposed policy | <2y 14 / 2-5y 18 / >5y 22 days | s60F; confirm for Sabah/Sarawak | Sick leave days by service tier — PENINSULAR_LABUAN |
| `my_hospitalisation_days__PEN` | empty | **S** Statutory value (not in spec) | 60 | s60F | Hospitalisation leave (days) — PENINSULAR_LABUAN |
| `my_annual_leave_tiers__PEN` | PENDING_G1 | **P** Proposed policy | <2y 8 / 2-5y 12 / >5y 16 days | s60E; confirm for Sabah/Sarawak | Annual leave days by service tier — PENINSULAR_LABUAN |
| `my_leave_pay_rule__PEN` | PENDING_G1 | **P** Proposed policy | ORDINARY_RATE_OF_PAY | s60E/F; vocab confirmed in P4 | Leave remuneration rule — PENINSULAR_LABUAN |
| `my_ot_multiplier_workday__SBH` | empty | **S** Statutory value (not in spec) | 1.5 | Employment Act s60A / Sabah and Sarawak ordinances | Overtime multiplier, normal working day — SABAH |
| `my_ot_multiplier_rest_day__SBH` | empty | **S** Statutory value (not in spec) | 2.0 | s60(3) | Overtime multiplier, rest day — SABAH |
| `my_ot_multiplier_public_holiday__SBH` | empty | **S** Statutory value (not in spec) | 3.0 | s60D(3) | Overtime multiplier, public holiday — SABAH |
| `my_ot_rate_divisor_rule__SBH` | PENDING_G1 | **P** Proposed policy | MONTHLY_BASE_DIV_DAYS_DIV_DAILY_HOURS | only value supported | Ordinary / hourly rate divisor rule — SABAH |
| `my_ot_rate_days_divisor__SBH` | empty | **S** Statutory value (not in spec) | 26 | s60I ordinary rate of pay | Days divisor for the ordinary rate of pay — SABAH |
| `my_sick_leave_tiers__SBH` | PENDING_G1 | **P** Proposed policy | <2y 14 / 2-5y 18 / >5y 22 days | s60F; confirm for Sabah/Sarawak | Sick leave days by service tier — SABAH |
| `my_hospitalisation_days__SBH` | empty | **S** Statutory value (not in spec) | 60 | s60F | Hospitalisation leave (days) — SABAH |
| `my_annual_leave_tiers__SBH` | PENDING_G1 | **P** Proposed policy | <2y 8 / 2-5y 12 / >5y 16 days | s60E; confirm for Sabah/Sarawak | Annual leave days by service tier — SABAH |
| `my_leave_pay_rule__SBH` | PENDING_G1 | **P** Proposed policy | ORDINARY_RATE_OF_PAY | s60E/F; vocab confirmed in P4 | Leave remuneration rule — SABAH |
| `my_ot_multiplier_workday__SWK` | empty | **S** Statutory value (not in spec) | 1.5 | Employment Act s60A / Sabah and Sarawak ordinances | Overtime multiplier, normal working day — SARAWAK |
| `my_ot_multiplier_rest_day__SWK` | empty | **S** Statutory value (not in spec) | 2.0 | s60(3) | Overtime multiplier, rest day — SARAWAK |
| `my_ot_multiplier_public_holiday__SWK` | empty | **S** Statutory value (not in spec) | 3.0 | s60D(3) | Overtime multiplier, public holiday — SARAWAK |
| `my_ot_rate_divisor_rule__SWK` | PENDING_G1 | **P** Proposed policy | MONTHLY_BASE_DIV_DAYS_DIV_DAILY_HOURS | only value supported | Ordinary / hourly rate divisor rule — SARAWAK |
| `my_ot_rate_days_divisor__SWK` | empty | **S** Statutory value (not in spec) | 26 | s60I ordinary rate of pay | Days divisor for the ordinary rate of pay — SARAWAK |
| `my_sick_leave_tiers__SWK` | PENDING_G1 | **P** Proposed policy | <2y 14 / 2-5y 18 / >5y 22 days | s60F; confirm for Sabah/Sarawak | Sick leave days by service tier — SARAWAK |
| `my_hospitalisation_days__SWK` | empty | **S** Statutory value (not in spec) | 60 | s60F | Hospitalisation leave (days) — SARAWAK |
| `my_annual_leave_tiers__SWK` | PENDING_G1 | **P** Proposed policy | <2y 8 / 2-5y 12 / >5y 16 days | s60E; confirm for Sabah/Sarawak | Annual leave days by service tier — SARAWAK |
| `my_leave_pay_rule__SWK` | PENDING_G1 | **P** Proposed policy | ORDINARY_RATE_OF_PAY | s60E/F; vocab confirmed in P4 | Leave remuneration rule — SARAWAK |
