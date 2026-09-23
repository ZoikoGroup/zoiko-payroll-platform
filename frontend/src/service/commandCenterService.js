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

// ── Enterprise Order Forms (Step 6 / Part 12) ────────────────────────────

export const listOrderForms = () => apiFetch("/api/super-admin/billing/order-forms");

export const listOrderFormEligibleOrgs = () =>
  apiFetch("/api/super-admin/billing/order-form-eligible-orgs").then((data) => data.organizations || []);

export const getOrderForm = (organizationId) =>
  apiFetch(`/api/super-admin/billing/organizations/${organizationId}/order-form`);

export const createOrderForm = (organizationId, payload) =>
  apiFetch(`/api/super-admin/billing/organizations/${organizationId}/order-form`, {
    method: "POST",
    body: payload,
  });

// ── Zoiko Commercial — Revenue & Collections (Step 5) ─────────────────────
// Zoiko's own subscription revenue (PAID BillingInvoice rows), distinct
// from /finance/* which reports customer payroll money movement. See the
// backend endpoint's docstring for the never-merge rationale.
export const getRevenueCollections = () =>
  apiFetch("/api/super-admin/commercial/revenue-collections");

// ── Alerts & Incidents (unified triage feed) ──────────────────────────────
// One feed over signals each existing Command Center page already computes —
// severity is derived on the backend from the source signal, never invented
// on the client. Also polled by SuperAdminShell for the nav badge.
export const listAlerts = () => apiFetch("/api/super-admin/alerts");

// ── Payroll Operations ──────────────────────────────────────────────────

export const listAllPayrollRuns = (params) =>
  apiFetch("/api/super-admin/payroll/runs", { params });

export const listFilingsRemittances = () =>
  apiFetch("/api/super-admin/compliance/filings-remittances");

// Write path for the same dashboard: record/update a statutory filing
// status for an org (upserts by natural key — jurisdiction + filing type +
// period — so re-saving an existing period updates it in place), and delete
// a recorded filing.
export const upsertStatutoryFiling = (organizationId, payload) =>
  apiFetch(`/api/super-admin/compliance/filings-remittances/${organizationId}`, {
    method: "PUT",
    body: payload,
  });

export const deleteStatutoryFiling = (organizationId, filingId) =>
  apiFetch(`/api/super-admin/compliance/filings-remittances/${organizationId}/${filingId}`, {
    method: "DELETE",
  });

export const listExceptions = (params) =>
  apiFetch("/api/super-admin/compliance/exceptions", { params });

// ── Platform ────────────────────────────────────────────────────────────

export const getServiceHealth = () => apiFetch("/api/super-admin/platform/service-health");

export const listIntegrations = () => apiFetch("/api/super-admin/platform/integrations");

export const getSecurityAuditLog = (params) => apiFetch("/api/super-admin/security/audit", { params });
