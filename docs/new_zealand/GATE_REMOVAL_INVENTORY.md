# New Zealand — gate-removal inventory (P0)

Plan: remove the dormancy / registry / sign-off / evidence gates and keep the documented content (Spain model, owner decision 2026-11-25). Generated from `backend/app/modules/payroll/engine/countries/new_zealand_content.py`. Read-only: nothing in code or DB changed yet.

Dispositions: **Accept** = spec value kept as-is, `[PENDING G1]` marker dropped. **P** = proposed policy value — approve or edit. **S** = public statutory value the spec does not give — filled only if you approve, otherwise stays blocked. **G** = row exists only for a removed gate — dropped. **B** = stays a narrow named calculation block until you supply a source.

## A. Documented values — accepted as-is (42)

| Key | Value | Source | Label |
|---|---|---|---|
| `nz_supported_pay_frequencies` | text=WEEKLY,FORTNIGHTLY,FOUR_WEEKLY,MONTHLY | S1 | Pay frequencies certified for calculation (spec §1) |
| `nz_acc_earner_levy_rate` | flat=1.7500 | S3 | ACC earner levy 2026-27 (% of liable earnings) |
| `nz_acc_max_liable_earnings` | flat=156641 | S3 | ACC earner levy maximum liable earnings 2026-27 (NZD) |
| `nz_ks_employee_rates` | text=3.5,4,6,8,10 | S4 | KiwiSaver employee standard contribution rates (%) |
| `nz_ks_temporary_reduction_rate` | flat=3.0000 | S4 | KiwiSaver temporary rate reduction (%) |
| `nz_ks_default_rate` | flat=3.5000 | S4 | KiwiSaver default employee rate (paydays on/after 1 Apr 2026) |
| `nz_ks_employer_min_rate` | flat=3.5000 | S4 | KiwiSaver compulsory employer contribution minimum (paydays on/after 1 Apr 2026) |
| `nz_ks_employer_min_age` | flat=16 | S4 | KiwiSaver compulsory employer contributions — from member age |
| `nz_ks_rate_selection_basis` | text=PAYDAY | S4 | KiwiSaver rate selected by (NZ-008) |
| `nz_sl_rate` | flat=12.0000 | S3 | Student-loan standard deduction rate (%) |
| `nz_sl_annual_threshold` | flat=24128 | S3 | Student-loan annual repayment threshold (NZD) |
| `nz_sl_threshold_weekly` | flat=464 | S3 | Student-loan pay-period threshold — weekly (NZD) |
| `nz_sl_threshold_fortnightly` | flat=928 | S3 | Student-loan pay-period threshold — fortnightly (NZD) |
| `nz_sl_threshold_four_weekly` | flat=1856 | S3 | Student-loan pay-period threshold — four-weekly (NZD) |
| `nz_sl_threshold_monthly` | flat=2010.66 | S3 | Student-loan pay-period threshold — monthly (NZD) |
| `nz_sl_secondary_basis` | text=WHOLE_PAYMENT | S3 | Student loan on secondary codes — deduction basis |
| `nz_cs_protected_net_pct` | flat=60.0000 | S3 | Child support — protected net earnings (% of net) |
| `nz_cs_max_deduction_pct` | flat=40.0000 | S3 | Child support — maximum deduction share (% of net) |
| `nz_min_wage_adult` | flat=23.95 | S6 | Minimum wage — adult (NZD per hour, from 1 Apr 2026) |
| `nz_min_wage_starting_out` | flat=19.16 | S6 | Minimum wage — starting-out (NZD per hour, from 1 Apr 2026) |
| `nz_min_wage_training` | flat=19.16 | S6 | Minimum wage — training (NZD per hour, from 1 Apr 2026) |
| `nz_payday_filing_working_days` | flat=2 | S2 | Electronic employment information due (working days after payday) |
| `nz_paper_filing_working_days` | flat=10 | S2 | Paper employment information due (working days after payday) |
| `nz_efiling_threshold` | flat=50000 | S2 | Electronic filing required at annual PAYE + ESCT of (NZD) |
| `nz_efiling_threshold_after_months` | flat=6 | S2 | Electronic filing threshold applies after (months as employer) |
| `nz_large_employer_threshold` | flat=500000 | S5 | Twice-monthly remittance at annual PAYE + ESCT of (NZD) |
| `nz_remit_monthly_due_day` | flat=20 | S5 | Monthly remitter — due day of the following month |
| `nz_remit_first_half_due_day` | flat=20 | S5 | Twice-monthly remitter — 1st–15th due day of the same month |
| `nz_remit_second_half_due_day` | flat=5 | S5 | Twice-monthly remitter — 16th–end due day of the following month |
| `nz_remit_december_second_half_due` | text=01-15 | S5 | Twice-monthly remitter — 16–31 December due (MM-DD) |
| `nz_hol_annual_weeks` | flat=4 | S7 | Annual holidays — weeks after each 12 months' continuous employment |
| `nz_hol_annual_qualifying_months` | flat=12 | S7 | Annual holidays — qualifying continuous employment (months) |
| `nz_hol_sick_days` | flat=10 | S7 | Sick leave — days per entitlement year |
| `nz_hol_sick_qualifying_months` | flat=6 | S7 | Sick leave — qualifying employment (months) |
| `nz_hol_sick_carry_max` | flat=20 | S7 | Sick leave — maximum balance carried over (days) |
| `nz_hol_bereavement_close_days` | flat=3 | S7 | Bereavement leave — immediate family (days) |
| `nz_hol_bereavement_other_days` | flat=1 | S7 | Bereavement leave — other qualifying bereavement (days) |
| `nz_hol_family_violence_days` | flat=10 | S7 | Family violence leave — paid days per year |
| `nz_hol_payg_pct` | flat=8.0000 | S7 | Pay-as-you-go annual holiday pay (% of gross earnings) |
| `nz_hol_cashup_max_weeks` | flat=1 | S7 | Annual holidays cash-up — maximum weeks per entitlement year |
| `nz_hol_ph_worked_multiplier` | flat=1.5 | S7 | Public holiday worked — minimum pay multiplier |
| `nz_record_retention_years` | flat=6 | S9 | Wage/time and holiday/leave records retained (years) |

