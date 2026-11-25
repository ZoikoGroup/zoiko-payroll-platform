# Japan — gate-removal inventory (P0)

Plan: remove the dormancy / registry / sign-off / evidence gates and keep the documented content (Spain model, owner decision 2026-11-25). Generated from `backend/app/modules/payroll/engine/countries/japan_content.py`. Read-only: nothing in code or DB changed yet.

Dispositions: **Accept** = spec value kept as-is, `[PENDING G1]` marker dropped. **P** = proposed policy value — approve or edit. **S** = public statutory value the spec does not give — filled only if you approve, otherwise stays blocked. **G** = row exists only for a removed gate — dropped. **B** = stays a narrow named calculation block until you supply a source.

## A. Documented values — accepted as-is (36)

| Key | Value | Source | Label |
|---|---|---|---|
| `jp_supported_pay_frequencies` | text=MONTHLY | S1 | Pay frequencies certified for calculation (spec §1) |
| `jp_withholding_method` | text=COMPUTER_PRIMARY_TABLES_OTHERS | S1 | National withholding method (computer method for the primary column) |
| `jp_sba_rounding` | text=DOWN_1000 | S8 | Standard bonus amount rounding (truncate below the unit) |
| `jp_sba_rounding_unit` | flat=1000 | S8 | Standard bonus amount rounding unit (JPY) |
| `jp_epi_total` | flat=18.3000 | S6 | Employees' Pension Insurance total rate (% of SMR / SBA) |
| `jp_epi_split_rule` | text=EQUAL | S6 | Employees' Pension Insurance employee / employer split |
| `jp_epi_sba_monthly_cap` | flat=1500000 | S8 | Pension standard bonus amount cap per month (JPY) |
| `jp_kyokai_health_total_min` | flat=9.2100 | S10 | Kyokai Kenpo FY2026 prefectural health rate — lowest (validation bound) |
| `jp_kyokai_health_total_max` | flat=10.5500 | S10 | Kyokai Kenpo FY2026 prefectural health rate — highest (validation bound) |
| `jp_health_split_rule` | text=EQUAL | S10 | Health insurance employee / employer split (generally equal) |
| `jp_health_sba_annual_cap` | flat=5730000 | S8 | Health standard bonus amount cumulative annual cap (JPY) |
| `jp_kyokai_care_total` | flat=1.6200 | S12 | Kyokai Kenpo FY2026 care insurance total rate (ages 40–64) |
| `jp_care_min_age` | flat=40 | S12 | Care insurance covered population — from age |
| `jp_care_max_age` | flat=64 | S12 | Care insurance covered population — through age |
| `jp_kyokai_child_support_total` | flat=0.2300 | S11 | Kyokai Kenpo child and childcare support contribution total rate |
| `jp_child_support_split_rule` | text=EQUAL | S11 | Child and childcare support contribution split (labour-management) |
| `jp_smr_determination_months` | text=04-06 | S7 | SMR annual determination remuneration months (MM-MM) |
| `jp_smr_report_month` | text=07 | S7 | SMR annual determination report month (MM) |
| `jp_smr_application_months` | text=09-08 | S7 | New SMR applies (MM-MM, crossing the year end) |
| `jp_smr_adhoc_revision_from_month` | flat=4 | S7 | SMR ad hoc revision applies from this month after the pay change |
| `jp_ei_general` | ee=0.5000, er=0.8500 | S13 | Employment insurance FY2026 — general business (employee / employer) |
| `jp_ei_agriculture_sake_total` | flat=1.5500 | S13 | Employment insurance FY2026 — agriculture/forestry/fishery/sake total |
| `jp_ei_construction_total` | flat=1.6500 | S13 | Employment insurance FY2026 — construction total |
| `jp_statutory_hours_per_day` | flat=8 | S14 | Statutory working hours per day (baseline) |
| `jp_statutory_hours_per_week` | flat=40 | S14 | Statutory working hours per week (baseline) |
| `jp_overtime_premium_pct` | flat=25 | S14 | Statutory overtime premium — minimum (%) |
| `jp_overtime_60h_threshold_hours` | flat=60 | S14 | Monthly overtime hours above which the higher premium applies |
| `jp_overtime_over_60h_premium_pct` | flat=50 | S14 | Overtime premium above the monthly threshold — minimum (%) |
| `jp_statutory_holiday_premium_pct` | flat=35 | S14 | Statutory day-off work premium — minimum (%) |
| `jp_night_premium_pct` | flat=25 | S14 | Night work premium — minimum (%) |
| `jp_night_window` | text=22:00-05:00 | S14 | Night work window (HH:MM-HH:MM) |
| `jp_resident_tax_collection_months` | text=06-05 | S16 | Resident tax special collection months (MM-MM, June–May) |
| `jp_wht_remittance_due_day` | flat=10 | S4 | Withholding remittance due by day of the month after payment |
| `jp_si_remittance_due` | text=LAST_DAY_FOLLOWING_MONTH | S9 | Social-insurance remittance due (employee + employer portions) |
| `jp_bonus_report_days` | flat=5 | S8 | JPS bonus payment report due within (days of payment) |
| `jp_statutory_reports_due` | text=01-31 | S5 | Withholding slips / salary payment reports due (MM-DD, following year) |

