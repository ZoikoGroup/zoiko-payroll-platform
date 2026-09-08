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

// Read-only: every hardcoded fallback value the payroll engine uses when no
// canonical/org rate exists — powers the "Engine Fallback Defaults" viewer.
export const getEngineFallbackDefaults = () => apiFetch("/api/super-admin/compliance/engine-fallback-defaults");

export const getCompliancePolicies = (params) => apiFetch("/api/super-admin/compliance/policies", { params });

export const upsertCompliancePolicy = (payload) =>
  apiFetch("/api/super-admin/compliance/policies", { method: "PUT", body: payload });

export const getCompliancePolicyVersions = (packId) =>
  apiFetch(`/api/super-admin/compliance/policies/${encodeURIComponent(packId)}/versions`);

export const setCompliancePolicyStatus = (id, status) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/status`, { method: "PUT", body: { status } });

// Maker-checker: records the CALLING Super Admin as this pack's approver.
// Must be a different person than whoever last edited it before the
// pack can go Active — enforced server-side, see set_jurisdiction_pack_status.
export const approveCompliancePolicy = (id) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/approve`, { method: "PUT" });

export const getCompliancePolicyOrganizations = (id) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/organizations`);

// Organizations whose own jurisdiction (country, and state for a
// state-level pack) matches this pack's — the set the Assign picker
// should offer, not every organization on the platform.
export const getCompliancePolicyEligibleOrganizations = (id) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/eligible-organizations`);

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

// ── US: Employer-Specific Tax Profiles (SUI and similar) ─────────────────
// Tenant-specific, agency-assigned rates — a separate schema/table from
// the canonical Contribution Rate/Tax Slab endpoints above (see
// EmployerTaxProfile's model docstring for why).

export const getEmployerTaxProfiles = (params) =>
  apiFetch("/api/super-admin/compliance/employer-tax-profiles", { params });

export const upsertEmployerTaxProfile = (payload) =>
  apiFetch("/api/super-admin/compliance/employer-tax-profiles", { method: "PUT", body: payload });

export const deleteEmployerTaxProfile = (id) =>
  apiFetch(`/api/super-admin/compliance/employer-tax-profiles/${id}`, { method: "DELETE" });

// Small organization picker for the Germany Employer Levies (Accident
// Insurance) tab — EmployerTaxProfile is org-scoped (unlike every other
// Germany registry, all global), so its Super Admin UI needs to let the
// operator pick which employer they're configuring (Phase 8AJ).
export const listOrganizationsForPicker = () =>
  apiFetch("/api/organizations", { params: { limit: 200 } }).then((data) => data.organizations || []);

// ── US: Cross-State Reciprocity ───────────────────────────────────────────

export const getReciprocityRules = () =>
  apiFetch("/api/super-admin/compliance/reciprocity-rules");

export const upsertReciprocityRule = (payload) =>
  apiFetch("/api/super-admin/compliance/reciprocity-rules", { method: "PUT", body: payload });

export const deleteReciprocityRule = (id) =>
  apiFetch(`/api/super-admin/compliance/reciprocity-rules/${id}`, { method: "DELETE" });

// ── US: Locality (county/municipal/school-district) Tax Rates ────────────
// Manually-entered, same pattern as Employer Tax Profiles above — no
// geocoding provider, Tax Ops types in a real published rate against a
// known locality code.

export const getLocalityRates = (params) =>
  apiFetch("/api/super-admin/compliance/locality-rates", { params });

export const upsertLocalityRate = (payload) =>
  apiFetch("/api/super-admin/compliance/locality-rates", { method: "PUT", body: payload });