## B. Policy rows and empty rows — need your decision (22)

| Key | Today | Disposition | Proposed value | Basis | Label |
|---|---|---|---|---|---|
| `nz_correction_policy` | PENDING_G1 | **P** Proposed policy | CORRECT_IN_LATER_PAYDAY_FILING | IRD: corrections in a later filing; vocab confirmed in P4 | Retro-pay and correction policy (NZ-006) |
| `nz_deduction_precedence` | PENDING_G1 | **P** Proposed policy | PAYE > STUDENT_LOAN > KIWISAVER > CHILD_SUPPORT > OTHER | statutory order; vocab confirmed in P4 | Statutory deduction precedence (NZ-011) |
| `nz_paye_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | PAYE rounding (per the IRD business rules) |
| `nz_acc_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | ACC earner levy rounding (per the IRD business rules) |
| `nz_sl_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | Student-loan deduction rounding |
| `nz_ks_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | KiwiSaver contribution rounding |
| `nz_esct_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | ESCT rounding |
| `nz_cs_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | Child-support deduction rounding |
| `nz_ks_employer_max_age` | empty | **S** Statutory value (not in spec) | 65 | NZ Super eligibility age | KiwiSaver compulsory employer contributions — up to member age |
| `nz_working_day_rule` | empty | **B** Stays blocked |  | filing rule; needs IR payday-filing spec (filing stays preview) | Payday filing — definition of a working day |
| `nz_filing_payload_version` | empty | **B** Stays blocked |  | needs IR schema; filing stays preview | Payday filing — IR payload schema version |
| `nz_hol_pay_rounding` | PENDING_G1 | **P** Proposed policy | NEAREST_CENT_HALF_UP |  | Holiday and leave pay rounding |
| `nz_hol_awe_lookback_months` | empty | **S** Statutory value (not in spec) | 12 | Holidays Act 2003 s5 (average weekly earnings) | Average weekly earnings — lookback (months) |
| `nz_hol_awe_divisor_weeks` | empty | **S** Statutory value (not in spec) | 52 | Holidays Act 2003 s5 | Average weekly earnings — divisor (weeks) |
| `nz_hol_owp_fallback_weeks` | empty | **S** Statutory value (not in spec) | 4 | Holidays Act 2003 s8(2)(b) | Ordinary weekly pay — fallback lookback (weeks) |
| `nz_hol_adp_lookback_weeks` | empty | **S** Statutory value (not in spec) | 52 | Holidays Act 2003 s9A | Average daily pay — lookback (weeks) |
| `nz_hol_owp_method` | empty | **S** Statutory value (not in spec) | AGREEMENT_THEN_FALLBACK | the only method the engine implements (s8) | Ordinary weekly pay — method |
| `nz_hol_rdp_method` | empty | **S** Statutory value (not in spec) | AGREEMENT_DAILY | the only method the engine implements (s9) | Relevant daily pay — method |
| `nz_hol_adp_use_rule` | empty | **S** Statutory value (not in spec) | RDP_UNDETERMINABLE_OR_VARIES | the only rule the engine implements (s9A) | When average daily pay replaces relevant daily pay |
| `nz_hol_final_pay_unvested_method` | empty | **S** Statutory value (not in spec) | PCT_OF_GROSS_SINCE_ANNIVERSARY | 8% rule, s23; the only method the engine implements | Final pay — holiday pay on unvested employment |
| `nz_out_of_cycle_paye_method` | empty | **S** Statutory value (not in spec) | EXTRA_PAY | IRD extra-pay method | Out-of-cycle payment — PAYE method (IRD) |
| `nz_lump_sum_paye_method` | empty | **S** Statutory value (not in spec) | EXTRA_PAY_FOUR_WEEK_ANNUALISE | IRD extra-pay method; the only method the engine implements | Lump sum / extra pay — PAYE method (IRD) |

## C. Authority tables — empty, stay blocked until you supply the source (10)

| Table | Source code | Rows |
|---|---|---|
| `paye_main_method` | S1 | 0 |
| `paye_secondary_rates` | S1 | 0 |
| `paye_nd_rate` | S1 | 0 |
| `ietc_parameters` | S1 | 0 |
| `cs_variation_codes` | S3 | 0 |
| `lump_sum_method` | S1 | 0 |
| `holiday_pay_advance_method` | S1 | 0 |
| `ird_official_examples` | S1 | 0 |
| `public_holidays` | S7 | 0 |
| `acc_employer_classifications` | None | 0 |