## B. Policy rows and empty rows — need your decision (22)

| Key | Today | Disposition | Proposed value | Basis | Label |
|---|---|---|---|---|---|
| `jp_correction_policy` | PENDING_G1 | **P** Proposed policy | DELTA_PAYSLIP | only value the engine supports | Japanese retro-pay and correction policy (JP-006) |
| `jp_wht_cmp_basic_deduction` | empty | **B** Stays blocked |  | not in docs | NTA computer method — basic employment-income deduction (JPY) |
| `jp_wht_cmp_dependant_deduction` | empty | **B** Stays blocked |  | not in docs | NTA computer method — deduction per dependant (JPY) |
| `jp_wht_bonus_special_multiple` | empty | **B** Stays blocked |  | not in docs | NTA bonus method — prior-month pay multiple for the special calculation |
| `jp_wht_rounding` | PENDING_G1 | **B** Stays blocked |  | NTA computer method rounds to 10 yen half-up; irrelevant until NTA tables are supplied | Withholding tax rounding (per the certified NTA method) |
| `jp_si_employee_share_rounding` | PENDING_G1 | **P** Proposed policy | HALF_DOWN (<=0.50 yen down, >0.50 up) | statutory 50-sen rule; needs one vocab entry (HALF_DOWN) added in P4 | Social-insurance employee share rounding |
| `jp_ei_employee_share_rounding` | PENDING_G1 | **P** Proposed policy | HALF_DOWN (<=0.50 yen down, >0.50 up) | same 50-sen rule; vocab entry added in P4 | Employment-insurance employee share rounding |
| `jp_care_split_rule` | PENDING_G1 | **P** Proposed policy | EQUAL | employee/employer 50:50 | Care insurance employee / employer split |
| `jp_smr_min_payment_base_days` | empty | **B** Stays blocked |  | not in docs | SMR — minimum payment base days for a month to count |
| `jp_smr_adhoc_grade_gap` | empty | **B** Stays blocked |  | not in docs | SMR ad hoc revision — minimum grade difference |
| `jp_ei_agriculture_sake` | empty | **B** Stays blocked |  | not in docs | Employment insurance FY2026 — agriculture/sake split (not stated by the spec) |
| `jp_ei_construction` | empty | **B** Stays blocked |  | not in docs | Employment insurance FY2026 — construction split (not stated by the spec) |
| `jp_premium_combination_rule` | PENDING_G1 | **P** Proposed policy | ADDITIVE (OT 25%+night 25% = 50%; holiday 35%+night 25% = 60%) | Labour Standards Act art. 37; vocab confirmed in P4 | How overtime, holiday and night premiums combine |
| `jp_holiday_substitute_rule` | PENDING_G1 | **B** Stays blocked |  | employer work-rules choice; blocks only substitute-holiday cases | When a statutory holiday is substituted for another day |
| `jp_wht_due_non_business_day_rule` | PENDING_G1 | **P** Proposed policy | NEXT_BUSINESS_DAY | General Act of National Taxes art. 10(2) | Withholding due date on a non-business day |
| `jp_yea_income_limit` | empty | **B** Stays blocked |  | not in docs | Year-end adjustment — annual pay above which the employee is excluded (JPY) |
| `jp_yea_earthquake_cap` | empty | **B** Stays blocked |  | not in docs | Year-end adjustment — earthquake insurance premium deduction cap (JPY) |
| `jp_reconstruction_surtax_pct` | empty | **S** Statutory value (not in spec) | 2.1 | Special reconstruction income tax 2.1% (to 2037) | Special reconstruction income tax (% of the income tax) |
| `jp_yea_taxable_rounding` | PENDING_G1 | **P** Proposed policy | DOWN_1000 | taxable income rounded down to 1,000 yen | Year-end adjustment — taxable income rounding |
| `jp_yea_rounding` | PENDING_G1 | **P** Proposed policy | DOWN_100 | annual tax rounded down to 100 yen | Year-end adjustment — annual tax rounding |
| `jp_yea_earliest_month` | PENDING_G1 | **P** Proposed policy | 12 | YEA in the last pay of the year | Year-end adjustment — earliest pay month it may be applied in (MM) |
| `jp_resident_tax_remittance_due_day` | empty | **S** Statutory value (not in spec) | 10 | special collection remitted by the 10th of the following month | Resident tax special collection remitted by day of the following month |

## C. Authority tables — empty, stay blocked until you supply the source (10)

| Table | Source code | Rows |
|---|---|---|
| `wht_monthly_table` | S1 | 0 |
| `wht_computer_method` | S1 | 0 |
| `wht_bonus_rate_table` | S1 | 0 |
| `year_end_adjustment` | S3 | 0 |
| `smr_grades_health` | S7 | 0 |
| `smr_grades_pension` | S7 | 0 |
| `kyokai_health_rates` | S10 | 0 |
| `minimum_wage` | S15 | 0 |
| `public_holidays` | S14 | 0 |
| `workers_comp_rates` | None | 0 |
