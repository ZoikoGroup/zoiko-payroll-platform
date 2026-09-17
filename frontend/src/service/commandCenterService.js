// service/commandCenterService.js
// -----------------------------------
// Frontend calls for the Super Admin Command Center sections (Zoiko
// Commercial / Payroll Operations / Platform). All cross-tenant reads
// against backend/app/modules/super_admin/command_center_router.py, plus
// the pre-existing billing admin endpoints (backend/app/modules/billing/
// admin_router.py) used by the Plans & Entitlements page.
import { apiFetch } from "../api/client";

// ── Zoiko Commercial ────────────────────────────────────────────────────

export const listAllSubscriptions = (params) =>
  apiFetch("/api/super-admin/billing/subscriptions", { params });

export const listPublishedPlans = () => apiFetch("/api/billing/plans");

export const createBillingPlan = (payload) =>
  apiFetch("/api/super-admin/billing/plans", { method: "POST", body: payload });

export const createBillingPlanVersion = (planId, payload) =>
  apiFetch(`/api/super-admin/billing/plans/${planId}/versions`, { method: "POST", body: payload });

export const transitionPlanVersionStatus = (planVersionId, status) =>
  apiFetch(`/api/super-admin/billing/plan-versions/${planVersionId}/status`, {
    method: "PUT",
    body: { status },
  });

export const addEntitlementFlag = (planVersionId, payload) =>
  apiFetch(`/api/super-admin/billing/plan-versions/${planVersionId}/entitlement-flags`, {
    method: "POST",
    body: payload,
  });

export const listEntitlementOverrides = (organizationId) =>
  apiFetch(`/api/super-admin/billing/organizations/${organizationId}/entitlement-overrides`);

export const createEntitlementOverride = (organizationId, payload) =>
  apiFetch(`/api/super-admin/billing/organizations/${organizationId}/entitlement-overrides`, {
    method: "POST",
    body: payload,
  });

// ── Payroll Operations ──────────────────────────────────────────────────

export const listAllPayrollRuns = (params) =>
  apiFetch("/api/super-admin/payroll/runs", { params });

export const listFilingsRemittances = () =>
  apiFetch("/api/super-admin/compliance/filings-remittances");

export const listExceptions = (params) =>
  apiFetch("/api/super-admin/compliance/exceptions", { params });

// ── Platform ────────────────────────────────────────────────────────────

export const getServiceHealth = () => apiFetch("/api/super-admin/platform/service-health");

export const listIntegrations = () => apiFetch("/api/super-admin/platform/integrations");

export const getSecurityAuditLog = (params) => apiFetch("/api/super-admin/security/audit", { params });
