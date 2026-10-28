// Thin API wrapper for the new Super Admin modules (Compliance, Finance,
// Reports, Dashboard charts) — mirrors the existing pages/*.jsx convention
// of calling apiFetch directly, just consolidated into named functions
// since these three modules add far more endpoints than any single
// existing Super Admin page called before.
import { apiFetch, API_BASE, getAccessToken } from "../api/client";

// ── Compliance ───────────────────────────────────────────────────────────

export const getComplianceJurisdictions = () => apiFetch("/api/super-admin/compliance/jurisdictions");

// Full Caribbean jurisdiction master (region-grouped, includes Coming
// Soon entries) — a display-only view, separate from
// getComplianceJurisdictions above (which only ever lists jurisdictions
// that already have real configured data).
export const getCaribbeanJurisdictions = () => apiFetch("/api/super-admin/compliance/caribbean-jurisdictions");

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

// Hard-delete intentionally removed — production compliance packs should
// never be permanently destroyable via the UI. Use
// setCompliancePolicyStatus(id, "Retired") for normal lifecycle
// retirement instead (see JurisdictionLayout.jsx's status dropdown).

// ── Super Admin UI completion (§19 gap-closure Part 11, 2026-09-09) ──────

export const getPackImpactPreview = (id) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/impact-preview`);

// Tax Year/Release Manager (gap-closure Plan Phase 4) — rate-level diff
// between two versions of the same pack.
export const getPackVersionDiff = (fromId, toId) =>
  apiFetch(`/api/super-admin/compliance/policies/${fromId}/compare/${toId}`);

// Emergency hotfix activation — bypasses the distinct-approver gate,
// requires incident_id + justification, always flagged for mandatory
// retrospective review (see HotfixActivateModal.jsx).
export const hotfixActivatePack = (id, payload) =>
  apiFetch(`/api/super-admin/compliance/policies/${id}/hotfix-activate`, { method: "PUT", body: payload });

export const getHotfixActivations = (params) =>
  apiFetch("/api/super-admin/compliance/hotfix-activations", { params });

export const reviewHotfixActivation = (id, payload) =>
  apiFetch(`/api/super-admin/compliance/hotfix-activations/${id}/review`, { method: "PUT", body: payload });

// Golden-test certification (Part 10's harness, generalized to Canada
// gap-closure Phase 8) — trigger a run for a jurisdiction, and read run
// history. jurisdictionCountry defaults to "UK" for back-compat.
// Singapore — read-only calculation preview against one SG pack's rows,
// computed by the backend's production engine (the frontend never does
// statutory payroll maths itself). Writes nothing server-side.
export const previewSingaporeCalculation = (payload) =>
  apiFetch("/api/super-admin/compliance/singapore/calculation-preview", { method: "POST", body: payload });

// Singapore — read-only statutory configuration summary (point-in-time,
// from persisted pack rows only) and the paginated PWM overtime gross
// schedule (global statutory reference data). Both tenant-independent.
export const getSingaporeStatutorySummary = (params) =>
  apiFetch("/api/super-admin/compliance/singapore/statutory-summary", { params });

export const getSingaporePwmSchedules = (params) =>
  apiFetch("/api/super-admin/compliance/singapore/pwm-schedules", { params });

// Sweden (ZP-SE-ENG-001) — release-gate readiness checklist and a read-only
// calculation preview computed by the backend's production engine (the
// frontend never does statutory payroll maths itself).
export const getSwedenReadiness = (packId) =>
  apiFetch("/api/super-admin/compliance/sweden/readiness", { params: packId ? { packId } : {} });

export const previewSwedenCalculation = (payload) =>
  apiFetch("/api/super-admin/compliance/sweden/calculation-preview", { method: "POST", body: payload });

// Italy (ZP-IT-ENG-001) — release gates G1-G8 and a read-only calculation
// preview run by the backend's production engine.
export const getItalyReadiness = (packId) =>
  apiFetch("/api/super-admin/compliance/italy/readiness", { params: packId ? { packId } : {} });

export const previewItalyCalculation = (payload) =>
  apiFetch("/api/super-admin/compliance/italy/calculation-preview", { method: "POST", body: payload });

// ————— Netherlands (ZP-NL-ENG-001) ————
// Super Admin API: backend/app/modules/payroll/netherlands_router.py. ZP-PRIV:
// the employee list, employer profile, premium decisions, VCR, expat
// decisions and loonaangifte routes are retired (tenant-run / worker data).
// Earning classifications and pension schemes are the PLATFORM catalog only.
// Statutory pack rows (minimum wage, WKR, car windows, period maxima) are
// read-only here — they change only through the governed pack editor.
const NL_SA = "/api/super-admin/compliance/netherlands";

export const listNlOrganizations = () => apiFetch(`${NL_SA}/organizations`);

export const getNlEmployerReadiness = (orgId) =>
  apiFetch(`${NL_SA}/employer-profile/readiness`, { params: { org_id: orgId } });

export const listNlTaxTables = () => apiFetch(`${NL_SA}/tax-tables`);
export const transitionNlTaxTable = (id, action, reason) =>
  apiFetch(`${NL_SA}/tax-tables/${id}/${action}`, { method: "PUT", body: reason ? { reason } : {} });
// Multipart upload: apiFetch JSON-encodes bodies, so the file goes through fetch.
export const importNlTaxTable = async (file, fields) => {
  const formData = new FormData();
  formData.append("file", file);
  Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") formData.append(k, v); });
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}${NL_SA}/tax-tables/import`, {
    method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: formData,
  });
  let data = {};
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) throw new Error(data.detail || "Import failed.");
  return data;
};