export const deleteLocalityRate = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-rates/${id}`, { method: "DELETE" });

// ── Source Evidence ────────────────────────────────────────────────────────

export const getSourceArtifacts = () =>
  apiFetch("/api/super-admin/compliance/source-artifacts");

export const createSourceArtifact = (payload) =>
  apiFetch("/api/super-admin/compliance/source-artifacts", { method: "POST", body: payload });

export const reviewSourceArtifact = (id) =>
  apiFetch(`/api/super-admin/compliance/source-artifacts/${id}/review`, { method: "PUT" });

// ── Germany statutory registries (Phase 8O) ─────────────────────────────
// Every function below is a thin wrapper over a pre-existing Super-Admin-
// only backend endpoint (Phases 3/4/5/6/8G-1) — this phase adds the
// frontend client, not new backend surface, except getChurchTaxMatrix
// (a genuinely new, read-only endpoint — see service.get_church_tax_matrix's
// own docstring for why it has no create/approve/status counterpart).

// PAP algorithm assets
export const listPapAssets = (taxYear) =>
  apiFetch("/api/super-admin/compliance/germany/pap-assets", { params: taxYear ? { taxYear } : {} });
export const getPapAsset = (id) => apiFetch(`/api/super-admin/compliance/germany/pap-assets/${id}`);
export const approvePapAsset = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-assets/${id}/approve`, { method: "PUT" });
export const setPapAssetStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-assets/${id}/status`, { method: "PUT", params: { status: statusValue } });

// PAP asset ingestion is multipart (raw file + form fields) — apiFetch
// always JSON-encodes its body, so this bypasses it with a raw fetch,
// same auth/refresh-token convention as api/client.js's own rawFetch.
export async function ingestPapAsset({ taxYear, papVersion, effectiveFrom, effectiveTo, sourceAgency, sourceTitle, sourceUrl, sourcePublicationDate, file }) {
  const form = new FormData();
  form.append("taxYear", taxYear);
  form.append("papVersion", papVersion);
  form.append("effectiveFrom", effectiveFrom);
  if (effectiveTo) form.append("effectiveTo", effectiveTo);
  form.append("sourceAgency", sourceAgency);
  form.append("sourceTitle", sourceTitle);
  if (sourceUrl) form.append("sourceUrl", sourceUrl);
  if (sourcePublicationDate) form.append("sourcePublicationDate", sourcePublicationDate);
  form.append("file", file);
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/api/super-admin/compliance/germany/pap-assets`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

// PAP release governance
export const listPapReleases = (taxYear) =>
  apiFetch("/api/super-admin/compliance/germany/pap-releases", { params: taxYear ? { taxYear } : {} });
