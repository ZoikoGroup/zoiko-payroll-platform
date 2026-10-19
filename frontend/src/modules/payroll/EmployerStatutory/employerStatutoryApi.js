import { api, getStoredUser } from "../../../service/api";

// Tenant-run employer statutory configuration (ZP-PRIV decision 3). Every
// route takes the organization from the login token — never pass an
// organizationId query parameter here. Backend:
// backend/app/modules/payroll/tenant_statutory_router.py (mounted under
// /api/payroll), plus the existing org-scoped Saudi GOSI liability list and
// the /api/payroll/filings compliance endpoint in payroll/router.py.

const P = "/api/payroll";

// ── Organization context ───────────────────────────────────────────────
export const getComplianceData = () => api.get(`${P}/filings`);
export const getOrganizationDetail = () => api.get("/api/organizations/me/detail");
export const storedOrganizationId = () => getStoredUser()?.organization_id ?? null;

// ── France ─────────────────────────────────────────────────────────────
export const getFranceEmployerProfile = () => api.get(`${P}/france/employer-profile`);
export const upsertFranceEmployerProfile = (payload) => api.put(`${P}/france/employer-profile`, payload);
export const recordFranceEffectif = (payload) => api.post(`${P}/france/effectif`, payload);
export const correctFranceEffectif = (payload) => api.post(`${P}/france/effectif/corrections`, payload);
export const listFranceEstablishments = () => api.get(`${P}/france/establishments`);
export const createFranceEstablishment = (payload) => api.post(`${P}/france/establishments`, payload);
export const updateFranceEstablishment = (id, payload) => api.put(`${P}/france/establishments/${id}`, payload);
export const listFranceRatePacks = (siret) =>
  api.get(`${P}/france/establishment-rate-packs`, { params: { siret } });
export const appendFranceRatePack = (payload) => api.put(`${P}/france/establishment-rate-packs`, payload);
export const updateFranceRatePack = (id, payload) => api.patch(`${P}/france/establishment-rate-packs/${id}`, payload);
export const closeFranceRatePack = (id, effectiveTo) =>
  api.post(`${P}/france/establishment-rate-packs/${id}/close`, { effectiveTo });
export const getFranceReadiness = (forPeriod) => api.get(`${P}/france/readiness`, { params: { for_period: forPeriod } });
export const setFranceLive = (evidence) => api.post(`${P}/france/go-live`, { evidence: evidence || null });

// ── Germany accident insurance ─────────────────────────────────────────
export const listGermanyAccidentProfiles = () => api.get(`${P}/germany/accident-insurance-profiles`);
export const createGermanyAccidentProfile = (payload) => api.post(`${P}/germany/accident-insurance-profiles`, payload);
export const approveGermanyAccidentProfile = (id) => api.put(`${P}/germany/accident-insurance-profiles/${id}/approve`);
export const setGermanyAccidentProfileStatus = (id, status) =>
  api.put(`${P}/germany/accident-insurance-profiles/${id}/status`, undefined, { params: { status } });

// ── Saudi Arabia GOSI ──────────────────────────────────────────────────
export const listSaEmployerProfiles = () => api.get(`${P}/saudi-arabia/employer-profiles`);
export const createSaEmployerProfile = (payload) => api.post(`${P}/saudi-arabia/employer-profiles`, payload);
export const approveSaEmployerProfile = (id) => api.post(`${P}/saudi-arabia/employer-profiles/${id}/approve`);
export const listSaGosiLiabilities = () => api.get(`${P}/saudi-arabia/gosi-liabilities`);
export const markSaGosiLiabilityPaid = (id, paymentReference) =>
  api.post(`${P}/saudi-arabia/gosi-liabilities/${id}/paid`, { paymentReference });

// ── Netherlands premium decisions (snake_case bodies) ──────────────────
export const listNlPremiumDecisions = () => api.get(`${P}/netherlands/premium-decisions`);
export const createNlPremiumDecision = (payload) => api.post(`${P}/netherlands/premium-decisions`, payload);
export const activateNlPremiumDecision = (id) => api.put(`${P}/netherlands/premium-decisions/${id}/activate`);

// ── Netherlands 30% facility decisions (snake_case bodies) ─────────────
export const listNlExpatDecisions = () => api.get(`${P}/netherlands/expat-decisions`);
export const createNlExpatDecision = (payload) => api.post(`${P}/netherlands/expat-decisions`, payload);
// action: "verify" | "revoke"
export const transitionNlExpatDecision = (id, action) => api.put(`${P}/netherlands/expat-decisions/${id}/${action}`);

// ── Netherlands earning classifications / pension schemes ──────────────
// Lists return the platform catalog (organization_id null) plus your own rows.
export const listNlEarningClassifications = () => api.get(`${P}/netherlands/earning-classifications`);
export const createNlEarningClassification = (payload) => api.post(`${P}/netherlands/earning-classifications`, payload);
export const listNlPensionSchemes = () => api.get(`${P}/netherlands/pension-schemes`);
export const createNlPensionScheme = (payload) => api.post(`${P}/netherlands/pension-schemes`, payload);

// ── Switzerland read-only calculation preview ──────────────────────────
export const previewSwissCalculation = (payload) => api.post(`${P}/switzerland/calculation-preview`, payload);

// ── Your employees (for pickers) ───────────────────────────────────────
export const listOrgEmployees = async () => {
  const res = await api.get(`${P}/employees`, { params: { limit: 1000 } });
  const list = res?.items || res?.data || res || [];
  return Array.isArray(list) ? list : [];
};

// ── Employer tax profiles (US SUI and similar) ─────────────────────────
export const listEmployerTaxProfiles = (jurisdictionId) =>
  api.get(`${P}/compliance/employer-tax-profiles`, { params: { jurisdictionId } });
export const upsertEmployerTaxProfile = (payload) => api.put(`${P}/compliance/employer-tax-profiles`, payload);
export const deleteEmployerTaxProfile = (id) => api.delete(`${P}/compliance/employer-tax-profiles/${id}`);

// ── Collective agreements ──────────────────────────────────────────────
export const listCollectiveAgreements = (country) =>
  api.get(`${P}/compliance/collective-agreements`, { params: { country } });
export const upsertCollectiveAgreement = (payload) => api.post(`${P}/compliance/collective-agreements`, payload);
export const setCollectiveAgreementStatus = (id, status, reason) =>
  api.post(`${P}/compliance/collective-agreements/${id}/status`, { status, reason: reason || null });

// ── Statutory filing records ───────────────────────────────────────────
export const upsertFilingRecord = (payload) => api.put(`${P}/filings/records`, payload);
export const deleteFilingRecord = (id) => api.delete(`${P}/filings/records/${id}`);

// api.js throws Error(message = server `detail`, already flattened from a
// 422 list of {loc,msg}) with err.status. Turn that into something
// friendly; never surface raw JSON.
export function describeError(err, fallback = "Something went wrong. Please try again.") {
  if (!err) return null;
  if (err.status === 403) return "You don't have permission to do this. Ask your organization admin.";
  if (err.status === 401) return "Your session has expired. Please sign in again.";
  const text = typeof err.message === "string" ? err.message.trim() : "";
  if (!text || text.startsWith("{") || text.startsWith("[")) return fallback;
  return text;
}