export const getNlPackRows = (kind, on) => apiFetch(`${NL_SA}/${kind}`, { params: on ? { on } : {} });

export const listNlEarningClassifications = () => apiFetch(`${NL_SA}/earning-classifications`);
export const createNlEarningClassification = (payload) =>
  apiFetch(`${NL_SA}/earning-classifications`, { method: "POST", body: payload });

export const listNlCaos = () => apiFetch(`${NL_SA}/caos`);
export const listNlPensionSchemes = () => apiFetch(`${NL_SA}/pension-schemes`);
export const createNlPensionScheme = (payload) =>
  apiFetch(`${NL_SA}/pension-schemes`, { method: "POST", body: payload });

export const getNlReadiness = () => apiFetch(`${NL_SA}/readiness`);

// ————— Mexico (ZP-MX-ENG-001) ————
// Super Admin API: backend/app/modules/payroll/mexico_router.py. Statutory
// pack content is read-only here (governed pack lifecycle only) and is read
// as in force on an explicit date — omitted, the pack's own effective-from
// is used, never today. Employer-profile calls arrive in Phase 3.
const MX_SA = "/api/super-admin/compliance/mexico";
const mxOn = (on, packId) => ({ params: { ...(on ? { on } : {}), ...(packId ? { pack_id: packId } : {}) } });

export const getMxReadiness = () => apiFetch(`${MX_SA}/readiness`);
// Completion W5-3: per gate, checklist items confirmed by code now vs awaiting signed evidence.
export const getMxGateChecklists = () => apiFetch(`${MX_SA}/readiness/gate-checklists`);
// Final mile X1: the decision register (four-eyes; an approval changes no calculation).
export const listMxDecisions = (gate, status) =>
  apiFetch(`${MX_SA}/decisions`, { params: { ...(gate ? { gate } : {}), ...(status ? { status } : {}) } });
export const proposeMxDecision = (id, body) => apiFetch(`${MX_SA}/decisions/${id}/propose`, { method: "POST", body });
export const approveMxDecision = (id) => apiFetch(`${MX_SA}/decisions/${id}/approve`, { method: "POST" });
export const withdrawMxDecision = (id, body) => apiFetch(`${MX_SA}/decisions/${id}/withdraw`, { method: "POST", body });
export const reviseMxDecision = (id) => apiFetch(`${MX_SA}/decisions/${id}/revise`, { method: "POST" });
export const transcribedMxDecision = (id, body) => apiFetch(`${MX_SA}/decisions/${id}/transcribed`, { method: "POST", body });
export const getMxDecisionsForBlock = (code) => apiFetch(`${MX_SA}/decisions/by-block/${encodeURIComponent(code)}`);
// Final mile X2: the calculation sandbox (writes nothing; candidates watermarked).
export const runMxSandbox = (body) => apiFetch(`${MX_SA}/sandbox/calculate`, { method: "POST", body });
// Final mile X3b: template library tools (read-only; previews watermarked).
export const getMxTemplateCoverage = () => apiFetch(`${MX_SA}/report-templates/coverage`);
export const compareMxReportTemplates = (from, to) => apiFetch(`${MX_SA}/report-templates/compare`, { params: { from, to } });
export const previewMxTemplateInSandbox = (id, body) => apiFetch(`${MX_SA}/report-templates/${id}/sandbox-preview`, { method: "POST", body });
// Phase 10e: pilot grants (four-eyes, revocable, expiring) and the read-only
// list of governed master-data copies (its worker routes stay retired, ZP-PRIV).
export const listMxPilotGrants = () => apiFetch(`${MX_SA}/pilot-grants`);
export const proposeMxPilotGrant = (payload) => apiFetch(`${MX_SA}/pilot-grants`, { method: "POST", body: payload });
export const approveMxPilotGrant = (id) => apiFetch(`${MX_SA}/pilot-grants/${id}/approve`, { method: "POST", body: {} });
export const withdrawMxPilotGrant = (id, reason) =>
  apiFetch(`${MX_SA}/pilot-grants/${id}/withdraw`, { method: "POST", body: { reason } });
export const revokeMxPilotGrant = (id, reason) =>
  apiFetch(`${MX_SA}/pilot-grants/${id}/revoke`, { method: "POST", body: { reason } });
