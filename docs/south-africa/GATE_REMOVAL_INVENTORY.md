# South Africa — gate-removal inventory (P0)

Plan: remove the dormancy / registry / sign-off / evidence gates and keep the documented content (Spain model, owner decision 2026-11-25). Generated from `backend/app/modules/payroll/engine/countries/south_africa_content.py`. Read-only: nothing in code or DB changed yet.

Dispositions: **Accept** = spec value kept as-is, `[PENDING G1]` marker dropped. **P** = proposed policy value — approve or edit. **S** = public statutory value the spec does not give — filled only if you approve, otherwise stays blocked. **G** = row exists only for a removed gate — dropped. **B** = stays a narrow named calculation block until you supply a source.

## A. Documented values — accepted as-is (36)

| Key | Value | Source | Label |
|---|---|---|---|
| `za_supported_pay_frequencies` | text=MONTHLY | S1 | Pay frequencies certified for calculation (spec §1) |
| `za_rounding_mode` | text=HALF_UP | S3 | ZAR rounding mode for statutory amounts |
| `za_rounding_precision` | flat=2 | S3 | ZAR rounding precision (decimals) |
| `za_rebate_primary` | flat=17820 | S2 | PAYE primary rebate (annual) |
| `za_rebate_secondary` | flat=9765 | S2 | PAYE secondary rebate, age 65+ (annual) |
| `za_rebate_tertiary` | flat=3249 | S2 | PAYE tertiary rebate, age 75+ (annual) |
| `za_rebate_secondary_age` | flat=65 | S2 | Age from which the secondary rebate applies |
| `za_rebate_tertiary_age` | flat=75 | S2 | Age from which the tertiary rebate applies |
| `za_mtc_main_member` | flat=376 | S3 | Medical scheme fees tax credit — taxpayer (monthly) |
| `za_mtc_first_dependant` | flat=376 | S3 | Medical scheme fees tax credit — first dependant (monthly) |
| `za_mtc_additional_dependant` | flat=254 | S3 | Medical scheme fees tax credit — each additional dependant (monthly) |
| `za_retirement_deduction_pct` | ee=27.5000 | S1 | Retirement fund deduction (% of remuneration or taxable income) |
| `za_retirement_annual_cap` | flat=430000 | S1 | Retirement fund deduction annual cap |
| `za_travel_inclusion_default_pct` | ee=80.0000 | S1 | Fixed travel allowance included in PAYE remuneration |
| `za_travel_inclusion_business_pct` | ee=20.0000 | S1 | Fixed travel allowance inclusion where >= 80% business use |
| `za_travel_business_use_min_pct` | ee=80.0000 | S1 | Business-use share that qualifies for the reduced inclusion |
| `za_uif` | ee=1.0000, er=1.0000 | S6 | UIF contribution (employee / employer) |
| `za_uif_monthly_ceiling` | flat=17712 | S6 | UIF monthly remuneration ceiling |
| `za_sdl` | er=1.0000 | S7 | Skills Development Levy (employer only) |
| `za_sdl_exemption_threshold` | flat=500000 | S7 | SDL exemption — annual leviable remuneration not exceeding |
| `za_eti_hours_normaliser` | flat=160 | S8 | ETI hours normaliser (paid hours per month) |
| `za_eti_qualifying_months_max` | flat=24 | S8 | ETI maximum qualifying months per employee |
| `za_eti_min_age` | flat=18 | S8 | ETI minimum employee age |
| `za_eti_max_age` | flat=29 | S8 | ETI maximum employee age |
| `za_nmw_hourly` | flat=30.23 | S9 | National Minimum Wage (per ordinary hour) |
| `za_bcea_earnings_threshold` | flat=269900.90 | S10 | BCEA earnings threshold (annual, specified working-time sections) |
| `za_emp201_due_day` | flat=7 | S1 | EMP201 payment and declaration due by day of following month |
| `za_emp201_non_business_day_rule` | text=PRECEDING_BUSINESS_DAY | S1 | EMP201 due date on a weekend or public holiday |
| `za_brs_version` | text=25.3.0 | S4 | SARS PAYE reconciliation BRS version (202608 interim period) |
| `za_record_retention_years` | flat=5 | S14 | SARS payroll/tax record retention (years, minimum) |
| `za_emp501_interim_months` | text=03-08 | S5 | EMP501 interim reconciliation months (MM-MM) |
| `za_emp501_interim_window_open` | text=2026-09-21 | S5 | EMP501 interim submission window opens |
| `za_emp501_interim_window_close` | text=2026-10-31 | S5 | EMP501 interim submission window closes |
| `za_emp501_annual_close` | text=05-31 | S1 | EMP501 annual reconciliation closes (MM-DD) |
| `za_reconciliation_tolerance` | flat=0 | S5 | EMP501 balancing tolerance per month (ZAR) |
| `za_deduction_authority_types` | text=STATUTORY,COURT_ORDER,CONSENT,COLLECTIVE | S11 | Recognised authorities for a non-statutory payroll deduction |

## B. Policy rows and empty rows — need your decision (10)

| Key | Today | Disposition | Proposed value | Basis | Label |
|---|---|---|---|---|---|
| `za_paye_tax_year_date_basis` | PENDING_G1 | **P** Proposed policy | PAYMENT_DATE | PAYE applies on the date paid | Date that selects the PAYE tax year (ZA-006) |
| `za_variable_remuneration_basis` | PENDING_G1 | **P** Proposed policy | PAYMENT_DATE | s7B: accrues when paid | Section 7B variable remuneration timing (ZA-006) |
| `za_eti_offset_policy` | PENDING_G1 | **P** Proposed policy | OFFSET_UP_TO_PAYE | ETI offset against PAYE on EMP201 | ETI offset against the EMP201 PAYE remittance |
| `za_bcea_overtime_multiplier` | empty | **S** Statutory value (not in spec) | 1.5 | BCEA s10(2) | BCEA overtime pay multiplier (not stated by the spec) |
| `za_bcea_sunday_multiplier` | empty | **S** Statutory value (not in spec) | 2.0 | BCEA s16 (1.5 if the employee ordinarily works Sundays; engine holds one value) | BCEA Sunday work multiplier (not stated by the spec) |
| `za_bcea_public_holiday_multiplier` | empty | **S** Statutory value (not in spec) | 2.0 | BCEA s18(3) | BCEA public-holiday work multiplier (not stated by the spec) |
| `za_damage_deduction_limit_pct` | empty | **S** Statutory value (not in spec) | 25 | BCEA s34(2)(c): max one quarter of net pay | Damage / loss deduction limit (% of pay; not stated by the spec) |
| `za_four_eyes_variable_pay_pct` | empty | **G** Remove (gate-only) |  | four-eyes gate | Variable pay above this % of salary needs a second approver (ZA-016) |
| `za_four_eyes_bank_change_days` | empty | **G** Remove (gate-only) |  | four-eyes gate | Bank change within this many days of pay day needs a second approver |
| `za_parallel_materiality_amount` | empty | **G** Remove (gate-only) |  | gate-only (parallel run) | Parallel-cycle materiality threshold per employee per concept (ZAR) |
