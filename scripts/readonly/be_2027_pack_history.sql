-- ============================================================================
-- READ-ONLY. SELECT statements only: who moved BE-PAYROLL-2027 to Approved,
-- when and through which endpoint, and what the pack holds. It writes, updates
-- or deletes NOTHING. Run it with a read-only database role, e.g.:
--   python scripts/readonly/run_readonly_sql.py scripts/readonly/be_2027_pack_history.sql
--
-- How to read the "route" column (see payroll/service.py):
--   approve-button  PUT /api/super-admin/compliance/policies/{id}/approve
--                   (action 'update', reason 'Approver set'; Draft -> Approved auto-advance)
--   status-dropdown PUT /api/super-admin/compliance/policies/{id}/status
--                   (action 'status_change')
--   refused         an attempt the backend refused (action 'refused')
-- ============================================================================

-- 1. The BE-PAYROLL-2027 pack row(s).
SELECT p.id, p.pack_id, p.version, p.status, p.tax_year, p.effective_from, p.effective_to,
       p.created_by_id, p.updated_by_id, p.approved_by_id, p.created_at, p.updated_at
FROM payroll_jurisdiction_packs p
WHERE p.jurisdiction_country = 'BE' AND p.pack_id = 'BE-PAYROLL-2027'
ORDER BY p.id;

-- 2. Its full audit trail, oldest first, with the route and the actor's role.
SELECT a.id, a.created_at, a.actor_id, u.role AS actor_role, a.action, a.entity_type,
       CASE
         WHEN a.action = 'update' AND a.reason = 'Approver set' THEN 'approve-button'
         WHEN a.action = 'status_change' THEN 'status-dropdown'
         WHEN a.action = 'refused' THEN 'refused'
         ELSE a.action
       END AS route,
       a.old_value ->> 'status' AS old_status, a.new_value ->> 'status' AS new_status,
       a.new_value ->> 'approved_by_id' AS approved_by_id, a.reason
FROM payroll_tax_configuration_audit a
JOIN payroll_jurisdiction_packs p ON p.id = a.jurisdiction_pack_id
LEFT JOIN users u ON u.id = a.actor_id
WHERE p.jurisdiction_country = 'BE' AND p.pack_id = 'BE-PAYROLL-2027'
ORDER BY a.created_at, a.id;

-- 3. What the pack holds: catalogue (rate) rows and slab rows.
SELECT p.id AS pack_row_id,
       (SELECT count(*) FROM payroll_contribution_rates r
         WHERE r.jurisdiction_pack_id = p.id AND r.organization_id IS NULL) AS catalogue_rows,
       (SELECT count(*) FROM payroll_tax_slabs s
         WHERE s.jurisdiction_pack_id = p.id AND s.organization_id IS NULL) AS slab_rows
FROM payroll_jurisdiction_packs p
WHERE p.jurisdiction_country = 'BE' AND p.pack_id = 'BE-PAYROLL-2027'
ORDER BY p.id;