export const listMxMasterCopies = () => apiFetch(`${MX_SA}/master-copies`);
// Phase 10g: the "no new Mexican organisations" switch (four-eyes).
export const getMxOnboardingPause = () => apiFetch(`${MX_SA}/onboarding-pause`);
export const proposeMxOnboardingChange = (payload) => apiFetch(`${MX_SA}/onboarding-pause`, { method: "POST", body: payload });
export const approveMxOnboardingChange = (id) => apiFetch(`${MX_SA}/onboarding-pause/${id}/approve`, { method: "POST", body: {} });
export const withdrawMxOnboardingChange = (id) => apiFetch(`${MX_SA}/onboarding-pause/${id}/withdraw`, { method: "POST", body: {} });
export const listMxOrganizations = () => apiFetch(`${MX_SA}/organizations`);
export const listMxEmployees = (orgId) => apiFetch(`${MX_SA}/employees`, { params: { org_id: orgId } });
export const listMxPacks = () => apiFetch(`${MX_SA}/packs`);
export const getMxActivationReadiness = (packRowId) => apiFetch(`${MX_SA}/packs/${packRowId}/activation-readiness`);
export const getMxIsrTariffs = (on, packId) => apiFetch(`${MX_SA}/isr-tariffs`, mxOn(on, packId));
export const getMxUmaMinWage = (on, packId) => apiFetch(`${MX_SA}/uma-min-wage`, mxOn(on, packId));
export const getMxImssBranches = (on, packId) => apiFetch(`${MX_SA}/imss-branches`, mxOn(on, packId));
export const getMxCeavSchedule = (on, packId) => apiFetch(`${MX_SA}/ceav-schedule`, mxOn(on, packId));
export const getMxInfonavit = (on, packId) => apiFetch(`${MX_SA}/infonavit`, mxOn(on, packId));
export const getMxBenefitsWorkweek = (on, packId) => apiFetch(`${MX_SA}/benefits-workweek`, mxOn(on, packId));
export const listMxIsnStates = () => apiFetch(`${MX_SA}/isn-states`);
// Completion W5-1: one state ISN pack's rows with sources, and the module-direct rules (read-only).
export const getMxIsnContent = (packId, on) => apiFetch(`${MX_SA}/isn-content`, mxOn(on, packId));
export const getMxStatutoryRules = (on) => apiFetch(`${MX_SA}/statutory-rules`, mxOn(on));
export const listMxEarningClassifications = (orgId, on) =>
  apiFetch(`${MX_SA}/earning-classifications`, { params: { ...(orgId ? { org_id: orgId } : {}), ...(on ? { on } : {}) } });
export const createMxEarningClassification = (payload) =>
  apiFetch(`${MX_SA}/earning-classifications`, { method: "POST", body: payload });
export const approveMxEarningClassification = (id) =>
  apiFetch(`${MX_SA}/earning-classifications/${id}/approve`, { method: "POST" });
export const archiveMxEarningClassification = (id, reason) =>
  apiFetch(`${MX_SA}/earning-classifications/${id}/archive`, { method: "POST", body: { reason } });
export const listMxCfdiReleases = () => apiFetch(`${MX_SA}/cfdi-catalogs`);
export const createMxCfdiRelease = (payload) => apiFetch(`${MX_SA}/cfdi-catalogs`, { method: "POST", body: payload });
// Phase 11a: entries are filtered and capped ({ total, limit, counts, entries }).
export const listMxCfdiEntries = (releaseId, params = {}) =>
  apiFetch(`${MX_SA}/cfdi-catalogs/${releaseId}/entries`, { params });
export const listMxPinnedSets = () => apiFetch(`${MX_SA}/cfdi-catalogs/pinned-sets`);
export const loadMxPinnedSet = (releaseId, setId) =>
  apiFetch(`${MX_SA}/cfdi-catalogs/${releaseId}/load-pinned`, { method: "POST", body: { setId } });
export const listMxSystemConcepts = (releaseId) =>
  apiFetch(`${MX_SA}/cfdi-system-concepts`, { params: releaseId ? { releaseId } : {} });
export const proposeMxSystemConcept = (payload) =>
  apiFetch(`${MX_SA}/cfdi-system-concepts`, { method: "POST", body: payload });
export const approveMxSystemConcept = (id) => apiFetch(`${MX_SA}/cfdi-system-concepts/${id}/approve`, { method: "POST" });
export const withdrawMxSystemConcept = (id) => apiFetch(`${MX_SA}/cfdi-system-concepts/${id}/withdraw`, { method: "POST" });
export const addMxCfdiEntry = (releaseId, payload) =>
  apiFetch(`${MX_SA}/cfdi-catalogs/${releaseId}/entries`, { method: "POST", body: payload });
export const transitionMxCfdiRelease = (releaseId, action) =>
  apiFetch(`${MX_SA}/cfdi-catalogs/${releaseId}/${action}`, { method: "PUT" });
// Phase 3 — employers, READ-ONLY for Super Admin (the tenant authors its own
// employer facts). Identifiers come back masked; readiness needs an explicit date.
export const listMxSaEmployers = (orgId) => apiFetch(`${MX_SA}/employers`, { params: { organization_id: orgId } });
export const getMxSaEmployer = (orgId, employerId) =>
  apiFetch(`${MX_SA}/employers/${employerId}`, { params: { organization_id: orgId } });
export const getMxSaEmployerReadiness = (orgId, on) =>
  apiFetch(`${MX_SA}/employer-readiness`, { params: { organization_id: orgId, on } });
export const getMxSaEmployerReadinessSummary = (on) => apiFetch(`${MX_SA}/employer-readiness/summary`, { params: { on } });
// Final mile X5 (C3): ACTIVE CSD references expired / expiring on a date, every organisation (public metadata only).
export const getMxCsdExpiryAlerts = (on) => apiFetch(`${MX_SA}/csd-expiry`, { params: { on } });
// Phase 7 — CFDI lifecycle, read-only (counts by status, UNKNOWN items, pinned release, blocks).
export const getMxCfdiValidations = (orgId) =>
  apiFetch(`${MX_SA}/cfdi/validations`, { params: orgId ? { organization_id: orgId } : {} });
