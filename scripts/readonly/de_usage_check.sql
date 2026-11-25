-- ============================================================================
-- READ-ONLY. This file contains SELECT statements only: it reads which
-- organisations are registered for Germany, their German employees, and the
-- payslips that carry a German calculation (by run status, payslip status and
-- PAP version). It writes, updates or deletes NOTHING. Run it with a read-only
-- database role, e.g. through the read-only runner next to it:
--   python scripts/readonly/run_readonly_sql.py scripts/readonly/de_usage_check.sql
-- Purpose: decide whether Germany is used for real payroll today (German wage
-- tax currently comes from an internal reference tariff, not BMF-certified).
-- ============================================================================
-- 1) Organisations registered for Germany
SELECT c.organization_id, c.jurisdiction_country
FROM payroll_company_compliance c
WHERE upper(c.jurisdiction_country) IN ('DE', 'GERMANY')
ORDER BY c.organization_id;

-- 2) German employees per organisation and status
SELECT e.organization_id, e.status, count(*) AS employees
FROM payroll_employees e
WHERE upper(e.country_code) = 'DE'
GROUP BY e.organization_id, e.status
ORDER BY e.organization_id, e.status;

-- 3) Payslips that carry a German calculation, by organisation / run status / payslip status / PAP version
SELECT p.organization_id, r.status AS run_status, p.status AS payslip_status,
       coalesce(p.germany_calculation_snapshot ->> 'pap_version', '(none)') AS pap_version,
       count(*) AS payslips, min(r.pay_date) AS first_pay_date, max(r.pay_date) AS last_pay_date
FROM payslip_items p
JOIN payroll_runs r ON r.id = p.payroll_run_id
WHERE p.germany_calculation_snapshot IS NOT NULL
GROUP BY p.organization_id, r.status, p.status, 4
ORDER BY p.organization_id, last_pay_date DESC;