export const getPapRelease = (id) => apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}`);
export const getPapReleaseGateStatus = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/gate-status`);
export const createPapRelease = (papAssetId) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-assets/${papAssetId}/release`, { method: "POST" });
export const recordPapReleaseSourceIdentity = (id, notes) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/source-identity`, { method: "PUT", body: { notes } });
export const recordPapReleaseSourceHash = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/source-hash`, { method: "PUT" });
export const recordPapReleaseSourceFinality = (id, body) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/source-finality`, { method: "PUT", body });
export const recordPapReleaseLicensing = (id, body) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/licensing`, { method: "PUT", body });
export const recordPapReleaseGoldenVectors = (id, body) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/golden-vectors`, { method: "PUT", body });
export const recordPapReleaseSecurityCertification = (id, notes) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/security-certification`, { method: "PUT", body: { notes } });
export const markPapReleaseReady = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/ready`, { method: "PUT" });
export const approvePapRelease = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/approve`, { method: "PUT" });
export const rejectPapRelease = (id, reason) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/reject`, { method: "PUT", body: { reason } });
export const activatePapRelease = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/activate`, { method: "POST" });
export const requestPapRollback = (id, reason, targetReleaseId) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/rollback/request`, { method: "POST", body: { reason, targetReleaseId } });
export const rejectPapRollback = (id, reason) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/rollback/reject`, { method: "POST", body: { reason } });
export const approvePapRollback = (id, reason, targetReleaseId) =>
  apiFetch(`/api/super-admin/compliance/germany/pap-releases/${id}/rollback/approve`, { method: "POST", body: { reason, targetReleaseId } });

// Health funds
export const listHealthFunds = (healthFundId) =>
  apiFetch("/api/super-admin/compliance/germany/health-funds", { params: healthFundId ? { healthFundId } : {} });
export const createHealthFund = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/health-funds", { method: "POST", body: payload });
export const approveHealthFund = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/health-funds/${id}/approve`, { method: "PUT" });
export const setHealthFundStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/health-funds/${id}/status`, { method: "PUT", params: { status: statusValue } });

// Germany accident-insurance profiles (Phase 8AJ, 2nd pass) — maker-checker
// workspace, organization-scoped (unlike health funds above, which are
// global). Publishing one materializes it into the existing
// EmployerTaxProfile mechanism the engine actually reads — see
// models.GermanyAccidentInsuranceProfile's own docstring.
export const listGermanyAccidentInsuranceProfiles = (organizationId) =>
  apiFetch("/api/super-admin/compliance/germany/accident-insurance-profiles", { params: organizationId ? { organizationId } : {} });
export const createGermanyAccidentInsuranceProfile = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/accident-insurance-profiles", { method: "POST", body: payload });
export const approveGermanyAccidentInsuranceProfile = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/accident-insurance-profiles/${id}/approve`, { method: "PUT" });
export const setGermanyAccidentInsuranceProfileStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/accident-insurance-profiles/${id}/status`, { method: "PUT", params: { status: statusValue } });

// U1 tariffs (sickness reimbursement) — child records of health funds
export const listU1Tariffs = (healthFundId) =>
  apiFetch("/api/super-admin/compliance/germany/health-funds/u1-tariffs", { params: healthFundId ? { healthFundId } : {} });
export const createU1Tariff = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/health-funds/u1-tariffs", { method: "POST", body: payload });
export const approveU1Tariff = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/health-funds/u1-tariffs/${id}/approve`, { method: "PUT" });
export const setU1TariffStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/health-funds/u1-tariffs/${id}/status`, { method: "PUT", params: { status: statusValue } });

// Contribution ceilings
export const listContributionCeilings = (branch) =>
  apiFetch("/api/super-admin/compliance/germany/contribution-ceilings", { params: branch ? { branch } : {} });
export const createContributionCeiling = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/contribution-ceilings", { method: "POST", body: payload });
export const approveContributionCeiling = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/contribution-ceilings/${id}/approve`, { method: "PUT" });
export const setContributionCeilingStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/contribution-ceilings/${id}/status`, { method: "PUT", params: { status: statusValue } });

// PV configurations
export const listPvConfigurations = (childCategory, isSaxony) =>
  apiFetch("/api/super-admin/compliance/germany/pv-configurations", {
    params: { ...(childCategory ? { childCategory } : {}), ...(isSaxony !== undefined && isSaxony !== "" ? { isSaxony } : {}) },
  });
export const createPvConfiguration = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/pv-configurations", { method: "POST", body: payload });
export const approvePvConfiguration = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/pv-configurations/${id}/approve`, { method: "PUT" });
export const setPvConfigurationStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/pv-configurations/${id}/status`, { method: "PUT", params: { status: statusValue } });

// Church tax (16-Land matrix, read-only)
export const getChurchTaxMatrix = () => apiFetch("/api/super-admin/compliance/germany/church-tax");

// Church-tax exceptions (Phase 8AM) — sub-Land denomination/location
// overrides with the same maker-checker + source-evidence lifecycle as
// health funds. NOTE: the approve endpoint is POST here (not PUT).
export const listGermanyChurchTaxExceptions = (landCode) =>
  apiFetch("/api/super-admin/compliance/germany/church-tax-exceptions", { params: landCode ? { landCode } : {} });
export const createGermanyChurchTaxException = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/church-tax-exceptions", { method: "POST", body: payload });
export const approveGermanyChurchTaxException = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/church-tax-exceptions/${id}/approve`, { method: "POST" });
export const setGermanyChurchTaxExceptionStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/church-tax-exceptions/${id}/status`, { method: "PUT", params: { status: statusValue } });

// Earning/deduction taxability (Phase 8T, spec §15 four-dimension model)
export const listEarningTaxabilityRules = (earningType) =>
  apiFetch("/api/super-admin/compliance/germany/earning-taxability-rules", { params: earningType ? { earningType } : {} });
export const createEarningTaxabilityRule = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/earning-taxability-rules", { method: "POST", body: payload });
export const approveEarningTaxabilityRule = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/earning-taxability-rules/${id}/approve`, { method: "PUT" });
export const setEarningTaxabilityRuleStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/earning-taxability-rules/${id}/status`, { method: "PUT", params: { status: statusValue } });

// Germany overtime/shift-premium statutory registries (Phase 8AD)
export const listOvertimePremiumCategories = (categoryCode) =>
  apiFetch("/api/super-admin/compliance/germany/overtime-premium-categories", { params: categoryCode ? { categoryCode } : {} });
export const createOvertimePremiumCategory = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/overtime-premium-categories", { method: "POST", body: payload });
export const approveOvertimePremiumCategory = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/overtime-premium-categories/${id}/approve`, { method: "PUT" });
export const setOvertimePremiumCategoryStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/overtime-premium-categories/${id}/status`, { method: "PUT", params: { status: statusValue } });

export const listOvertimeGrundlohnCaps = (dimension) =>
  apiFetch("/api/super-admin/compliance/germany/overtime-grundlohn-caps", { params: dimension ? { dimension } : {} });
export const createOvertimeGrundlohnCap = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/overtime-grundlohn-caps", { method: "POST", body: payload });
export const approveOvertimeGrundlohnCap = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/overtime-grundlohn-caps/${id}/approve`, { method: "PUT" });
export const setOvertimeGrundlohnCapStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/overtime-grundlohn-caps/${id}/status`, { method: "PUT", params: { status: statusValue } });

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

// ── Report Templates (jurisdiction-wide, Super Admin-authored statutory
// report blueprints — separate from Compliance's JurisdictionPack, since a
// report template has no rates/slabs/org-assignment) ────────────────────

export const getReportTemplates = (params) => apiFetch("/api/super-admin/report-templates", { params });

export const getReportTemplateDetail = (id) => apiFetch(`/api/super-admin/report-templates/${id}`);

export const upsertReportTemplate = (payload) =>
  apiFetch("/api/super-admin/report-templates", { method: "PUT", body: payload });

export const getReportTemplateVersions = (templateKey) =>
  apiFetch(`/api/super-admin/report-templates/by-key/${encodeURIComponent(templateKey)}/versions`);

export const setReportTemplateStatus = (id, status) =>
  apiFetch(`/api/super-admin/report-templates/${id}/status`, { method: "PUT", body: { status } });

// Maker-checker: records the CALLING Super Admin as this template's
// approver. Must be a different person than whoever last edited it before
// the template can go Published/Active — enforced server-side.
export const approveReportTemplate = (id) =>
  apiFetch(`/api/super-admin/report-templates/${id}/approve`, { method: "PUT" });

export const getReportTemplateAudit = (id) => apiFetch(`/api/super-admin/report-templates/${id}/audit`);

export const hardDeleteReportTemplate = (id) =>
  apiFetch(`/api/super-admin/report-templates/${id}`, { method: "DELETE" });

// The enumerable, backend-owned component/data-field catalogs a template's
// authoring UI must pick from — never a free-typed or generic-unrelated
// dropdown; see get_available_report_components/get_available_report_data_fields.
export const getAvailableReportComponents = (reportType) =>
  apiFetch("/api/super-admin/report-templates/available-components", { params: { reportType } });

export const getAvailableReportDataFields = (jurisdictionCountry) =>
  apiFetch("/api/super-admin/report-templates/available-data-fields", { params: { jurisdictionCountry } });

export const upsertReportTemplateComponent = (templateId, payload) =>
  apiFetch(`/api/super-admin/report-templates/${templateId}/components`, { method: "PUT", body: payload });

export const deleteReportTemplateComponent = (componentId) =>
  apiFetch(`/api/super-admin/report-templates/components/${componentId}`, { method: "DELETE" });

export const upsertReportTemplateField = (componentId, payload) =>
  apiFetch(`/api/super-admin/report-templates/components/${componentId}/fields`, { method: "PUT", body: payload });

export const deleteReportTemplateField = (fieldId) =>
  apiFetch(`/api/super-admin/report-templates/fields/${fieldId}`, { method: "DELETE" });

// ── Statutory Filing Calendar (jurisdiction-wide, Super Admin-authored) ──

export const getFilingCalendarEntries = (params) =>
  apiFetch("/api/super-admin/report-templates/filing-calendar", { params });

export const upsertFilingCalendarEntry = (payload) =>
  apiFetch("/api/super-admin/report-templates/filing-calendar", { method: "PUT", body: payload });

export const setFilingCalendarEntryStatus = (id, status) =>
  apiFetch(`/api/super-admin/report-templates/filing-calendar/${id}/status`, { method: "PUT", body: { status } });
