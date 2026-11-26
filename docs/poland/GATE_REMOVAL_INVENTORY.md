# Poland — gate-removal inventory (P0)

Plan: remove the dormancy / registry / sign-off / evidence gates and keep the documented content (Spain model, owner decision 2026-11-25). Generated from `backend/app/modules/payroll/engine/countries/poland_content.py`. Read-only: nothing in code or DB changed yet.

Dispositions: **Accept** = spec value kept as-is, `[PENDING G1]` marker dropped. **P** = proposed policy value — approve or edit. **S** = public statutory value the spec does not give — filled only if you approve, otherwise stays blocked. **G** = row exists only for a removed gate — dropped. **B** = stays a narrow named calculation block until you supply a source.

## A. Documented values — accepted as-is (51)

| Key | Value | Source | Label |
|---|---|---|---|
| `pl_supported_pay_frequencies` | text=MONTHLY | S10 | Pay frequencies certified for calculation (spec §1, §8) |
| `pl_supported_contract_types` | text=UMOWA_O_PRACE | S3 | Contract types in the first certified release (spec §1) |
| `pl_pit_social_deduction_rule` | text=EMPLOYEE_SOCIAL_ONLY | S3 | Social contributions deductible for PIT (spec §4) |
| `pl_health_base_rule` | text=GROSS_LESS_EMPLOYEE_SOCIAL | S7 | Health contribution base (spec §2, §5) |
| `pl_min_wage_monthly` | flat=4806 | S1 | Minimum monthly wage, full-time (PLN) |
| `pl_min_hourly_civil` | flat=31.40 | S2 | Minimum hourly rate, covered civil-law services (PLN) |
| `pl_pay_deadline_day` | flat=10 | S10 | Monthly pay due by this day of the following month |
| `pl_pit_tax_free_amount` | flat=30000 | S4 | PIT tax-free amount (annual, PLN) |
| `pl_pit_tax_reducing_annual` | flat=3600 | S4 | PIT tax-reducing amount (annual, PLN) |
| `pl_pit2_reduction_full` | flat=300 | S4 | PIT-2 monthly reduction, one payer (PLN) |
| `pl_pit2_reduction_half` | flat=150 | S4 | PIT-2 monthly reduction, half allocation (PLN) |
| `pl_pit2_reduction_third` | flat=100 | S4 | PIT-2 monthly reduction, third allocation (PLN) |
| `pl_costs_standard_monthly` | flat=250 | S3 | Standard employee deductible costs (monthly, PLN) |
| `pl_costs_commuter_monthly` | flat=300 | S3 | Commuter employee deductible costs (monthly, PLN) |
| `pl_zus_emerytalne` | ee=9.7600, er=9.7600 | S5 | Old-age pension contribution (employee / employer) |
| `pl_zus_rentowe` | ee=1.5000, er=6.5000 | S5 | Disability contribution (employee / employer) |
| `pl_zus_chorobowe` | ee=2.4500 | S5 | Sickness contribution (employee, mandatory employment cover) |
| `pl_zus_wypadkowe_min` | er=0.6700 | S5 | Accident contribution — lowest employer rate |
| `pl_zus_wypadkowe_max` | er=3.3300 | S5 | Accident contribution — highest employer rate |
| `pl_zus_wypadkowe_small_payer` | er=1.6700 | S5 | Accident contribution — small / non-REGON payer rate |
| `pl_zus_contribution_year_start` | text=04-01 | S6 | Accident-rate contribution year starts (1 Apr - 31 Mar) |
| `pl_zus_annual_cap` | flat=282600 | S6 | Pension/disability annual base limit (30x, PLN) |
| `pl_health` | ee=9.0000 | S7 | Health contribution (employee-funded) |
| `pl_fp_fs` | er=2.4500 | S5 | Labour Fund / Solidarity Fund (FP/FS), employer |
| `pl_fgsp` | er=0.1000 | S12 | Guaranteed Employee Benefits Fund (FGSP), employer |
| `pl_fep` | er=1.5000 | S12 | Bridging Pension Fund (FEP), employer, qualifying work only |
| `pl_ppk_employee_basic` | ee=2.0000 | S9 | PPK employee basic contribution |
| `pl_ppk_employee_reduced_min` | ee=0.5000 | S9 | PPK reduced employee basic contribution, minimum |
| `pl_ppk_reduced_income_pct_min_wage` | ee=120.0000 | S9 | PPK reduced rate: monthly income limit, % of minimum wage |
| `pl_ppk_employee_additional_max` | ee=2.0000 | S9 | PPK employee additional contribution, maximum |
| `pl_ppk_employer_basic` | er=1.5000 | S9 | PPK employer basic contribution |
| `pl_ppk_employer_additional_max` | er=2.5000 | S9 | PPK employer additional contribution, maximum |
| `pl_ppk_transfer_day` | flat=15 | S9 | PPK transfer due by this day of the following month |
| `pl_working_hours_daily` | flat=8 | S10 | Standard working time (hours per day) |
| `pl_working_hours_weekly_avg` | flat=40 | S10 | Standard working time (average hours per week) |
| `pl_overtime_premium_standard` | ee=50.0000 | S10 | Overtime premium on normal pay, standard case |
| `pl_overtime_premium_high` | ee=100.0000 | S10 | Overtime premium on normal pay, statutory high case |
| `pl_leave_days_base` | flat=20 | S10 | Annual leave days, service credit under the senior threshold |
| `pl_leave_days_senior` | flat=26 | S10 | Annual leave days, service credit at/over the senior threshold |
| `pl_leave_service_years_senior` | flat=10 | S10 | Service credit (years) for the higher leave tier |
| `pl_sick_employer_days` | flat=33 | S10 | Employer-paid sick days per calendar year |
| `pl_sick_employer_days_older` | flat=14 | S10 | Employer-paid sick days per year, older employee |
| `pl_sick_older_age_threshold` | flat=50 | S10 | Age above which the shorter employer period applies |
| `pl_sick_rate_standard` | ee=80.0000 | S10 | Employer sick pay, standard rate (% of base) |
| `pl_sick_rate_full` | ee=100.0000 | S10 | Employer sick pay, full rate for statutory cases (% of base) |
| `pl_sick_full_rate_cases` | text=ROUTE_ACCIDENT,PREGNANCY,DONOR | S10 | Cases paid at the full sick-pay rate |
| `pl_zus_due_day_classes` | text=5,15,20 | S8 | ZUS DRA filing/payment day by payer class |
| `pl_pit11_authority_due` | text=END_JANUARY | S11 | PIT-11 to the tax office |
| `pl_pit11_employee_due` | text=END_FEBRUARY | S11 | PIT-11 to the employee |
| `pl_pit4r_due` | text=END_JANUARY | S11 | PIT-4R annual payer declaration |
| `pl_pit8ar_due` | text=END_JANUARY | S11 | PIT-8AR annual payer declaration |

