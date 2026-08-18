// Thin API wrapper for the new Super Admin modules (Compliance, Finance,
// Reports, Dashboard charts) — mirrors the existing pages/*.jsx convention
// of calling apiFetch directly, just consolidated into named functions
// since these three modules add far more endpoints than any single
// existing Super Admin page called before.
import { apiFetch, API_BASE, getAccessToken } from "../api/client";

// ── Compliance ───────────────────────────────────────────────────────────

export const getComplianceJurisdictions = () => apiFetch("/api/super-admin/compliance/jurisdictions");

// One row per jurisdiction with real counts (active tax packs, active
// policy packs, active statutory rates, orgs assigned) — powers the
// jurisdiction card grid landing view.
export const getJurisdictionSummary = () => apiFetch("/api/super-admin/compliance/jurisdiction-summary");

export const getCompliancePolicies = (params) => apiFetch("/api/super-admin/compliance/policies", { params });

export const upsertCompliancePolicy = (payload) =>
  apiFetch("/api/super-admin/compliance/policies", { method: "PUT", body: payload });

export const getCompliancePolicyVersions = (packId) =>
  apiFetch(`/api/super-admin/compliance/policies/${encodeURIComponent(packId)}/versions`);

export const setCompliancePolicyStatus = (id, status) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/status`, { method: "PUT", body: { status } });

export const getCompliancePolicyOrganizations = (id) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/organizations`);

export const assignCompliancePolicy = (id, organizationIds) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/assign`, {
    method: "POST",
    body: { organizationIds },
  });

export const hardDeleteCompliancePolicy = (id) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}`, { method: "DELETE" });

// Every organization's ACTUAL, currently-configured compliance setup (as
// opposed to the abstract policy templates above) — used by the Compliance
// page's "Organization Compliance" view to promote real configs into
// versioned policies.
export const getComplianceConfigurations = (params) =>
  apiFetch("/api/super-admin/compliance/configurations", { params });

// ── Canonical Tax Configuration (government-mandated values; Super Admin-only) ──
// organization_id IS NULL rows on payroll_tax_slabs/payroll_contribution_rates —
// the actual government-mandated values, linked to a "tax" JurisdictionPack.
// Org-scoped rows (what payroll calculation actually reads) are populated
// FROM these via sync_org_rates_from_canonical — not a duplicate system.

export const getCanonicalTaxSlabs = (params) =>
  apiFetch("/api/super-admin/compliance/tax-configuration/slabs", { params });

export const upsertCanonicalTaxSlab = (payload) =>
  apiFetch("/api/super-admin/compliance/tax-configuration/slabs", { method: "PUT", body: payload });

export const deleteCanonicalTaxSlab = (id) =>
  apiFetch(`/api/super-admin/compliance/tax-configuration/slabs/${id}`, { method: "DELETE" });

export const getCanonicalContributionRates = (params) =>
  apiFetch("/api/super-admin/compliance/tax-configuration/contribution-rates", { params });

export const upsertCanonicalContributionRate = (payload) =>
  apiFetch("/api/super-admin/compliance/tax-configuration/contribution-rates", { method: "PUT", body: payload });

export const deleteCanonicalContributionRate = (id) =>
  apiFetch(`/api/super-admin/compliance/tax-configuration/contribution-rates/${id}`, { method: "DELETE" });

export const getTaxConfigurationAudit = (params) =>
  apiFetch("/api/super-admin/compliance/tax-configuration/audit", { params });

// ── Finance ──────────────────────────────────────────────────────────────

export const getFinanceOverview = (params) => apiFetch("/api/super-admin/finance/overview", { params });

export const getFinanceSummary = (params) => apiFetch("/api/super-admin/finance/summary", { params });

export const getOrganizationCurrencies = () => apiFetch("/api/super-admin/finance/organization-currencies");

export const updateOrganizationCurrency = (organizationId, currency) =>
  apiFetch(`/api/super-admin/finance/organizations/${organizationId}/currency`, {
    method: "PUT",
    body: { currency },
  });

// ── Statutory Rates ──────────────────────────────────────────────────────

export const getOrganizationContributionRates = (params) =>
  apiFetch("/api/super-admin/statutory-rates/organization-rates", { params });

// Read-only: the canonical rates/slabs from whichever tax pack is
// currently Active for this jurisdiction — the same data Compliance's
// Rates editor writes to. Editing happens on the Compliance page.
export const getActiveTaxConfiguration = (params) =>
  apiFetch("/api/super-admin/compliance/active-tax-configuration", { params });

// ── Reports ──────────────────────────────────────────────────────────────

export const getReportsOrganizations = (params) => apiFetch("/api/super-admin/reports/organizations", { params });

export const getReportsEmployees = (params) => apiFetch("/api/super-admin/reports/employees", { params });

export async function downloadReportCsv(type, params = {}) {
  const query = new URLSearchParams({ type, ...params }).toString();
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/api/super-admin/reports/export?${query}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to export report");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${type}-report.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
}

// ── Dashboard charts ───────────────────────────────────────────────────────

export const getDashboardCharts = (params) => apiFetch("/api/super-admin/dashboard/charts", { params });

// ── Organizations (for filter dropdowns — reuses the existing endpoint) ───

export const listAllOrganizationsBrief = () =>
  apiFetch("/api/organizations", { params: { limit: 200, include_inactive: true } });
