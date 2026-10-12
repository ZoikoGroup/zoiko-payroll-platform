-- Germany 2026 all-Länder jurisdiction readiness — read-only verification
-- queries (Phase 8). Safe to run in pgAdmin against the shared dev DB;
-- none of these write anything.

-- 1. All Germany jurisdiction packs (federal + all Länder), status/lifecycle.
SELECT id, pack_id, jurisdiction_country, jurisdiction_state, pack_type,
       version, status, tax_year, effective_from, effective_to, parent_pack_id
FROM payroll_jurisdiction_packs
WHERE jurisdiction_country = 'DE'
ORDER BY (jurisdiction_state IS NOT NULL), jurisdiction_state;

-- 2. Registry row counts by pack (the 8 categories, 51-row baseline).
SELECT 'contribution_ceilings' AS registry, jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_contribution_ceilings GROUP BY 1, 2, 3
UNION ALL
SELECT 'pv_configurations', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_pv_configurations GROUP BY 1, 2, 3
UNION ALL
SELECT 'health_funds', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_health_funds GROUP BY 1, 2, 3
UNION ALL
SELECT 'health_fund_u1_tariffs', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_health_fund_u1_tariffs GROUP BY 1, 2, 3
UNION ALL
SELECT 'earning_taxability_rules', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_earning_taxability_rules GROUP BY 1, 2, 3
UNION ALL
SELECT 'overtime_premium_categories', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_overtime_premium_categories GROUP BY 1, 2, 3
UNION ALL
SELECT 'overtime_grundlohn_caps', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_overtime_grundlohn_caps GROUP BY 1, 2, 3
UNION ALL
SELECT 'church_tax_exceptions', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_church_tax_exceptions GROUP BY 1, 2, 3
UNION ALL
SELECT 'minijob_midijob_parameters', jurisdiction_pack_id, status, COUNT(*)
FROM payroll_germany_minijob_midijob_parameters GROUP BY 1, 2, 3
ORDER BY 1, 2;

-- 3. Orphan registry rows (jurisdiction_pack_id set but no matching pack row).
SELECT 'contribution_ceilings' AS registry, r.id, r.jurisdiction_pack_id
FROM payroll_germany_contribution_ceilings r
LEFT JOIN payroll_jurisdiction_packs p ON p.id = r.jurisdiction_pack_id
WHERE r.jurisdiction_pack_id IS NOT NULL AND p.id IS NULL
UNION ALL
SELECT 'minijob_midijob_parameters', r.id, r.jurisdiction_pack_id
FROM payroll_germany_minijob_midijob_parameters r
LEFT JOIN payroll_jurisdiction_packs p ON p.id = r.jurisdiction_pack_id
WHERE r.jurisdiction_pack_id IS NOT NULL AND p.id IS NULL;
-- (repeat the LEFT JOIN pattern for the remaining 6 registry tables if a
-- deeper audit is needed — omitted here since query 2 already shows every
-- jurisdiction_pack_id in use, which can be diffed against query 1's ids.)

-- 4. Duplicate ACTIVE packs for the same country+state (should be zero rows).
SELECT jurisdiction_country, jurisdiction_state, tax_regime, COUNT(*) AS active_count
FROM payroll_jurisdiction_packs
WHERE jurisdiction_country = 'DE' AND pack_type = 'tax' AND status = 'Active'
GROUP BY 1, 2, 3
HAVING COUNT(*) > 1;

-- 5. Missing Länder — expects zero rows (all 16 present).
WITH expected(code) AS (
  VALUES ('DE-BW'),('DE-BY'),('DE-BE'),('DE-BB'),('DE-HB'),('DE-HH'),('DE-HE'),
         ('DE-MV'),('DE-NI'),('DE-NW'),('DE-RP'),('DE-SL'),('DE-SN'),('DE-ST'),
         ('DE-SH'),('DE-TH')
)
SELECT e.code AS missing_land
FROM expected e
LEFT JOIN payroll_jurisdiction_packs p
  ON p.jurisdiction_country = 'DE' AND p.jurisdiction_state = e.code
  AND p.pack_type = 'tax' AND p.status = 'Active'
WHERE p.id IS NULL;

-- 6. Every Land pack's parent_pack_id points at the correct Active federal pack.
SELECT land.jurisdiction_state, land.pack_id AS land_pack, land.parent_pack_id,
       federal.pack_id AS parent_pack, federal.status AS parent_status
FROM payroll_jurisdiction_packs land
LEFT JOIN payroll_jurisdiction_packs federal ON federal.id = land.parent_pack_id
WHERE land.jurisdiction_country = 'DE' AND land.jurisdiction_state IS NOT NULL
  AND land.pack_type = 'tax' AND land.status = 'Active'
ORDER BY land.jurisdiction_state;

-- 7. Current Alembic revision (should be a single row/single head).
SELECT version_num FROM alembic_version;

-- 8. jurisdiction_pack_id integrity summary across ALL Germany registry
-- tables at once (every distinct pack id actually referenced).
SELECT DISTINCT jurisdiction_pack_id, p.pack_id, p.jurisdiction_state
FROM (
  SELECT jurisdiction_pack_id FROM payroll_germany_contribution_ceilings
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_pv_configurations
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_health_funds
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_health_fund_u1_tariffs
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_earning_taxability_rules
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_overtime_premium_categories
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_overtime_grundlohn_caps
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_church_tax_exceptions
  UNION SELECT jurisdiction_pack_id FROM payroll_germany_minijob_midijob_parameters
) used
LEFT JOIN payroll_jurisdiction_packs p ON p.id = used.jurisdiction_pack_id
ORDER BY 1;