## B. Policy rows and empty rows — need your decision (25)

| Key | Today | Disposition | Proposed value | Basis | Label |
|---|---|---|---|---|---|
| `pl_health_limitation_rule` | PENDING_G1 | **P** Proposed policy | NONE | no limitation since 2022; only value supported | Health contribution limitation rule (not in spec) |
| `pl_rounding_pit` | PENDING_G1 | **P** Proposed policy | FULL_PLN_HALF_UP | Tax Ordinance art. 63 | PIT advance rounding (PL-004) |
| `pl_rounding_zus` | PENDING_G1 | **P** Proposed policy | GROSZ_HALF_UP |  | ZUS social contribution rounding (PL-004) |
| `pl_rounding_health` | PENDING_G1 | **P** Proposed policy | GROSZ_HALF_UP |  | Health contribution rounding (PL-004) |
| `pl_rounding_ppk` | PENDING_G1 | **P** Proposed policy | GROSZ_HALF_UP |  | PPK contribution rounding (PL-004) |
| `pl_costs_standard_annual_cap` | empty | **S** Statutory value (not in spec) | 3000.00 | PIT Act art. 22(2) | Standard costs annual cap, one employment (PLN) |
| `pl_costs_standard_multi_annual_cap` | empty | **S** Statutory value (not in spec) | 4500.00 | PIT Act art. 22(2) | Standard costs annual cap, multiple employments (PLN) |
| `pl_costs_commuter_annual_cap` | empty | **S** Statutory value (not in spec) | 3600.00 | PIT Act art. 22(2) | Commuter costs annual cap, one employment (PLN) |
| `pl_costs_commuter_multi_annual_cap` | empty | **S** Statutory value (not in spec) | 5400.00 | PIT Act art. 22(2) | Commuter costs annual cap, multiple employments (PLN) |
| `pl_pit0_annual_limit` | empty | **S** Statutory value (not in spec) | 85528.00 | PIT Act art. 21 (PIT-0 reliefs) | PIT-0 reliefs shared annual exempt-income limit (PLN) |
| `pl_fp_fs_min_base_rule` | PENDING_G1 | **P** Proposed policy | BASE_AT_LEAST_MIN_WAGE | FP/FS due only when base >= minimum wage | FP/FS minimum-base applicability test |
| `pl_fund_cap_rule` | PENDING_G1 | **P** Proposed policy | CAPPED_WITH_PENSION_BASE | same base as pension/disability (30x cap) | FP/FS and FGSP base: with or without the 30x cap (not in spec) |
| `pl_fund_exemption_rules` | PENDING_G1 | **P** Proposed policy | STATUTORY (age 55F/60M; 36 months after parental leave; 12 months new hire under 30) | vocab confirmed in P4 | Age / return-to-work employer-fund exemptions |
| `pl_ppk_reenrolment_cycle_years` | empty | **S** Statutory value (not in spec) | 4 | PPK Act art. 23(4) | PPK auto re-enrolment cycle (years) |
| `pl_ppk_employer_pit_treatment` | PENDING_G1 | **P** Proposed policy | TAXABLE_EMPLOYEE_INCOME | employer PPK is employee taxable income | PIT treatment of the employer PPK contribution (not in spec) |
| `pl_overtime_premium_map` | PENDING_G1 | **P** Proposed policy | DAILY 50% (100% night/Sunday/holiday); WEEKLY 100%; SUNDAY_HOLIDAY 100%; COMP_TIME_FAILED 100% | Labour Code art. 151(1); vocab confirmed in P4 | Overtime event kind -> premium (spec §8, not given) |
| `pl_night_supplement_basis` | PENDING_G1 | **P** Proposed policy | 20% of hourly minimum-wage rate | Labour Code art. 151(8); vocab currently empty, entry added in P4 | Night-work supplement basis |
| `pl_leave_part_time_rounding` | PENDING_G1 | **P** Proposed policy | ROUND_UP_FULL_DAY | Labour Code art. 154(2) | Part-time annual leave rounding (not in spec) |
| `pl_leave_pay_reference_rule` | PENDING_G1 | **P** Proposed policy | 3 months for variable components | Leave Pay Regulation; vocab confirmed in P4 | Leave remuneration reference-period rule |
| `pl_sick_age_rule` | PENDING_G1 | **P** Proposed policy | FROM_YEAR_AFTER_REACHING_AGE | Labour Code art. 92 (age 50) | How the shorter employer sick-pay period's age test is applied (not in spec) |
| `pl_benefit_reference_months` | empty | **S** Statutory value (not in spec) | 12 | Sickness Benefits Act art. 36 | Benefit base reference period (months) |
| `pl_pit_remittance_due_rule` | PENDING_G1 | **P** Proposed policy | DAY_20_NEXT_MONTH | PIT Act art. 38; vocab confirmed in P4 | PIT advance remittance due-date rule |
| `pl_record_retention_years` | empty | **S** Statutory value (not in spec) | 10 | employee files / ZUS records | Payroll / filing record retention (years) |
| `pl_reconciliation_tolerance` | empty | **G** Remove (gate-only) |  | gate-only (G4) | Statutory reconciliation tolerance (PLN) |
| `pl_parallel_materiality_amount` | empty | **G** Remove (gate-only) |  | gate-only (parallel run) | Parallel-cycle materiality per employee per concept (PLN) |
