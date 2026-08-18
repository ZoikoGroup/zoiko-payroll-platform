// API wrapper for the new generic jurisdiction/tax hierarchy engine
// (Super Admin's Jurisdiction Explorer). Additive, separate surface from
// superAdminService.js's existing Compliance/Statutory Rates calls — the
// old endpoints and this new one both exist and serve different data
// (old = JurisdictionPack/ContributionRate/TaxSlab, new = the generic
// Country/Jurisdiction/Tax/TaxVersion hierarchy).
import { apiFetch } from "../api/client";

const BASE = "/api/super-admin/tax-hierarchy";

// ── Static reference metadata ────────────────────────────────────────────
export const getCountries = () => apiFetch(`${BASE}/countries`);
export const getJurisdictionLevels = (countryId) => apiFetch(`${BASE}/countries/${countryId}/levels`);

// ── Jurisdiction tree ────────────────────────────────────────────────────
export const getJurisdictionChildren = ({ parentId, countryId } = {}) =>
  apiFetch(`${BASE}/jurisdictions`, { params: { parent_id: parentId, country_id: countryId } });

export const getJurisdictionDetail = (id) => apiFetch(`${BASE}/jurisdictions/${id}`);

export const upsertJurisdiction = (payload) =>
  apiFetch(`${BASE}/jurisdictions`, { method: "PUT", body: payload });

// ── Tax ──────────────────────────────────────────────────────────────────
export const getTaxesForJurisdiction = (jurisdictionId) =>
  apiFetch(`${BASE}/jurisdictions/${jurisdictionId}/taxes`);

export const upsertTax = (payload) => apiFetch(`${BASE}/taxes`, { method: "PUT", body: payload });

// ── TaxVersion ───────────────────────────────────────────────────────────
export const getTaxVersions = (taxId, jurisdictionId) =>
  apiFetch(`${BASE}/taxes/${taxId}/versions`, { params: { jurisdiction_id: jurisdictionId } });

export const getTaxVersionDetail = (id) => apiFetch(`${BASE}/tax-versions/${id}`);

export const upsertTaxVersion = (payload) =>
  apiFetch(`${BASE}/tax-versions`, { method: "PUT", body: payload });

export const setTaxVersionStatus = (id, status) =>
  apiFetch(`${BASE}/tax-versions/${id}/status`, { method: "PUT", body: { status } });

// ── TaxRule / TaxRuleSlab / TaxRuleRate ─────────────────────────────────
export const getTaxRules = (taxVersionId) => apiFetch(`${BASE}/tax-versions/${taxVersionId}/rules`);

export const upsertTaxRule = (payload) => apiFetch(`${BASE}/tax-rules`, { method: "PUT", body: payload });
export const deleteTaxRule = (id) => apiFetch(`${BASE}/tax-rules/${id}`, { method: "DELETE" });

export const upsertTaxRuleSlab = (payload) => apiFetch(`${BASE}/tax-rule-slabs`, { method: "PUT", body: payload });
export const deleteTaxRuleSlab = (id) => apiFetch(`${BASE}/tax-rule-slabs/${id}`, { method: "DELETE" });

export const upsertTaxRuleRate = (payload) => apiFetch(`${BASE}/tax-rule-rates`, { method: "PUT", body: payload });
export const deleteTaxRuleRate = (id) => apiFetch(`${BASE}/tax-rule-rates/${id}`, { method: "DELETE" });

// ── TaxParameter ─────────────────────────────────────────────────────────
export const getTaxParameters = (taxVersionId) => apiFetch(`${BASE}/tax-versions/${taxVersionId}/parameters`);
export const upsertTaxParameter = (payload) => apiFetch(`${BASE}/tax-parameters`, { method: "PUT", body: payload });
export const deleteTaxParameter = (id) => apiFetch(`${BASE}/tax-parameters/${id}`, { method: "DELETE" });

// ── Applicability / Audit ────────────────────────────────────────────────
export const getJurisdictionApplicability = (jurisdictionId) =>
  apiFetch(`${BASE}/jurisdictions/${jurisdictionId}/applicability`);

export const getTaxVersionAudit = (taxVersionId) => apiFetch(`${BASE}/tax-versions/${taxVersionId}/audit`);

// ── Organization-facing (also usable from an org-scoped admin screen later) ──
export const getApplicableComplianceConfiguration = (organizationId, payrollDate) =>
  apiFetch(`/api/organizations/${organizationId}/compliance/applicable`, { params: { payroll_date: payrollDate } });

export const getOrgJurisdictionAssignments = (organizationId) =>
  apiFetch(`/api/organizations/${organizationId}/compliance/jurisdiction-assignments`);

export const upsertOrgJurisdictionAssignment = (organizationId, payload) =>
  apiFetch(`/api/organizations/${organizationId}/compliance/jurisdiction-assignments`, { method: "PUT", body: payload });
