-- ============================================================================
-- READ-ONLY. This file contains SELECT statements only: it reads the Belgian
-- packs, their catalogue rows and slab rows, and their audit trail. It writes,
-- updates or deletes NOTHING. Run it with a read-only database role.
-- Purpose: see exactly what each Belgian pack holds (rows per catalogue group,
-- signed vs [PENDING G1], with a value, with a source; slab rows per key).
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/readonly/be_pack_inventory.sql
-- The catalogue VALUES lists are generated from
-- backend/app/modules/payroll/engine/countries/belgium_content.py (83 keys).
-- ============================================================================

-- 1. The Belgian packs and their stored tax year vs. dates.
SELECT id, pack_id, version, status, tax_year, effective_from, effective_to, previous_version_id,
       approved_by_id, created_at
FROM payroll_jurisdiction_packs WHERE jurisdiction_country = 'BE' ORDER BY pack_id, version;

-- 2. Canonical scalar rows per pack and catalogue group: linked rows, signed vs pending,
--    rows with a value, rows with a source.
WITH catalogue(component_key, grp, kind) AS (VALUES
    ('be_supported_pay_frequencies', 'policy', 'text-choice'),
    ('be_supported_pay_bases', 'policy', 'text-choice'),
    ('be_supported_worker_categories', 'policy', 'text-choice'),
    ('be_supported_contract_types', 'policy', 'text-choice'),
    ('be_rounding_onss', 'policy', 'text-choice'),
    ('be_rounding_withholding', 'policy', 'text-choice'),
    ('be_rounding_holiday', 'policy', 'text-choice'),
    ('be_bssc_pending', 'policy', 'text-choice'),
    ('be_wht_applicability_rule', 'withholding', 'text-choice'),
    ('be_wht_nonresident_rule', 'withholding', 'text-choice'),
    ('be_wht_taxable_basis_rule', 'withholding', 'text-choice'),
    ('be_wht_period_strategy', 'withholding', 'text-choice'),
    ('be_wht_annex3_regular_scale', 'withholding', 'band'),
    ('be_wht_annex3_amendment_2026', 'withholding', 'formula'),
    ('be_wht_family_reductions', 'withholding', 'band'),
    ('be_wht_fiscal_work_bonus', 'withholding', 'formula'),
    ('be_wht_exceptional_rule', 'withholding', 'band'),
    ('be_wht_holiday_pay_rule', 'withholding', 'formula'),
    ('be_wht_arrears_rule', 'withholding', 'formula'),
    ('be_wht_overtime_rule', 'withholding', 'formula'),
    ('be_onss_employee_rate', 'onss_employee', 'rate'),
    ('be_onss_employee_base_rule', 'onss_employee', 'text-choice'),
    ('be_onss_manual_base_uplift', 'onss_employee', 'rate'),
    ('be_onss_manual_base_categories', 'onss_employee', 'text-choice'),
    ('be_onss_supported_employer_categories', 'onss_employer', 'text-choice'),
    ('be_onss_supported_worker_codes', 'onss_employer', 'text-choice'),
    ('be_onss_rate_file_quarter', 'onss_employer', 'date'),
    ('be_onss_employer_base_rate', 'onss_employer', 'band'),
    ('be_onss_wage_moderation', 'onss_employer', 'rate'),
    ('be_onss_special_160', 'onss_employer', 'rate'),
    ('be_onss_special_160_threshold_rule', 'onss_employer', 'text-choice'),
    ('be_onss_pension_special', 'onss_employer', 'rate'),
    ('be_onss_company_car', 'onss_employer', 'formula'),
    ('be_onss_fund_contributions', 'onss_employer', 'band'),
    ('be_red_social_work_bonus', 'reductions', 'band'),
    ('be_red_structural', 'reductions', 'formula'),
    ('be_red_target_group', 'reductions', 'band'),
    ('be_hol_entitlement_weeks', 'holiday', 'amount'),
    ('be_hol_wc_simple_rule', 'holiday', 'text-choice'),
    ('be_hol_wc_double_pct', 'holiday', 'rate'),
    ('be_hol_wc_double_contribution_rule', 'holiday', 'text-choice'),
    ('be_hol_additional_rule', 'holiday', 'formula'),
    ('be_hol_departure_rule', 'holiday', 'formula'),
    ('be_hol_manual_quarterly_contribution', 'holiday', 'rate'),
    ('be_hol_manual_annual_debit', 'holiday', 'rate'),
    ('be_wage_rmmmg', 'wages', 'amount'),
    ('be_wage_rmmmg_min_age', 'wages', 'amount'),
    ('be_wage_index_centime_threshold', 'wages', 'amount'),
    ('be_wage_index_centime_rule', 'wages', 'formula'),
    ('be_wage_norm_margin', 'wages', 'rate'),
    ('be_wt_daily_limit_hours', 'working_time', 'amount'),
    ('be_wt_weekly_limit_hours', 'working_time', 'amount'),
    ('be_wt_weekly_reduced_hours', 'working_time', 'amount'),
    ('be_ot_threshold_rule', 'working_time', 'text-choice'),
    ('be_ot_premium_weekday', 'working_time', 'rate'),
    ('be_ot_premium_sunday_holiday', 'working_time', 'rate'),
    ('be_ot_compensatory_rest_rule', 'working_time', 'formula'),
    ('be_abs_wc_guaranteed_days', 'absence', 'amount'),
    ('be_abs_wc_guaranteed_pct', 'absence', 'rate'),
    ('be_abs_wc_min_contract_months', 'absence', 'amount'),
    ('be_abs_manual_day_bands', 'absence', 'band'),
    ('be_abs_manual_insurance_cap', 'absence', 'amount'),
    ('be_abs_relapse_window_weeks', 'absence', 'amount'),
    ('be_abs_maternity_weeks', 'absence', 'amount'),
    ('be_abs_maternity_multiple_weeks', 'absence', 'band'),
    ('be_abs_birth_leave_days', 'absence', 'amount'),
    ('be_abs_birth_leave_window_months', 'absence', 'amount'),
    ('be_abs_birth_leave_employer_days', 'absence', 'amount'),
    ('be_public_holidays', 'holidays', 'table'),
    ('be_public_holiday_substitution_rule', 'holidays', 'text-choice'),
    ('be_bik_valuation_rules', 'earning_class', 'formula'),
    ('be_meal_voucher_treatment', 'earning_class', 'text-choice'),
    ('be_ecocheque_treatment', 'earning_class', 'text-choice'),
    ('be_filing_dimona_schema_versions', 'filing', 'schema-version'),
    ('be_filing_dmfa_schema_versions', 'filing', 'schema-version'),
    ('be_filing_finprof_schema_versions', 'filing', 'schema-version'),
    ('be_filing_belcotax_schema_versions', 'filing', 'schema-version'),
    ('be_parallel_tolerance_gross', 'parallel', 'amount'),
    ('be_parallel_tolerance_withholding', 'parallel', 'amount'),
    ('be_parallel_tolerance_onss_employee', 'parallel', 'amount'),
    ('be_parallel_tolerance_work_bonus_social', 'parallel', 'amount'),
    ('be_parallel_tolerance_net', 'parallel', 'amount'),
    ('be_parallel_tolerance_employer_onss', 'parallel', 'amount'))
