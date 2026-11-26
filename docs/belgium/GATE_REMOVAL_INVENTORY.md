# Belgium — gate-removal inventory (P0)

Plan: remove the dormancy / registry / sign-off / evidence gates and keep the documented content (Spain model, owner decision 2026-11-25). Generated from `backend/app/modules/payroll/engine/countries/belgium_content.py`. Read-only: nothing in code or DB changed yet.

Dispositions: **Accept** = spec value kept as-is, `[PENDING G1]` marker dropped. **P** = proposed policy value — approve or edit. **S** = public statutory value the spec does not give — filled only if you approve, otherwise stays blocked. **G** = row exists only for a removed gate — dropped. **B** = stays a narrow named calculation block until you supply a source.

## Note
Belgium stores **no** values: seeded rows are empty and the spec figures exist only as display text (`SPEC_PROPOSED`). Under the Spain model these spec figures become real row values in P4. Spec text that is a range or a note rather than one value (e.g. `17-19 weeks`, `indefinite or >= 3 months`, public holidays `dates none in spec`) needs your exact value.

## A. Spec values to promote into rows (31)

| Key | Group | Kind | Spec text |
|---|---|---|---|
| `be_supported_worker_categories` | policy | text-choice | MANUAL,EMPLOYEE (special regimes blocked) |
| `be_onss_employee_rate` | onss_employee | rate | 13.07% ordinary |
| `be_onss_manual_base_uplift` | onss_employee | rate | 108% (gross + 8%) |
| `be_onss_manual_base_categories` | onss_employee | text-choice | MANUAL + assimilated |
| `be_onss_employer_base_rate` | onss_employer | band | 24.92% globalised base |
| `be_onss_special_160` | onss_employer | rate | 1.60% |
| `be_onss_pension_special` | onss_employer | rate | 8.86% |
| `be_hol_entitlement_weeks` | holiday | amount | 4 weeks max |
| `be_hol_wc_double_pct` | holiday | rate | 92% of monthly wage |
| `be_hol_manual_quarterly_contribution` | holiday | rate | 5.57% quarterly |
| `be_hol_manual_annual_debit` | holiday | rate | 10.27% annual debit |
| `be_wage_rmmmg` | wages | amount | EUR 2,233.61 from 1 Jul 2026 |
| `be_wage_rmmmg_min_age` | wages | amount | 18 |
| `be_wage_index_centime_threshold` | wages | amount | EUR 4,000 from 1 Jun 2026 |
| `be_wage_norm_margin` | wages | rate | 0% (2025-2026) |
| `be_wt_daily_limit_hours` | working_time | amount | 8 |
| `be_wt_weekly_limit_hours` | working_time | amount | 40 |
| `be_wt_weekly_reduced_hours` | working_time | amount | 38 |
| `be_ot_premium_weekday` | working_time | rate | 50% |
| `be_ot_premium_sunday_holiday` | working_time | rate | 100% |
| `be_abs_wc_guaranteed_days` | absence | amount | 30 days |
| `be_abs_wc_guaranteed_pct` | absence | rate | 100% |
| `be_abs_wc_min_contract_months` | absence | amount | indefinite or >= 3 months |
| `be_abs_relapse_window_weeks` | absence | amount | 8 weeks (from 1 Jan 2026) |
| `be_abs_maternity_weeks` | absence | amount | 15 weeks |
| `be_abs_maternity_multiple_weeks` | absence | band | 17-19 weeks (multiple birth) |
| `be_abs_birth_leave_days` | absence | amount | 20 days |
| `be_abs_birth_leave_window_months` | absence | amount | 4 months |
| `be_abs_birth_leave_employer_days` | absence | amount | 3 days |
| `be_public_holidays` | holidays | table | ten statutory holidays; dates none in spec (G-09) |
| `be_filing_dmfa_schema_versions` | filing | schema-version | 2026/2 to 30 Sep, 2026/3 from 1 Oct |

## B. Gate-only rows — remove (6)

- `be_parallel_tolerance_gross` — Parallel-run tolerance: gross (EUR)
- `be_parallel_tolerance_withholding` — Parallel-run tolerance: withholding (EUR)
- `be_parallel_tolerance_onss_employee` — Parallel-run tolerance: employee ONSS (EUR)
- `be_parallel_tolerance_work_bonus_social` — Parallel-run tolerance: social work bonus (EUR)
- `be_parallel_tolerance_net` — Parallel-run tolerance: net pay (EUR)
- `be_parallel_tolerance_employer_onss` — Parallel-run tolerance: employer contributions (EUR)

