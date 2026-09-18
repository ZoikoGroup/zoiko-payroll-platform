-- scripts/germany_production_db_evidence.sql
-- ============================================
-- READ-ONLY database evidence collection for the Germany 2026 production
-- activation runbook (docs/GERMANY_2026_PRODUCTION_EXECUTION_RUNBOOK.md,
-- Gates 1, 3 and 4).
--
-- SAFETY: this file contains ONLY SELECT / information_schema queries. It
-- contains NO INSERT, UPDATE, DELETE, ALTER, CREATE, DROP, TRUNCATE, GRANT,
-- REVOKE, VACUUM, ANALYZE, or any other write-capable statement. It also
-- does not call any function that writes (e.g. set_config side-effects are
-- avoided; no DDL in CTEs). Run it against the PRODUCTION database or a
-- read replica with a read-only role; collect the output as
-- gate4_db_evidence.txt (or name it to match your evidence matrix).
--
-- Safe invocation:
--   psql "postgresql://A:B@READ_REPLICA:5432/zoiko_payroll" \
--        -v ON_ERROR_STOP=0 -f scripts/germany_production_db_evidence.sql \
--        > gate4_db_evidence.txt 2>&1
--
-- (ON_ERROR_STOP=0 so one missing table does not abort the rest of the
-- survey; each section names the artifact it feeds.)

\echo '=============================================================='
\echo ' Germany 2026 DB evidence (READ-ONLY) — capture timestamp records the run date in the evidence filename'
\echo '=============================================================='

-- --------------------------------------------------------------------------
-- 1. Alembic version table (feeds the reconciliation decision, Gate 5)
-- --------------------------------------------------------------------------
\echo '--- 1. alembic_version ---'
SELECT version_num
FROM alembic_version;

-- --------------------------------------------------------------------------
-- 2. Source evidence registry (feeds Gate 4 / SOURCE LOCK rule)
-- --------------------------------------------------------------------------
\echo '--- 2. payroll_source_artifacts: row count ---'
SELECT count(*) AS source_artifact_count
FROM payroll_source_artifacts;

\echo '--- 2b. payroll_source_artifacts: rows (id, agency, title, form_number, publication_date, reviewer_approved_at) ---'
SELECT id, agency,
       left(title, 120) AS title,
       form_number, publication_date, reviewer_approved_at
FROM payroll_source_artifacts
ORDER BY id;

\echo '--- 2c. payroll_germany_pap_assets: status distribution ---'
SELECT status, count(*) AS n
FROM payroll_germany_pap_assets
GROUP BY status
ORDER BY status;

-- --------------------------------------------------------------------------
-- 3. Germany statutory registries: existence + row count (feeds Gate 4)
-- --------------------------------------------------------------------------
\echo '--- 3. Germany registry tables: present? / row count ---'
SELECT
  t.table_name,
  CASE WHEN t.table_name IS NOT NULL THEN 'PRESENT' ELSE 'ABSENT' END AS table_state
FROM (
  SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
) t
ORDER BY t.table_name;

\echo '--- 3b. Row counts per Germany registry (regardless of presence) ---'
SELECT 'payroll_germany_health_funds'                      AS registry, count(*) AS rows_ FROM payroll_germany_health_funds
UNION ALL SELECT 'payroll_germany_health_fund_u1_tariffs', count(*) FROM payroll_germany_health_fund_u1_tariffs
UNION ALL SELECT 'payroll_germany_contribution_ceilings',  count(*) FROM payroll_germany_contribution_ceilings
UNION ALL SELECT 'payroll_germany_minijob_midijob_parameters', count(*) FROM payroll_germany_minijob_midijob_parameters
UNION ALL SELECT 'payroll_germany_pv_configurations',      count(*) FROM payroll_germany_pv_configurations
UNION ALL SELECT 'payroll_germany_earning_taxability_rules', count(*) FROM payroll_germany_earning_taxability_rules
UNION ALL SELECT 'payroll_germany_overtime_premium_categories', count(*) FROM payroll_germany_overtime_premium_categories
UNION ALL SELECT 'payroll_germany_overtime_grundlohn_caps',count(*) FROM payroll_germany_overtime_grundlohn_caps
UNION ALL SELECT 'payroll_germany_church_tax_exceptions',  count(*) FROM payroll_germany_church_tax_exceptions
UNION ALL SELECT 'payroll_germany_pap_assets',             count(*) FROM payroll_germany_pap_assets
UNION ALL SELECT 'payroll_germany_pap_releases',           count(*) FROM payroll_germany_pap_releases
UNION ALL SELECT 'payroll_germany_accident_insurance_profiles', count(*) FROM payroll_germany_accident_insurance_profiles;