SELECT p.pack_id, p.version, cat.grp,
       count(r.id)                                                     AS rows_linked,
       count(*) FILTER (WHERE r.id IS NULL)                            AS catalogue_keys_missing,
       count(r.id) FILTER (WHERE r.label LIKE '%[PENDING G1]%')        AS pending_signature,
       count(r.id) FILTER (WHERE r.label NOT LIKE '%[PENDING G1]%')    AS signed,
       count(r.id) FILTER (WHERE r.employee_rate_pct IS NOT NULL OR r.employer_rate_pct IS NOT NULL
                                OR r.flat_amount IS NOT NULL OR nullif(btrim(r.text_value), '') IS NOT NULL) AS with_value,
       count(r.id) FILTER (WHERE r.source_document_id IS NOT NULL)     AS with_source
FROM payroll_jurisdiction_packs p
CROSS JOIN catalogue cat
LEFT JOIN payroll_contribution_rates r
       ON r.jurisdiction_pack_id = p.id AND r.organization_id IS NULL AND r.component_key = cat.component_key
WHERE p.jurisdiction_country = 'BE'
GROUP BY p.pack_id, p.version, cat.grp
ORDER BY p.pack_id, p.version, cat.grp;

-- 3. Slab rows (bands / formulas / tables) per pack and key: count, signed vs pending.
WITH rules(rule_type, component_key, grp) AS (VALUES
    ('BE_WHT_ANNEX3_REGULAR_SCALE', 'be_wht_annex3_regular_scale', 'withholding'),
    ('BE_WHT_ANNEX3_AMENDMENT_2026', 'be_wht_annex3_amendment_2026', 'withholding'),
    ('BE_WHT_FAMILY_REDUCTIONS', 'be_wht_family_reductions', 'withholding'),
    ('BE_WHT_FISCAL_WORK_BONUS', 'be_wht_fiscal_work_bonus', 'withholding'),
    ('BE_WHT_EXCEPTIONAL_RULE', 'be_wht_exceptional_rule', 'withholding'),
    ('BE_WHT_HOLIDAY_PAY_RULE', 'be_wht_holiday_pay_rule', 'withholding'),
    ('BE_WHT_ARREARS_RULE', 'be_wht_arrears_rule', 'withholding'),
    ('BE_WHT_OVERTIME_RULE', 'be_wht_overtime_rule', 'withholding'),
    ('BE_ONSS_EMPLOYER_BASE_RATE', 'be_onss_employer_base_rate', 'onss_employer'),
    ('BE_ONSS_COMPANY_CAR', 'be_onss_company_car', 'onss_employer'),
    ('BE_ONSS_FUND_CONTRIBUTIONS', 'be_onss_fund_contributions', 'onss_employer'),
    ('BE_RED_SOCIAL_WORK_BONUS', 'be_red_social_work_bonus', 'reductions'),
    ('BE_RED_STRUCTURAL', 'be_red_structural', 'reductions'),
    ('BE_RED_TARGET_GROUP', 'be_red_target_group', 'reductions'),
    ('BE_HOL_ADDITIONAL_RULE', 'be_hol_additional_rule', 'holiday'),
    ('BE_HOL_DEPARTURE_RULE', 'be_hol_departure_rule', 'holiday'),
    ('BE_WAGE_INDEX_CENTIME_RULE', 'be_wage_index_centime_rule', 'wages'),
    ('BE_OT_COMPENSATORY_REST_RULE', 'be_ot_compensatory_rest_rule', 'working_time'),
    ('BE_ABS_MANUAL_DAY_BANDS', 'be_abs_manual_day_bands', 'absence'),
    ('BE_ABS_MATERNITY_MULTIPLE', 'be_abs_maternity_multiple_weeks', 'absence'),
    ('BE_PUBLIC_HOLIDAY', 'be_public_holidays', 'holidays'),
    ('BE_BIK_VALUATION_RULES', 'be_bik_valuation_rules', 'earning_class'),
    ('BE_FILING_DIMONA_SCHEMA', 'be_filing_dimona_schema_versions', 'filing'),
    ('BE_FILING_DMFA_SCHEMA', 'be_filing_dmfa_schema_versions', 'filing'),
    ('BE_FILING_FINPROF_SCHEMA', 'be_filing_finprof_schema_versions', 'filing'),
    ('BE_FILING_BELCOTAX_SCHEMA', 'be_filing_belcotax_schema_versions', 'filing'))