## C. No value in any doc — stays blocked until you supply a source (46)

| Key | Group | Kind | Label |
|---|---|---|---|
| `be_supported_pay_frequencies` | policy | text-choice | Supported pay frequencies |
| `be_supported_pay_bases` | policy | text-choice | Supported pay bases (salaried / hourly) |
| `be_supported_contract_types` | policy | text-choice | Supported contract types |
| `be_rounding_onss` | policy | text-choice | ONSS rounding rule |
| `be_rounding_withholding` | policy | text-choice | Professional withholding rounding rule |
| `be_rounding_holiday` | policy | text-choice | Holiday pay rounding rule |
| `be_bssc_pending` | policy | text-choice | Special social security contribution (awaiting specialist) |
| `be_wht_applicability_rule` | withholding | text-choice | Withholding applicability |
| `be_wht_nonresident_rule` | withholding | text-choice | Non-resident withholding treatment |
| `be_wht_taxable_basis_rule` | withholding | text-choice | Withholding taxable basis |
| `be_wht_period_strategy` | withholding | text-choice | Withholding period strategy |
| `be_wht_annex3_regular_scale` | withholding | band | Annex III regular withholding scale |
| `be_wht_annex3_amendment_2026` | withholding | formula | Annex III amendments (RD 24 Jul 2026) |
| `be_wht_family_reductions` | withholding | band | Family / reduction layer |
| `be_wht_fiscal_work_bonus` | withholding | formula | Fiscal work bonus |
| `be_wht_exceptional_rule` | withholding | band | Exceptional remuneration withholding |
| `be_wht_holiday_pay_rule` | withholding | formula | Holiday pay withholding |
| `be_wht_arrears_rule` | withholding | formula | Arrears withholding |
| `be_wht_overtime_rule` | withholding | formula | Overtime withholding changes |
| `be_onss_employee_base_rule` | onss_employee | text-choice | Employee ONSS base rule |
| `be_onss_supported_employer_categories` | onss_employer | text-choice | Supported ONSS employer categories |
| `be_onss_supported_worker_codes` | onss_employer | text-choice | Supported ONSS worker codes |
| `be_onss_rate_file_quarter` | onss_employer | date | ONSS rate file quarter |
| `be_onss_wage_moderation` | onss_employer | rate | Wage moderation contribution |
| `be_onss_special_160_threshold_rule` | onss_employer | text-choice | Special contribution workforce test |
| `be_onss_company_car` | onss_employer | formula | Company car contribution |
| `be_onss_fund_contributions` | onss_employer | band | Fund contributions |
| `be_red_social_work_bonus` | reductions | band | Social work bonus |
| `be_red_structural` | reductions | formula | Structural reduction |
| `be_red_target_group` | reductions | band | Target-group reductions |
| `be_hol_wc_simple_rule` | holiday | text-choice | White-collar simple holiday pay |
| `be_hol_wc_double_contribution_rule` | holiday | text-choice | Double holiday pay contribution rule |
| `be_hol_additional_rule` | holiday | formula | Additional holidays |
| `be_hol_departure_rule` | holiday | formula | Departure holiday pay |
| `be_wage_index_centime_rule` | wages | formula | Index-centime limitation rule |
| `be_ot_threshold_rule` | working_time | text-choice | Overtime threshold rule |
| `be_ot_compensatory_rest_rule` | working_time | formula | Compensatory rest rule |
| `be_abs_manual_day_bands` | absence | band | Manual-worker guaranteed salary day bands |
| `be_abs_manual_insurance_cap` | absence | amount | Manual-worker insurance cap |
| `be_public_holiday_substitution_rule` | holidays | text-choice | Public holiday substitution |
| `be_bik_valuation_rules` | earning_class | formula | Benefit-in-kind valuation |
| `be_meal_voucher_treatment` | earning_class | text-choice | Meal voucher treatment |
| `be_ecocheque_treatment` | earning_class | text-choice | Ecocheque treatment |
| `be_filing_dimona_schema_versions` | filing | schema-version | Dimona schema versions |
| `be_filing_finprof_schema_versions` | filing | schema-version | FinProf schema versions |
| `be_filing_belcotax_schema_versions` | filing | schema-version | Belcotax fiche schema versions |

`docs/belgium/content/BE_2026_AI_DRAFT.xlsx` is an AI draft and is **not** used unless you say so.