export const getMxSaCfdiLifecycle = (orgId) => apiFetch(`${MX_SA}/cfdi`, { params: orgId ? { organization_id: orgId } : {} });
export const getMxSaAuthorities = (orgId) => apiFetch(`${MX_SA}/authorities`, { params: orgId ? { organization_id: orgId } : {} });

// ————— Brazil (ZP-BR-ENG-001) ————
// Super Admin API: backend/app/modules/payroll/brazil_router.py (Phase 2).
// Mirrors the Netherlands block above: every organisation-scoped call takes an
// explicit orgId (no default organisation). Statutory pack rows (INSS bands,
// IRRF table + reduction, minimum wage, salário-família, FGTS, CPP) are
// READ-ONLY here — they change only through the governed pack editor
// (draft -> review -> approve -> activate), never by a direct edit.
const BR_SA = "/api/super-admin/compliance/brazil";
const ZA_SA = "/api/super-admin/compliance/south-africa";

export const getZaSummary = () => apiFetch(`${ZA_SA}/summary`);

export const listBrOrganizations = () => apiFetch(`${BR_SA}/organizations`);
export const listBrEmployees = (orgId) => apiFetch(`${BR_SA}/employees`, { params: { org_id: orgId } });

export const getBrPackRows = (ruleType, on) =>
  apiFetch(`${BR_SA}/pack-rows`, { params: { rule_type: ruleType, ...(on ? { on } : {}) } });

export const listBrRubricCatalogue = (orgId) =>
  apiFetch(`${BR_SA}/rubric-catalogue`, { params: orgId ? { org_id: orgId } : {} });

export const getBrFpasTable = () => apiFetch(`${BR_SA}/fpas-table`);

export const getBrReadiness = () => apiFetch(`${BR_SA}/readiness`);
export const getBrGates = () => apiFetch(`${BR_SA}/gates`);
// Phase 3 — READ ONLY: the tenant owns its employer facts (identifiers masked).
export const listBrSaEmployers = (orgId) => apiFetch(`${BR_SA}/employers`, { params: { organization_id: orgId } });
export const getBrSaEmployerReadiness = (orgId, on) =>
  apiFetch(`${BR_SA}/employer-readiness`, { params: { organization_id: orgId, on } });
export const getBrSaEmployerReadinessSummary = (on) => apiFetch(`${BR_SA}/employer-readiness/summary`, { params: { on } });
// Phase 4 — READ ONLY: one employee's Brazilian record (identifiers masked).
export const getBrSaEmployee = (employeeId, orgId, on) =>
  apiFetch(`${BR_SA}/employees/${employeeId}`, { params: { organization_id: orgId, ...(on ? { on } : {}) } });

export const runBrGoldenCheck = (payload) =>
  apiFetch(`${BR_SA}/golden-check`, { method: "POST", body: payload });

// Governed collective-agreement registry (spec §9) — no national default.
export const listCollectiveAgreements = (params) =>
  apiFetch("/api/super-admin/compliance/collective-agreements", { params });

export const upsertCollectiveAgreement = (payload) =>
  apiFetch("/api/super-admin/compliance/collective-agreements", { method: "POST", body: payload });

export const setCollectiveAgreementStatus = (id, status, reason) =>
  apiFetch(`/api/super-admin/compliance/collective-agreements/${id}/status`, { method: "POST", body: { status, reason } });

export const runTestCertification = (jurisdictionCountry = "UK") =>
  apiFetch("/api/super-admin/compliance/test-certification/run", {
    method: "POST", body: { jurisdiction_country: jurisdictionCountry },
  });

export const getTestCertificationRuns = (params) =>
  apiFetch("/api/super-admin/compliance/test-certification/runs", { params });

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

// US employer-specific tax profiles (SUI and similar) are tenant
// configuration (ZP-PRIV decision 3): the Super Admin routes are retired and
// tenants use /api/payroll/compliance/employer-tax-profiles.

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

// ── Locality Dataset Manager (ZP-TAX-US-2026-001 §10/§11.1) ────────────────
// The full Draft/Staged/Active/Retired import/diff/stage/approve/activate/
// rollback workflow, alongside (not replacing) the manual-entry endpoints
// above — both operate on the same underlying LocalityDataset/LocalityRate
// tables.

export const getLocalityDatasets = (params) =>
  apiFetch("/api/super-admin/compliance/locality-datasets", { params });

export const getLocalityDatasetRates = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-datasets/${id}/rates`);

export const importLocalityDataset = (payload) =>
  apiFetch("/api/super-admin/compliance/locality-datasets/import", { method: "POST", body: payload });

// "New State Import" bulk tooling (Production-Readiness Plan Phase 3) —
// creates a brand-new Draft JurisdictionPack for a state, pre-populated
// with its full bracket table + standard deduction, in one call instead
// of hand-entering each row through USStateAccordionRow's one-at-a-time
// component editor.
export const bulkImportStateTaxPack = (payload) =>
  apiFetch("/api/super-admin/compliance/tax-configuration/state-import", { method: "POST", body: payload });

export const diffLocalityDataset = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-datasets/${id}/diff`);

export const stageLocalityDataset = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-datasets/${id}/stage`, { method: "PUT" });

export const approveLocalityDataset = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-datasets/${id}/approve`, { method: "PUT" });