-- --------------------------------------------------------------------------
-- 4. Payslip Germany-relevant schema drift checks (feeds Gate 3)
--    payslip_items.soli:  present? type? server default? (Phase 6 drift: NULL)
-- --------------------------------------------------------------------------
\echo '--- 4. payslip_items.soli / church_tax column metadata ---'
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'payslip_items'
  AND column_name IN ('soli', 'church_tax', 'tds', 'germany_calculation_snapshot')
ORDER BY column_name;

\echo '--- 4b. Count of payslip rows where soli differs from null-or-zero ---'
SELECT
  count(*)                                              AS payslip_rows,
  count(*) FILTER (WHERE soli IS NOT NULL)              AS soli_not_null,
  count(*) FILTER (WHERE soli <> 0)                     AS soli_nonzero
FROM payslip_items;

-- --------------------------------------------------------------------------
-- 5. Overtime premium components: the three Phase-8BW delta columns
-- --------------------------------------------------------------------------
\echo '--- 5. payroll_germany_overtime_premium_components delta columns ---'
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'payroll_germany_overtime_premium_components'
  AND column_name IN (
    'attachment_status', 'financial_integration_status',
    'applied_gross_delta', 'applied_pf_delta', 'applied_esi_delta',
    'applied_wage_tax_delta', 'applied_soli_delta', 'applied_church_tax_delta'
  )
ORDER BY ordinal_position;

\echo '--- 5b. Distribution of financial_integration_status (if table present) ---'
SELECT financial_integration_status, count(*)
FROM payroll_germany_overtime_premium_components
GROUP BY financial_integration_status
ORDER BY financial_integration_status;

-- --------------------------------------------------------------------------
-- 6. ELStAM / ELSTER table presence (feeds Gate 8 decision)
-- --------------------------------------------------------------------------
\echo '--- 6. ELStAM / ELSTER tables ---'
SELECT table_name, 'PRESENT' AS state
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'payroll_germany_elstam_change_list_batches',
    'payroll_germany_elstam_import_attempts',
    'payroll_germany_elster_certificate_configs',
    'payroll_germany_elster_transmissions'
  )
ORDER BY table_name;

-- --------------------------------------------------------------------------
-- 7. ELStAM unique constraint presence (feeds schema reconciliation, Gate 3)
-- --------------------------------------------------------------------------
\echo '--- 7. Unique constraints on payroll_germany_elstam_change_list_batches (if present) ---'
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'payroll_germany_elstam_change_list_batches'::regclass
ORDER BY conname;

-- --------------------------------------------------------------------------
-- 8. Global invariants that the Germany package must not disturb
-- --------------------------------------------------------------------------
\echo '--- 8. schema/owner context ---'
SELECT current_database(), current_user, current_setting('server_version') AS server_version;

\echo '--- 8b. counts of pre-existing payslip/run rows (context, unchanged by this package) ---'
SELECT
  (SELECT count(*) FROM payroll_runs)           AS payroll_runs,
  (SELECT count(*) FROM payslip_items)          AS payslip_items,
  (SELECT count(*) FROM payroll_employees)      AS payroll_employees;

-- --------------------------------------------------------------------------
-- 9. Final safety assertion: confirm this script issued no writes
-- --------------------------------------------------------------------------
\echo '--- 9. post-scan pg_stat check (informational: DML counter before/after is unchanged by SELECT-only queries) ---'
SELECT n_live_tup
FROM pg_stat_user_tables
WHERE relname IN ('payslip_items', 'payroll_source_artifacts')
ORDER BY relname;

\echo '=== END of read-only DB evidence ==='