SELECT p.pack_id, p.version, ru.grp, ru.component_key, ru.rule_type,
       count(s.id)                                                          AS slab_rows,
       count(s.id) FILTER (WHERE s.rate_label LIKE '%[PENDING G1]%')        AS pending_signature,
       count(s.id) FILTER (WHERE s.rate_label NOT LIKE '%[PENDING G1]%')    AS signed
FROM payroll_jurisdiction_packs p
CROSS JOIN rules ru
LEFT JOIN payroll_tax_slabs s
       ON s.jurisdiction_pack_id = p.id AND s.organization_id IS NULL AND s.rule_type = ru.rule_type
WHERE p.jurisdiction_country = 'BE'
GROUP BY p.pack_id, p.version, ru.grp, ru.component_key, ru.rule_type
ORDER BY p.pack_id, p.version, ru.grp, ru.component_key;

-- 4. Any Belgian canonical row NOT in the catalogue (stray / hand-made rows).
SELECT p.pack_id, p.version, r.id, r.component_key, r.label
FROM payroll_contribution_rates r JOIN payroll_jurisdiction_packs p ON p.id = r.jurisdiction_pack_id
WHERE p.jurisdiction_country = 'BE' AND r.organization_id IS NULL
  AND r.component_key NOT IN (SELECT component_key FROM (VALUES ('be_supported_pay_frequencies'), ('be_supported_pay_bases'), ('be_supported_worker_categories'), ('be_supported_contract_types'), ('be_rounding_onss'), ('be_rounding_withholding'), ('be_rounding_holiday'), ('be_bssc_pending'), ('be_wht_applicability_rule'), ('be_wht_nonresident_rule'), ('be_wht_taxable_basis_rule'), ('be_wht_period_strategy'), ('be_wht_annex3_regular_scale'), ('be_wht_annex3_amendment_2026'), ('be_wht_family_reductions'), ('be_wht_fiscal_work_bonus'), ('be_wht_exceptional_rule'), ('be_wht_holiday_pay_rule'), ('be_wht_arrears_rule'), ('be_wht_overtime_rule'), ('be_onss_employee_rate'), ('be_onss_employee_base_rule'), ('be_onss_manual_base_uplift'), ('be_onss_manual_base_categories'), ('be_onss_supported_employer_categories'), ('be_onss_supported_worker_codes'), ('be_onss_rate_file_quarter'), ('be_onss_employer_base_rate'), ('be_onss_wage_moderation'), ('be_onss_special_160'), ('be_onss_special_160_threshold_rule'), ('be_onss_pension_special'), ('be_onss_company_car'), ('be_onss_fund_contributions'), ('be_red_social_work_bonus'), ('be_red_structural'), ('be_red_target_group'), ('be_hol_entitlement_weeks'), ('be_hol_wc_simple_rule'), ('be_hol_wc_double_pct'), ('be_hol_wc_double_contribution_rule'), ('be_hol_additional_rule'), ('be_hol_departure_rule'), ('be_hol_manual_quarterly_contribution'), ('be_hol_manual_annual_debit'), ('be_wage_rmmmg'), ('be_wage_rmmmg_min_age'), ('be_wage_index_centime_threshold'), ('be_wage_index_centime_rule'), ('be_wage_norm_margin'), ('be_wt_daily_limit_hours'), ('be_wt_weekly_limit_hours'), ('be_wt_weekly_reduced_hours'), ('be_ot_threshold_rule'), ('be_ot_premium_weekday'), ('be_ot_premium_sunday_holiday'), ('be_ot_compensatory_rest_rule'), ('be_abs_wc_guaranteed_days'), ('be_abs_wc_guaranteed_pct'), ('be_abs_wc_min_contract_months'), ('be_abs_manual_day_bands'), ('be_abs_manual_insurance_cap'), ('be_abs_relapse_window_weeks'), ('be_abs_maternity_weeks'), ('be_abs_maternity_multiple_weeks'), ('be_abs_birth_leave_days'), ('be_abs_birth_leave_window_months'), ('be_abs_birth_leave_employer_days'), ('be_public_holidays'), ('be_public_holiday_substitution_rule'), ('be_bik_valuation_rules'), ('be_meal_voucher_treatment'), ('be_ecocheque_treatment'), ('be_filing_dimona_schema_versions'), ('be_filing_dmfa_schema_versions'), ('be_filing_finprof_schema_versions'), ('be_filing_belcotax_schema_versions'), ('be_parallel_tolerance_gross'), ('be_parallel_tolerance_withholding'), ('be_parallel_tolerance_onss_employee'), ('be_parallel_tolerance_work_bonus_social'), ('be_parallel_tolerance_net'), ('be_parallel_tolerance_employer_onss')) v(component_key));

-- 5. How BE-PAYROLL-2027 and its tax year were created (the pack's audit trail).
SELECT a.created_at, a.action, a.actor_id, a.reason, a.new_value->>'tax_year' AS tax_year_written, a.new_value->>'pack_id' AS pack_id
FROM payroll_tax_configuration_audit a JOIN payroll_jurisdiction_packs p ON p.id = a.entity_id
WHERE a.entity_type = 'jurisdiction_pack' AND p.jurisdiction_country = 'BE'
ORDER BY a.created_at;