export const activateLocalityDataset = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-datasets/${id}/activate`, { method: "PUT" });

export const rollbackLocalityDataset = (id) =>
  apiFetch(`/api/super-admin/compliance/locality-datasets/${id}/rollback`, { method: "PUT" });

// ── Source Evidence ────────────────────────────────────────────────────────

export const getSourceArtifacts = () =>
  apiFetch("/api/super-admin/compliance/source-artifacts");

export const createSourceArtifact = (payload) =>
  apiFetch("/api/super-admin/compliance/source-artifacts", { method: "POST", body: payload });

// Real preserved-file storage (ZP-TAX-US-2026-001 §14.2, gap-closure Plan
// Phase 4) — `apiFetch` above always JSON-encodes its body, so a real file
// upload/binary download needs its own raw fetch call, same pattern
// payrollService.js's downloadPayslip/downloadRunPayslips already use.
export const uploadSourceArtifactFile = async (id, file) => {
  const formData = new FormData();
  formData.append("file", file);
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/api/super-admin/compliance/source-artifacts/${id}/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { /* ignore */ }
    throw new Error(detail || "Upload failed.");
  }
  return res.json();
};

export const downloadSourceArtifactFile = async (id, filenameHint) => {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/api/super-admin/compliance/source-artifacts/${id}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to download file.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameHint || `source_artifact_${id}`;
  a.click();
  URL.revokeObjectURL(url);
};

export const reviewSourceArtifact = (id) =>
  apiFetch(`/api/super-admin/compliance/source-artifacts/${id}/review`, { method: "PUT" });

// Singapore gate / decision evidence: keep the old artifact, mark it superseded by a same-tag replacement.
export const supersedeSourceArtifact = (id, replacementId) =>
  apiFetch(`/api/super-admin/compliance/source-artifacts/${id}/supersede`, { method: "PUT", body: { replacementId } });

// Singapore gate / decision evidence review outcome: ACCEPTED (optional validUntil) or REJECTED (notes required).
export const reviewSgEvidence = (id, { outcome, notes, validUntil }) =>
  apiFetch(`/api/super-admin/compliance/source-artifacts/${id}/sg-review`, {
    method: "PUT", body: { outcome, notes: notes || null, validUntil: validUntil || null },
  });

// Singapore owner decision D1 / D2 / D3 — selected option + reason (counts after memo upload + second-admin review).
export const recordSgDecision = ({ key, selectedValue, reason }) =>
  apiFetch("/api/super-admin/compliance/singapore/decisions", { method: "POST", body: { key, selectedValue, reason } });

// Singapore registry step (Phase 6.10): AVAILABLE (gated server-side) or PLANNED; reason required, audited.
export const transitionSgServiceRegistry = ({ availability, reason }) =>
  apiFetch("/api/super-admin/compliance/singapore/service-registry", { method: "POST", body: { availability, reason } });

// ── India: state/local statutory readiness registry (§16) ─────────────────
// One row per (state/UT, optional local authority, program) — informational
// only, no calculation/onboarding path enforces it yet.

export const getStateLocalReadiness = (params) =>
  apiFetch("/api/super-admin/compliance/state-local-readiness", { params });

export const upsertStateLocalReadiness = (payload) =>
  apiFetch("/api/super-admin/compliance/state-local-readiness", { method: "POST", body: payload });

// ── Taxability rules (India Code Wages classification, §7/§8) ─────────────
// Backs engine/countries/india.py's _calculate_code_wages — which of an
// employee's own named salary components count as "core included wages" vs.
// "excluded, subject to the 50%-cap add-back test." Had NO admin UI at all
// before this (only a read-only backend resolver existed).

export const getTaxabilityRules = (params) =>
  apiFetch("/api/super-admin/compliance/taxability-rules", { params });

export const upsertTaxabilityRule = (payload) =>
  apiFetch("/api/super-admin/compliance/taxability-rules", { method: "POST", body: payload });

export const deleteTaxabilityRule = (id) =>
  apiFetch(`/api/super-admin/compliance/taxability-rules/${id}`, { method: "DELETE" });

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

// Germany accident-insurance profiles are tenant configuration (ZP-PRIV
// decision 3); tenants use /api/payroll/germany/accident-insurance-profiles.

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

// Germany Compliance Pack completeness (Phase 8DJ) — COMPLETE/PARTIAL/INVALID,
// per-component PUBLISHED-row-linked-to-this-pack counts. Backend-authoritative:
// this call surfaces exactly what service.assess_germany_pack_completeness()
// computes — the frontend never invents or re-derives these counts itself.
export const getGermanyPackCompleteness = (packId, asOf) =>
  apiFetch(`/api/super-admin/compliance/germany/compliance-pack/${packId}/completeness`, { params: asOf ? { asOf } : {} });

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

// Germany Minijob/Midijob statutory parameters (Phase 8BK) — same
// effective-dated maker-checker lifecycle as contribution ceilings/PV
// configuration above.
export const listMinijobMidijobParameters = (parameterCode) =>
  apiFetch("/api/super-admin/compliance/germany/minijob-midijob-parameters", { params: parameterCode ? { parameterCode } : {} });
export const createMinijobMidijobParameter = (payload) =>
  apiFetch("/api/super-admin/compliance/germany/minijob-midijob-parameters", { method: "POST", body: payload });
export const approveMinijobMidijobParameter = (id) =>
  apiFetch(`/api/super-admin/compliance/germany/minijob-midijob-parameters/${id}/approve`, { method: "PUT" });
export const setMinijobMidijobParameterStatus = (id, statusValue) =>
  apiFetch(`/api/super-admin/compliance/germany/minijob-midijob-parameters/${id}/status`, { method: "PUT", params: { status: statusValue } });

// ── Platform aggregates (ZP-PRIV B.1/B.2) ────────────────────────────────
// Every cross-tenant total the Super Admin plane sees is k-suppressed: a
// cell covering fewer than 5 workers (money cells: or fewer than 2
// organizations) comes back as this literal token instead of a number.

export const SUPPRESSED = "<5, hidden";

export const SUPPRESSED_EXPLANATION =
  "Hidden: fewer than 5 workers or fewer than 2 organizations in this cell, to protect individuals.";

export const isSuppressed = (value) => value === SUPPRESSED;

// Recharts can't plot the hidden token — chart series get null (a gap)
// instead, and the UI says so next to the chart.
export const numericOrNull = (value) => {
  if (value === null || value === undefined || isSuppressed(value)) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

// The probing defences on aggregate reads (429 query budget, 403
// differencing guard) are expected, recoverable refusals — never an error
// screen. Returns a friendly sentence for them, or null for any other error.
export function aggregateRefusalMessage(err) {
  if (err?.errorCode === "AGGREGATE_QUERY_BUDGET_EXCEEDED" || err?.status === 429) {
    return "You've run a lot of aggregate queries in the last few minutes. Wait a moment, then refresh.";
  }
  if (err?.errorCode === "AGGREGATE_DIFFERENCING_DETECTED") {
    return "This filter combination overlaps a previous query closely enough that it could single out a few people, so it was not run. Broaden or change the filters.";
  }
  return null;
}

// ── Finance ──────────────────────────────────────────────────────────────
// All three are platform aggregates — no per-run rows and no single-
// organization filter. /overview returns jurisdiction x currency x month x
// status cells; /summary per-jurisdiction totals; /by-organization the
// tenant registry with a headcount bucket and payroll activity (no money).

export const getFinanceOverview = (params) => apiFetch("/api/super-admin/finance/overview", { params });

export const getFinanceSummary = (params) => apiFetch("/api/super-admin/finance/summary", { params });

export const getFinanceByOrganization = (params) => apiFetch("/api/super-admin/finance/by-organization", { params });

export const getOrganizationCurrencies = () => apiFetch("/api/super-admin/finance/organization-currencies");

export const updateOrganizationCurrency = (organizationId, currency) =>
  apiFetch(`/api/super-admin/finance/organizations/${organizationId}/currency`, {
    method: "PUT",
    body: { currency },
  });

// ── Statutory Rates ──────────────────────────────────────────────────────

// Read-only: the canonical rates/slabs from whichever tax pack is
// currently Active for this jurisdiction — the same data Compliance's
// Rates editor writes to. Editing happens on the Compliance page.
export const getActiveTaxConfiguration = (params) =>
  apiFetch("/api/super-admin/compliance/active-tax-configuration", { params });

// ── Reports ──────────────────────────────────────────────────────────────

export const getReportsOrganizations = (params) => apiFetch("/api/super-admin/reports/organizations", { params });

// "Workforce totals": k-suppressed headcounts by organization, jurisdiction,
// status and employment type — never a name, code or other identity.
// Params: organization_id, country, status, skip, limit (no search).
export const getReportsEmployees = (params) => apiFetch("/api/super-admin/reports/employees", { params });

// Server-built CSV for a report category. `employees` exports the same
// workforce counts, `payroll` the same aggregate cells as /finance/overview.
export async function downloadReportCsv(type, params = {}) {
  const query = new URLSearchParams({ type });
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== undefined && v !== null) query.set(k, v);
  });
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/api/super-admin/reports/export?${query.toString()}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch { data = {}; }
    const err = new Error(data.detail || data.message || "Failed to export report");
    err.status = res.status;
    err.errorCode = data.error || null;
    throw err;
  }
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

// Money points (payrollTrend gross/net, grossVsNet, payrollByJurisdiction
// grossPay) and employeesByCountry may be SUPPRESSED.
export const getDashboardCharts = (params) => apiFetch("/api/super-admin/dashboard/charts", { params });

// total_payroll_employees / total_payroll_runs may be SUPPRESSED.
export const getDashboardStats = () => apiFetch("/api/super-admin/dashboard/stats");

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

// ── Hong Kong (ZP-HK-ENG-001) — Super Admin, tenant-independent ────────
export const getHongKongStatutorySummary = () => apiFetch("/api/super-admin/compliance/hong-kong/statutory-summary");
export const previewHongKongCalculation = (payload) =>
  apiFetch("/api/super-admin/compliance/hong-kong/calculation-preview", { method: "POST", body: payload });
// Hong Kong statutory configuration administration (governed; Super Admin only)
const HK_CFG = "/api/super-admin/compliance/hong-kong/configuration";
export const getHkConfigVersions = () => apiFetch(`${HK_CFG}/versions`);
export const getHkConfigPack = (packRowId) => apiFetch(`${HK_CFG}/packs/${packRowId}`);
export const getHkConfigResolution = (on) => apiFetch(`${HK_CFG}/resolution`, { params: { on } });
export const compareHkConfig = (fromId, toId) => apiFetch(`${HK_CFG}/compare`, { params: { from: fromId, to: toId } });
export const updateHkConfigRow = (kind, rowId, payload) =>
  apiFetch(`${HK_CFG}/rows/${kind}/${rowId}`, { method: "PUT", body: payload });
// Hong Kong earning-code catalogue (HK-006): read, and a governed dated change of one row.
export const getHkEarningCodes = (on) => apiFetch(`${HK_CFG}/earning-codes`, { params: on ? { on } : {} });
export const splitHkEarningCodeRow = (rowId, payload) =>
  apiFetch(`${HK_CFG}/earning-codes/rows/${rowId}/split`, { method: "POST", body: payload });
export const createHkConfigVersion = (packRowId, version, reason) =>
  apiFetch(`${HK_CFG}/packs/${packRowId}/new-version`, { method: "POST", body: { version, reason } });
// Hong Kong platform control records (Super Admin only)
const HK_SA = "/api/super-admin/compliance/hong-kong";
export const getHkSoftwareApproval = () => apiFetch(`${HK_SA}/ird-software-approval`);
export const transitionHkSoftwareApproval = (payload) =>
  apiFetch(`${HK_SA}/ird-software-approval/transition`, { method: "POST", body: payload });
export const getHkEmpfConfiguration = () => apiFetch(`${HK_SA}/empf-configuration`);
export const createHkEmpfConfiguration = (payload) => apiFetch(`${HK_SA}/empf-configuration`, { method: "POST", body: payload });
export const activateHkEmpfConfiguration = (id, reason) =>
  apiFetch(`${HK_SA}/empf-configuration/${id}/activate`, { method: "POST", body: { reason } });
export const getHkRetentionPolicies = () => apiFetch(`${HK_SA}/retention-policies`);
export const proposeHkRetentionPolicy = (payload) => apiFetch(`${HK_SA}/retention-policies`, { method: "POST", body: payload });
export const approveHkRetentionPolicy = (id) => apiFetch(`${HK_SA}/retention-policies/${id}/approve`, { method: "POST" });
export const getHkReadinessCenter = () => apiFetch(`${HK_SA}/readiness-center`);
export const getHkMonitoring = () => apiFetch(`${HK_SA}/monitoring`);
export const transitionHongKongServiceRegistry = (availability, reason) =>
  apiFetch("/api/super-admin/compliance/hong-kong/service-registry", { method: "POST", body: { availability, reason } });
export const compareHongKongReportTemplates = (fromId, toId) =>
  apiFetch("/api/super-admin/compliance/hong-kong/report-templates/compare", { params: { from: fromId, to: toId } });
// Hong Kong gate / decision / production-verification evidence review outcome: ACCEPTED, or REJECTED (notes required).
export const reviewHkEvidence = (id, { outcome, notes }) =>
  apiFetch(`${HK_SA}/evidence/${id}/review`, { method: "PUT", body: { outcome, notes: notes || null } });
// MPF contribution-day deferral: operator-recorded black rainstorm / No. 8+ signal days (audited).
export const getHkContributionDayDisruptions = () => apiFetch(`${HK_SA}/contribution-day-disruptions`);
export const recordHkContributionDayDisruption = (payload) =>
  apiFetch(`${HK_SA}/contribution-day-disruptions`, { method: "POST", body: payload });
export const getHongKongPackGoldenCheck = (packRowId) =>
  apiFetch(`/api/super-admin/compliance/hong-kong/packs/${packRowId}/golden-check`);

export const getSaudiArabiaPackGoldenCheck = (packRowId) =>
  apiFetch(`/api/super-admin/compliance/saudi-arabia/packs/${packRowId}/golden-check`);

// ————— France (ZP-FR-ENG-001) ————
// ZP-PRIV decision 3: the France employer identity, establishments, AT/MP
// rate packs, effectif, readiness/go-live and DSN are tenant-run (tenant
// routes /api/payroll/france/*), and PAS rates are worker data; their Super
// Admin routes are retired. Only the org picker and pack tooling remain.

// France organizations only (the org's country resolves to FR).
export const listFranceOrganizations = () =>
  apiFetch("/api/organizations", { params: { limit: 200, country_code: "FR" } }).then((data) => data.organizations || []);

// Fill a France tax pack's missing statutory rows from the 2026 catalog
// (insert-only; editable packs only).
export const loadFranceStatutoryDefaults = (packId) =>
  apiFetch(`/api/super-admin/compliance/france/packs/${packId}/load-statutory-defaults`, { method: "POST" });

// ————— Switzerland (ZP-CH-PAYROLL-001) ————
// Super-Admin-owned authority data for the Switzerland Compliance workspace:
// QST tariff file registry (import/validate/approve/activate), the platform
// scheme catalog, earning classification rules and canton wage floors, plus
// the release-gate readiness G1-G7 and the read-only engine preview.
//
// Every CH WRITE carries an Idempotency-Key header (switzerland_http.py
// refuses writes without one) — apiFetch can't send headers, so JSON writes
// go through _chRequest below (same raw-fetch + JSON-encode convention as
// ingestPapAsset) and the tariff-file import through its own FormData fetch.
const CH_SA = "/api/super-admin/compliance/switzerland";

function nextIdempotencyKey() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `ch-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function _chRequest(path, { method = "POST", body } = {}) {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Idempotency-Key": nextIdempotencyKey(),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    const err = new Error(msg || `Request failed (${res.status})`);
    err.status = res.status;
    err.errorCode = data?.error || data?.error_code || null;
    throw err;
  }
  return data;
}

// Release gates G1-G7 + per-canton status, re-derived server-side on every
// read (Switzerland is only ever gated live after staff make it so — this
// endpoint never fabricates a "ready").
export const getSwissReadiness = (on) =>
  apiFetch(`${CH_SA}/readiness`, { params: on ? { on } : {} });

// QST tariff files (statuses: IMPORTED/VALIDATED/APPROVED/ACTIVE/REJECTED/
// SUPERSEDED; every status stays readable for replay).
export const listSwissQstTariffFiles = (params) => apiFetch(`${CH_SA}/qst-tariffs`, { params });
export const getSwissQstTariffFile = (id) => apiFetch(`${CH_SA}/qst-tariffs/${id}`);

// Import one canton's preserved authority tariff file (SHA-256 identity —
// an identical import is refused; audited). Same multipart raw-fetch
// convention as ingestPapAsset above.
export async function importSwissQstTariffFile({ canton, formatVersion, effectiveFrom, effectiveTo,
  taxYear, publicationDate, sourceDocumentId, file }) {
  const form = new FormData();
  form.append("canton", canton);
  form.append("formatVersion", formatVersion);
  form.append("effectiveFrom", effectiveFrom || "");
  if (effectiveTo) form.append("effectiveTo", effectiveTo);
  if (taxYear) form.append("taxYear", String(taxYear));
  if (publicationDate) form.append("publicationDate", publicationDate);
  if (sourceDocumentId) form.append("sourceDocumentId", String(sourceDocumentId));
  form.append("file", file);
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}${CH_SA}/qst-tariffs`, {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Idempotency-Key": nextIdempotencyKey(),
    },
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

// Maker-checker lifecycle: validate (structural) -> approve (a different
// Super Admin than the importer) -> activate (a different one than the
// approver; the canton's overlapping ACTIVE files are superseded).
export const validateSwissQstTariffFile = (id) => _chRequest(`${CH_SA}/qst-tariffs/${id}/validate`);
export const approveSwissQstTariffFile = (id, reason) =>
  _chRequest(`${CH_SA}/qst-tariffs/${id}/approve`, { body: { reason: reason || null } });
export const activateSwissQstTariffFile = (id, reason) =>
  _chRequest(`${CH_SA}/qst-tariffs/${id}/activate`, { body: { reason: reason || null } });

// Platform scheme catalog (organization_id NULL definitions; the org-facing
// payrollService.js listSwissSchemes returns these plus the tenant's own).
export const listSwissCatalogSchemes = (params) => apiFetch(`${CH_SA}/schemes`, { params });
export const getSwissCatalogScheme = (id) => apiFetch(`${CH_SA}/schemes/${id}`);
export const createSwissCatalogScheme = (payload) => _chRequest(`${CH_SA}/schemes`, { body: payload });
export const updateSwissCatalogScheme = (id, payload) =>
  _chRequest(`${CH_SA}/schemes/${id}`, { method: "PUT", body: payload });
export const deleteSwissCatalogScheme = (id) => _chRequest(`${CH_SA}/schemes/${id}`, { method: "DELETE" });
export const approveSwissCatalogScheme = (id, reason) =>
  _chRequest(`${CH_SA}/schemes/${id}/approve`, { body: { reason: reason || null } });
export const activateSwissCatalogScheme = (id, reason) =>
  _chRequest(`${CH_SA}/schemes/${id}/activate`, { body: { reason: reason || null } });

// Earning classification rules (Draft + Approved; only Approved rows govern).
export const listSwissTaxabilityRules = (params) => apiFetch(`${CH_SA}/taxability-rules`, { params });
export const createSwissTaxabilityRule = (payload) => _chRequest(`${CH_SA}/taxability-rules`, { body: payload });
export const approveSwissTaxabilityRule = (id, reason) =>
  _chRequest(`${CH_SA}/taxability-rules/${id}/approve`, { body: { reason: reason || null } });

// Canton wage floors (CH_CANTON_MINIMUM / CH_GAV / CH_NAV).
export const listSwissWageFloors = (params) => apiFetch(`${CH_SA}/wage-floors`, { params });
export const createSwissWageFloor = (payload) => _chRequest(`${CH_SA}/wage-floors`, { body: payload });
export const approveSwissWageFloor = (id, reason) =>
  _chRequest(`${CH_SA}/wage-floors/${id}/approve`, { body: { reason: reason || null } });
export const activateSwissWageFloor = (id, reason) =>
  _chRequest(`${CH_SA}/wage-floors/${id}/activate`, { body: { reason: reason || null } });

// ── Saudi Arabia (ZP-SA-ENG-001) ──────────────────────────────────────────
// ZP-PRIV decision 3: employer GOSI registration, contracts, GOSI liability,
// EOS, final settlement and WPS are tenant-run (tenant routes under
// /api/payroll/saudi-arabia/*); their Super Admin routes are retired.
const SA_SA = "/api/super-admin/compliance/saudi-arabia";

// Release gates for one SA tax pack (packId omitted = the pack in force) and a
// read-only calculation preview against it — both server-side; used by
// SAReadinessPreviewTab.
export const getSaReadiness = (packId) =>
  apiFetch(`${SA_SA}/readiness`, { params: packId ? { packId } : {} });
export const previewSaudiArabiaCalculation = (payload) =>
  apiFetch(`${SA_SA}/calculation-preview`, { method: "POST", body: payload });

