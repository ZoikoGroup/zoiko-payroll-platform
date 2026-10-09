import { api, getAccessToken, API_BASE_URL } from "./api";
import { getCurrencyForCountry, getCountryNameFromCode, normalizeCountryCode } from "../utils/currency";

// ── Company Profile ────────────────────────────────────
export const getCompanyProfile = async () => {
  try {
    const data = await api.get("/api/payroll/filings");
    const company = data?.company || data || null;
    if (!company) return null;
    // Map jurisdiction to currency code — delegates to utils/currency.js's
    // comprehensive map (46 currencies) instead of a narrow IN/US/UK-only
    // table, which silently fell back to USD for AU/DE/CA and anything else.
    const jurisdiction = company.jurisdictionCountry || company.jurisdiction_country || "";
    const currencyInfo = getCurrencyForCountry(jurisdiction);
    return {
      ...company,
      currency: currencyInfo?.code || "USD",
    };
  } catch {
    return null;
  }
};

// ── Compliance packs (inlined from compliancePacks.js) ──
export const COMPLIANCE_COUNTRIES = [
  { code: "IN", name: "India" },
  { code: "US", name: "United States" },
  { code: "UK", name: "United Kingdom" },
  { code: "AU", name: "Australia" },
  { code: "DE", name: "Germany" },
  { code: "CA", name: "Canada" },
  // Caribbean production jurisdictions (2026-09-21). The ~25 other
  // Caribbean jurisdictions ("Coming Soon") are NOT listed here — this
  // array feeds the real, configurable Compliance jurisdiction picker;
  // Coming Soon entries live only in utils/caribbeanJurisdictions.js's
  // region-grouped master, which is a display-only view.
  { code: "BB", name: "Barbados" },
  { code: "KY", name: "Cayman Islands" },
  { code: "DO", name: "Dominican Republic" },
  { code: "GY", name: "Guyana" },
  { code: "JM", name: "Jamaica" },
  { code: "BS", name: "Bahamas" },
  { code: "TT", name: "Trinidad and Tobago" },
  // France (2026-09-24, ZP-FR-ENG-001) — Europe expansion.
  { code: "FR", name: "France" },
  // Ireland (2026-09-25, ZP-IE-ENG-001) — Europe expansion.
  { code: "IE", name: "Ireland" },
];

export const DEFAULT_COUNTRY = "IN";

// Delegates to utils/currency.js's comprehensive country/currency map
// instead of a narrow IN/US/UK-only table, which silently defaulted every
// other jurisdiction (AU/DE/CA...) back to "India" — e.g. the Compliance
// page's "{country} compliance pack" badge. Handles both storage forms seen
// in this field historically — a 2-letter code ("AU") from the country
// dropdown, or a full name ("India") from the old schema default.
export function getCountryMeta(country) {
  if (!country) return { name: "India" };
  const code = normalizeCountryCode(country) || (country.length === 2 ? country.toUpperCase() : "");
  const name = getCountryNameFromCode(code) || country;
  return { name };
}

export function getFieldPack(country) {
  return [
    { label: "Company Legal Name", field: "name", type: "text" },
    { label: "Company Type", field: "type", type: "text" },
    { label: "Tax Registration No. (PAN/GST)", field: "taxNo", type: "text" },
    { label: "Employer ID", field: "employerId", type: "text" },
    { label: "Registered Address", field: "address", type: "text" },
    { label: "Industry", field: "industry", type: "text" },
    { label: "Jurisdiction — Country", field: "jurisdictionCountry", type: "text" },
    { label: "Jurisdiction — State", field: "jurisdictionState", type: "text" },
    { label: "Compliance Pack", field: "compliancePack", type: "text" },
  ];
}

const RATES_BY_COUNTRY = {
  IN: {
    rows: [
      { id: "pf", label: "Provident Fund", employee: "12%", employer: "12%", total: "24%" },
      { id: "esi", label: "ESI", employee: "0.75%", employer: "3.25%", total: "4%" },
      { id: "pt", label: "Professional Tax", employee: "₹200", employer: "—", total: "₹200" },
      { id: "gratuity", label: "Gratuity", employee: "—", employer: "4.81%", total: "4.81%" },
    ],
  },
  US: {
    rows: [
      { id: "social-security", label: "Social Security", employee: "6.2%", employer: "6.2%", total: "12.4%" },
      { id: "medicare", label: "Medicare", employee: "1.45%", employer: "1.45%", total: "2.9%" },
      { id: "federal-unemployment", label: "Federal Unemployment (FUTA)", employee: "—", employer: "6%", total: "6%" },
    ],
  },
  UK: {
    rows: [
      { id: "national-insurance", label: "National Insurance", employee: "8% (primary) / 2% (upper)", employer: "13.8%", total: "21.8% (employee) + 13.8%" },
      { id: "employer-pension", label: "Workplace Pension (Employer)", employee: "—", employer: "3% minimum", total: "3%" },
    ],
  },
  // Explicit DE entry so a Germany org never inherits India's PF/ESI/PT
  // rows via the DEFAULT_COUNTRY fallback below. Only the flat, non-
  // conditional statutory rates already certified in the backend engine
  // (backend/app/modules/payroll/hardcoded_defaults.py — RV/ALV/GKV general
  // rate, backend/.../engine/germany_pap/core.py — church tax per Land) are
  // shown here. PV and the GKV supplementary rate are genuinely registry-
  // driven (vary by Land/Saxony/dependents/fund) — honestly labeled as
  // varying rather than flattened into one invented number (Phase 8E-2 F1).
  // Display-only duplicates of the backend engine's certified flat rates —
  // NOT authoritative for computation. If a registry/DB override is later added
  // for RV/ALV/GKV these labels must be sourced from the contribution-rates API
  // instead. (2026-09-15 registry-readiness audit marker.)
  DE: {
    rows: [
      { id: "rv", label: "Pension Insurance (Rentenversicherung)", employee: "9.30%", employer: "9.30%", total: "18.60%" },
      { id: "alv", label: "Unemployment Insurance (Arbeitslosenversicherung)", employee: "1.30%", employer: "1.30%", total: "2.60%" },
      { id: "gkv", label: "Health Insurance (Krankenversicherung, general rate)", employee: "7.30% + ½ fund supplement", employer: "7.30% + ½ fund supplement", total: "14.60% + fund supplement (registry-driven)" },
      { id: "pv", label: "Long-Term Care Insurance (Pflegeversicherung)", employee: "Varies — Saxony & dependents", employer: "Varies — Saxony & dependents", total: "Registry-driven — see Germany calculation preview" },
      { id: "church-tax", label: "Church Tax (Kirchensteuer)", employee: "8% (Bavaria, Baden-Württemberg) or 9% (other Länder) of income tax, if liable", employer: "—", total: "8–9% of income tax, if liable" },
    ],
  },
};

export function getComplianceRates(country) {
  return RATES_BY_COUNTRY[country] || RATES_BY_COUNTRY[DEFAULT_COUNTRY];
}

const SLABS_BY_COUNTRY = {
  IN: {
    slabs: [
      { id: "in-1", min: "₹0", max: "₹4,00,000", rate: "Nil", tax: "No tax (up to ₹4L)" },
      { id: "in-2", min: "₹4,00,001", max: "₹8,00,000", rate: "5%", tax: "5% of income over ₹4L" },
      { id: "in-3", min: "₹8,00,001", max: "₹12,00,000", rate: "10%", tax: "₹20,000 + 10% over ₹8L" },
      { id: "in-4", min: "₹12,00,001", max: "₹16,00,000", rate: "15%", tax: "₹60,000 + 15% over ₹12L" },
      { id: "in-5", min: "₹16,00,001", max: "₹20,00,000", rate: "20%", tax: "₹1,20,000 + 20% over ₹16L" },
      { id: "in-6", min: "₹20,00,001", max: "₹24,00,000", rate: "25%", tax: "₹2,00,000 + 25% over ₹20L" },
      { id: "in-7", min: "₹24,00,001", max: "Above", rate: "30%", tax: "₹3,00,000 + 30% over ₹24L" },
    ],
  },
  US: {
    slabs: [
      { id: "us-1", min: "$0", max: "$11,925", rate: "10%", tax: "10% of income" },
      { id: "us-2", min: "$11,926", max: "$48,475", rate: "12%", tax: "$1,192.50 + 12% over $11,925" },
      { id: "us-3", min: "$48,476", max: "$103,350", rate: "22%", tax: "$5,570.50 + 22% over $48,475" },
      { id: "us-4", min: "$103,351", max: "$197,300", rate: "24%", tax: "$17,645 + 24% over $103,350" },
      { id: "us-5", min: "$197,301", max: "$250,525", rate: "32%", tax: "$40,199 + 32% over $197,300" },
      { id: "us-6", min: "$250,526", max: "$626,350", rate: "35%", tax: "$57,131 + 35% over $250,525" },
      { id: "us-7", min: "$626,351", max: "Above", rate: "37%", tax: "$188,364.75 + 37% over $626,350" },
    ],
  },
  UK: {
    slabs: [
      { id: "uk-1", min: "£0", max: "£12,570", rate: "0%", tax: "Personal allowance" },
      { id: "uk-2", min: "£12,571", max: "£50,270", rate: "20%", tax: "20% over £12,570" },
      { id: "uk-3", min: "£50,271", max: "£125,140", rate: "40%", tax: "£7,540 + 40% over £50,270" },
      { id: "uk-4", min: "£125,141", max: "Above", rate: "45%", tax: "£37,488 + 45% over £125,140" },
    ],
  },
  // Explicit DE entry (Phase 8E-2 F1) so Germany never inherits India's
  // slab table via the DEFAULT_COUNTRY fallback below. Unlike IN/US/UK,
  // German wage tax (Lohnsteuer) is not a published bracket table in this
  // system — it is computed by the BMF Programmablaufplan (PAP) formula,
  // and PAP execution is intentionally blocked (PAP_SOURCE_FINALITY=OPEN;
  // see docs/PHASE_8D_GERMANY_PAP_PRODUCTION_GATE_ASSESSMENT_REPORT.md).
  // No bracket values are invented here.
  DE: {
    slabs: [
      {
        id: "de-1",
        min: "—",
        max: "—",
        rate: "Not specified",
        tax: "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION — Lohnsteuer is computed via the BMF Programmablaufplan (PAP) formula, not published brackets; PAP execution is intentionally not yet active.",
      },
    ],
  },
};

export function getTaxSlabs(country) {
  return SLABS_BY_COUNTRY[country] || SLABS_BY_COUNTRY[DEFAULT_COUNTRY];
}

export function getPolicyBasedExtraction(countryCode = DEFAULT_COUNTRY) {
  const contributionRates = (getComplianceRates(countryCode).rows || []).map((row) => ({
    id: row.id,
    label: row.label,
    employee: row.employee,
    employer: row.employer,
    total: row.total,
  }));

  const taxSlabs = (getTaxSlabs(countryCode).slabs || []).map((row) => ({
    id: row.id,
    min: row.min,
    max: row.max,
    rate: row.rate,
    tax: row.tax,
  }));

  return {
    contributionRates,
    taxSlabs,
    requirements: [
      {
        label: "Company policy pack",
        note: `Using the configured ${getCountryMeta(countryCode).name} compliance policy defaults.`,
      },
    ],
  };
}

export function normalizeComplianceDocument(doc, countryCode = DEFAULT_COUNTRY) {
  const normalized = { ...doc };
  const hasExtractedData = Boolean(
    normalized?.extracted &&
      ((normalized.extracted.contributionRates && normalized.extracted.contributionRates.length > 0) ||
        (normalized.extracted.taxSlabs && normalized.extracted.taxSlabs.length > 0) ||
        (normalized.extracted.requirements && normalized.extracted.requirements.length > 0))
  );

  if ((normalized.status === "parsed" || normalized.status === "failed") && !hasExtractedData) {
    normalized.extracted = getPolicyBasedExtraction(countryCode);
    normalized.extractionSource = "policy";
    // Preserve the backend's actual error message so the UI can show it
    normalized.extractionError = normalized.errorMessage || normalized.error || null;
  } else if (normalized.status === "processing" && !hasExtractedData) {
    normalized.extracted = null;
    normalized.extractionSource = null;
  } else if (hasExtractedData) {
    normalized.extractionSource = "backend";
  }

  return normalized;
}

// ── Dashboard ──────────────────────────────────────────
export const getDashboardSummary = async ({ year, month } = {}) => {
  try {
    const params = {};
    if (year) params.year = year;
    if (month) params.month = month;
    return await api.get("/api/payroll/dashboard/summary", { params });
  } catch {
    return { totalPayrollCost: 0, headcount: 0, activeCount: 0, pendingApprovals: 0, totalGross: 0, totalTaxes: 0, totalNet: 0 };
  }
};

export const getDashboardTrend = async ({ months = 6, year, month } = {}) => {
  try {
    const params = { months };
    if (year) params.year = year;
    if (month) params.month = month;
    const res = await api.get("/api/payroll/dashboard/trend", { params });
    return Array.isArray(res) ? res : [];
  } catch {
    return [];
  }
};

export const getDashboardRecentRuns = async ({ year, month } = {}) => {
  try {
    const params = {};
    if (year) params.year = year;
    if (month) params.month = month;
    const res = await api.get("/api/payroll/runs", { params });
    const runs = Array.isArray(res) ? res : [];
    return runs.slice(0, 5);
  } catch {
    return [];
  }
};

export const getRecentActivity = async ({ year, month } = {}) => {
  try {
    const params = {};
    if (year) params.year = year;
    if (month) params.month = month;
    const res = await api.get("/api/payroll/dashboard/activity", { params });
    return Array.isArray(res) ? res : [];
  } catch {
    return [];
  }
};

export const getDashboardBreakdowns = async ({ year, month } = {}) => {
  try {
    const params = {};
    if (year) params.year = year;
    if (month) params.month = month;
    return await api.get("/api/payroll/dashboard/breakdowns", { params });
  } catch {
    return { byDepartment: [], payTypes: [], deductions: [] };
  }
};

// ── Employees ──────────────────────────────────────────
export const getEmployees = async (params) => {
  try {
    const res = await api.get("/api/payroll/employees", { params });
    const list = res?.items || res?.data || res || [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
};

export const getEmployeeById = async (id) => {
  try {
    return await api.get(`/api/payroll/employees/${id}`);
  } catch (err) {
    throw err;
  }
};

export const createEmployee = async (payload) => {
  try {
    return await api.post("/api/payroll/employees", payload);
  } catch (err) {
    throw err;
  }
};

export const updateEmployee = async (id, payload) => {
  try {
    return await api.put(`/api/payroll/employees/${id}`, payload);
  } catch (err) {
    throw err;
  }
};

// ── Germany statutory profile / ELStAM boundary (Phase 8N) ──────────────
// Never calls ELSTER/BZSt — these are plain CRUD/import calls against
// Zoiko's own backend, exactly like every other function in this file.

export const getEmployeeStatutoryProfile = async (employeeId, asOf) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/statutory-profile`, {
      params: asOf ? { as_of: asOf } : {},
    });
  } catch (err) {
    throw err;
  }
};

export const getEmployeeStatutoryProfileHistory = async (employeeId) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/statutory-profile/history`);
  } catch (err) {
    throw err;
  }
};

export const createEmployeeStatutoryProfile = async (employeeId, payload) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/statutory-profile`, payload);
  } catch (err) {
    throw err;
  }
};

export const importEmployeeElstamPayload = async (employeeId, payload) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/elstam-import`, payload);
  } catch (err) {
    throw err;
  }
};

export const getEmployeeElstamImportAttempts = async (employeeId) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/elstam-imports`);
  } catch (err) {
    throw err;
  }
};

// ── Germany ELStAM change-list batches (Phase 8O Super Admin surface) ───
// Metadata-only records (no live ELSTER polling, no auto-apply) — see
// backend service.create_elstam_change_list_batch's own docstring.

export const createElstamChangeListBatch = async (payload) => {
  try {
    return await api.post("/api/payroll/germany/elstam-change-list-batches", payload);
  } catch (err) {
    throw err;
  }
};

export const listElstamChangeListBatches = async () => {
  try {
    return await api.get("/api/payroll/germany/elstam-change-list-batches");
  } catch (err) {
    throw err;
  }
};

export const getElstamChangeListBatch = async (id) => {
  try {
    return await api.get(`/api/payroll/germany/elstam-change-list-batches/${id}`);
  } catch (err) {
    throw err;
  }
};

export const updateElstamChangeListBatchStatus = async (id, payload) => {
  try {
    return await api.patch(`/api/payroll/germany/elstam-change-list-batches/${id}/status`, payload);
  } catch (err) {
    throw err;
  }
};

// Phase 8BF — read-only, org-independent (these registries are global):
// whether Germany's statutory registries are published/effective today, so
// the employee-creation form can warn BEFORE an org admin creates a DE
// employee, instead of only failing closed at actual payroll-run time.
export const getGermanyStatutoryConfigurationReadiness = async () => {
  try {
    return await api.get("/api/payroll/germany/statutory-configuration-readiness");
  } catch (err) {
    throw err;
  }
};

// Phase 8BI — Germany statutory payroll summary, aggregated from real,
// persisted PayslipItem/PayrollRun rows (never a fabricated figure). Optional
// periodStart/periodEnd (YYYY-MM-DD) filter by the owning run's period.
export const getGermanyPayrollSummaryReport = async (params = {}) => {
  try {
    return await api.get("/api/payroll/germany/reports/summary", { params });
  } catch (err) {
    throw err;
  }
};

// ── Germany ELSTER transmission boundary (Phase 8BF) ─────────────────────
// These calls only prepare/validate GermanyElsterTransmission records and
// certificate-config references against Zoiko's own backend — they never
// transmit to ELSTER/BZSt (the transmitter is BLOCKED_EXTERNAL and fails
// closed by design). No Transferticket is ever fabricated.

export const getGermanyElsterCertificateConfig = async () => {
  try {
    return await api.get("/api/payroll/germany/elster-certificate-config");
  } catch (err) {
    throw err;
  }
};

export const setGermanyElsterCertificateConfig = async (payload) => {
  try {
    return await api.put("/api/payroll/germany/elster-certificate-config", payload);
  } catch (err) {
    throw err;
  }
};

export const createGermanyElsterTransmission = async (payload) => {
  try {
    return await api.post("/api/payroll/germany/elster-transmissions", payload);
  } catch (err) {
    throw err;
  }
};

export const listGermanyElsterTransmissions = async () => {
  try {
    return await api.get("/api/payroll/germany/elster-transmissions");
  } catch (err) {
    throw err;
  }
};

export const validateGermanyElsterTransmission = async (id) => {
  try {
    return await api.post(`/api/payroll/germany/elster-transmissions/${id}/validate`);
  } catch (err) {
    throw err;
  }
};

export const transmitGermanyElsterTransmission = async (id) => {
  try {
    return await api.post(`/api/payroll/germany/elster-transmissions/${id}/transmit`);
  } catch (err) {
    throw err;
  }
};

// ── Germany overtime/shift-premium (Phase 8AC-8AH backend; Phase 8AI
// frontend) ──────────────────────────────────────────────────────────
// Fact capture → statutory classification → wage-tax/SI calculation →
// premium component → explicit payslip attachment. Never calls PAP/
// ELStAM/ELSTER — plain CRUD/calculation-preview calls against Zoiko's
// own backend, exactly like every other function in this file.

export const listGermanyOvertimeWorkRecords = async (employeeId, { dateFrom, dateTo } = {}) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/germany-overtime-work-records`, {
      params: { dateFrom: dateFrom || undefined, dateTo: dateTo || undefined },
    });
  } catch (err) {
    throw err;
  }
};

export const createGermanyOvertimeWorkRecord = async (employeeId, payload) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/germany-overtime-work-records`, payload);
  } catch (err) {
    throw err;
  }
};

export const setGermanyOvertimeWorkRecordApproval = async (employeeId, recordId, hrApprovalStatus) => {
  try {
    return await api.post(
      `/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/approval`,
      { hrApprovalStatus },
    );
  } catch (err) {
    throw err;
  }
};

export const classifyGermanyOvertimeWorkRecord = async (employeeId, recordId) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/classification`);
  } catch (err) {
    throw err;
  }
};

export const getGermanyOvertimeClassification = async (employeeId, recordId) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/classification`);
  } catch (err) {
    throw err;
  }
};

export const calculateGermanyOvertimeWageTax = async (employeeId, recordId) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/wage-tax-calculation`);
  } catch (err) {
    throw err;
  }
};

export const getGermanyOvertimeWageTaxResult = async (employeeId, recordId) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/wage-tax-calculation`);
  } catch (err) {
    throw err;
  }
};

export const calculateGermanyOvertimeSocialInsurance = async (employeeId, recordId) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/social-insurance-calculation`);
  } catch (err) {
    throw err;
  }
};

export const getGermanyOvertimeSocialInsuranceResult = async (employeeId, recordId) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/social-insurance-calculation`);
  } catch (err) {
    throw err;
  }
};

export const buildGermanyOvertimePremiumComponents = async (employeeId, recordId) => {
  try {
    return await api.post(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/premium-components`);
  } catch (err) {
    throw err;
  }
};

export const getGermanyOvertimePremiumComponents = async (employeeId, recordId) => {
  try {
    return await api.get(`/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/premium-components`);
  } catch (err) {
    throw err;
  }
};

export const attachGermanyOvertimePremiumComponentToPayslip = async (employeeId, recordId, componentId, payslipItemId) => {
  try {
    return await api.post(
      `/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/premium-components/${componentId}/attach-to-payslip`,
      { payslipItemId },
    );
  } catch (err) {
    throw err;
  }
};

// Phase 8AQ — explicit detach. Reverses attach; never deletes the
// component or its attach history (see GermanyOvertimePanel.jsx).
export const detachGermanyOvertimePremiumComponentFromPayslip = async (employeeId, recordId, componentId) => {
  try {
    return await api.post(
      `/api/payroll/employees/${employeeId}/germany-overtime-work-records/${recordId}/premium-components/${componentId}/detach-from-payslip`,
    );
  } catch (err) {
    throw err;
  }
};

// Phase 8AO — batch attach. Still explicit/operator-initiated (see
// GermanyOvertimePanel.jsx's own docstring) — the caller supplies exact
// (componentId, payslipItemId) pairs; every pair is re-validated
// server-side regardless of what this UI believes about eligibility.
export const listGermanyOvertimePremiumComponentsForBatchAttach = async ({ employeeId, workDateFrom, workDateTo, attachmentState } = {}) => {
  try {
    return await api.get("/api/payroll/germany-overtime-premium-components/eligible-for-batch-attach", {
      params: {
        employeeId: employeeId || undefined, workDateFrom: workDateFrom || undefined,
        workDateTo: workDateTo || undefined, attachmentState: attachmentState || undefined,
      },
    });
  } catch (err) {
    throw err;
  }
};

export const batchAttachGermanyOvertimePremiumComponentsToPayslips = async (items) => {
  try {
    return await api.post("/api/payroll/germany-overtime-premium-components/batch-attach", { items });
  } catch (err) {
    throw err;
  }
};

export const deleteEmployee = async (id) => {
  try {
    return await api.delete(`/api/payroll/employees/${id}`);
  } catch (err) {
    throw err;
  }
};

// UK Statutory Sick Pay / Statutory Family Pay calculator (ZP-TAX-UK-
// 2026-27-001 §11/§12 gap-closure Phase 5, 2026-09-09) — an on-demand
// preview, not a payslip mutation. `payload` shape matches the backend's
// UKStatutoryPayRequest: { employeeId, paymentType, eventStartDate,
// weekNumber?, qualifyingDaysInPeriod?, qualifyingDaysPerWeek?,
// averageWeeklyEarnings?, includeEmployerRecovery?, priorYearTotalClass1Nic? }.
export const calculateUkStatutoryPay = async (payload) => {
  return await api.post("/api/payroll/uk/statutory-pay/calculate", {
    employee_id: payload.employeeId,
    payment_type: payload.paymentType,
    event_start_date: payload.eventStartDate,
    week_number: payload.weekNumber ?? 1,
    qualifying_days_in_period: payload.qualifyingDaysInPeriod ?? null,
    qualifying_days_per_week: payload.qualifyingDaysPerWeek ?? null,
    average_weekly_earnings: payload.averageWeeklyEarnings ?? null,
    include_employer_recovery: payload.includeEmployerRecovery ?? false,
    prior_year_total_class1_nic: payload.priorYearTotalClass1Nic ?? null,
  });
};

// UK NI category relief-eligibility facts (Freeport/Investment Zone/
// veteran/apprentice, ZP-TAX-UK-2026-27-001 §8.2/§9.3 gap-closure Part 2,
// 2026-09-09) — feeds derive_ni_category() once _UK_DERIVE_NI_CATEGORY_
// ENABLED_COUNTRIES is on (enabled 2026-09-10). Same snake_case-request/
// camelCase-response split as the court-orders API above.
export const listUkNiReliefFacts = async (employeeId) => {
  return await api.get(`/api/payroll/uk/employees/${employeeId}/ni-relief-facts`);
};

export const createUkNiReliefFact = async (employeeId, payload) => {
  return await api.post(`/api/payroll/uk/employees/${employeeId}/ni-relief-facts`, {
    relief_type: payload.reliefType,
    reference: payload.reference || null,
    effective_from: payload.effectiveFrom,
    effective_to: payload.effectiveTo || null,
  });
};

export const deleteUkNiReliefFact = async (employeeId, factId) => {
  return await api.delete(`/api/payroll/uk/employees/${employeeId}/ni-relief-facts/${factId}`);
};

// UK Court-Ordered Deductions (ZP-TAX-UK-2026-27-001 §17 gap-closure Part
// 8, 2026-09-09) — England & Wales Attachment of Earnings Orders, Scottish
// arrestments, Northern Ireland's own equivalent. The create/list/status
// endpoints take/return snake_case for the create payload (backend has no
// alias on UKCourtOrderCreate) but camelCase for the response
// (UKCourtOrderResponse) — matched exactly below, not assumed consistent.
export const listUkCourtOrders = async (employeeId, status) => {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return await api.get(`/api/payroll/uk/employees/${employeeId}/court-orders${query}`);
};

export const createUkCourtOrder = async (employeeId, payload) => {
  return await api.post(`/api/payroll/uk/employees/${employeeId}/court-orders`, {
    jurisdiction: payload.jurisdiction,
    order_type: payload.orderType,
    start_date: payload.startDate,
    court_reference: payload.courtReference || null,
    issue_date: payload.issueDate || null,
    end_date: payload.endDate || null,
    priority: payload.priority !== "" && payload.priority !== undefined ? Number(payload.priority) : null,
    fixed_deduction_rate_pct: payload.fixedDeductionRatePct || null,
    fixed_deduction_amount: payload.fixedDeductionAmount || null,
    protected_earnings_amount: payload.protectedEarningsAmount || null,
    total_amount_to_collect: payload.totalAmountToCollect || null,
  });
};

export const setUkCourtOrderStatus = async (employeeId, orderId, status) => {
  return await api.put(`/api/payroll/uk/employees/${employeeId}/court-orders/${orderId}/status`, { status });
};

export const calculateUkCourtOrderDeductions = async (payload) => {
  return await api.post("/api/payroll/uk/court-orders/calculate", {
    employee_id: payload.employeeId,
    attachable_earnings: payload.attachableEarnings,
    pay_frequency: payload.payFrequency,
    as_of: payload.asOf || null,
  });
};

// UK Employer Annual Charges — Employment Allowance + Class 1A/1B
// (ZP-TAX-UK-2026-27-001 §9.3/§14 gap-closure Phase 6, 2026-09-09).
// Whole-tax-year, run-independent employer liabilities — see the
// matching backend endpoints under /api/payroll/uk/employer-charges/.
export const getUkEmployerChargesSummary = async () => {
  return await api.get("/api/payroll/uk/employer-charges/summary");
};

export const calculateUkEmploymentAllowance = async (employerHasClaimed) => {
  return await api.post("/api/payroll/uk/employer-charges/employment-allowance", {
    employer_has_claimed: employerHasClaimed,
  });
};

export const calculateUkClass1A1BCharge = async (chargeType, amount) => {
  return await api.post("/api/payroll/uk/employer-charges/class-1a-1b", {
    charge_type: chargeType,
    amount,
  });
};

export const bulkCreateEmployees = async (employees) => {
  try {
    // Expected response shape: { created: [...employees], failed: [{ row, reason }] }
    return await api.post("/api/payroll/employees/bulk", { employees });
  } catch (err) {
    throw err;
  }
};

export const bulkDeleteEmployees = async (employeeIds) => {
  try {
    return await api.post("/api/payroll/employees/bulk-delete", { employee_ids: employeeIds });
  } catch (err) {
    throw err;
  }
};

export const bulkUpdateEmployees = async (employees) => {
  try {
    // Expected response shape: { employees: [...updated], failed: [{ row, reason }] }
    return await api.post("/api/payroll/employees/bulk-update", { employees });
  } catch (err) {
    throw err;
  }
};

export const EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Intern"];
export const EMPLOYEE_STATUSES = ["Active", "On Leave", "Inactive"];
export const DEPARTMENTS = [
  "Engineering",
  "Sales",
  "Marketing",
  "Finance",
  "Human Resources",
  "Operations",
  "Support",
];

// ── Payroll Runs ───────────────────────────────────────
export const fetchRuns = async (params) => {
  try {
    const res = await api.get("/api/payroll/runs", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const getRunById = async (id) => {
  try {
    return await api.get(`/api/payroll/runs/${id}`);
  } catch (err) {
    throw err;
  }
};

export const getRunItems = async (id) => {
  try {
    const res = await api.get(`/api/payroll/runs/${id}/items`);
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const getRunLeaveSummary = async (id) => {
  try {
    return await api.get(`/api/payroll/runs/${id}/leave-summary`);
  } catch {
    return {};
  }
};

export const getBankTransferSummary = async (runId) => {
  try {
    return await api.get(`/api/payroll/runs/${runId}/bank-transfer-summary`);
  } catch (err) {
    throw err;
  }
};

export const downloadBankTransferFile = async (runId, format) => {
  const token = getAccessToken();
  const requestUrl = `${API_BASE_URL}/api/payroll/runs/${runId}/bank-transfer-file${format ? `?format=${format}` : ""}`;
  const res = await fetch(requestUrl, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to generate bank transfer file");
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `bank-transfer_${runId}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
  return { filename, size: blob.size };
};

export const createRun = async (payload) => {
  try {
    return await api.post("/api/payroll/runs", payload);
  } catch (err) {
    throw err;
  }
};

export const approveRun = async (id) => {
  try {
    return await api.put(`/api/payroll/runs/${id}/approve`);
  } catch (err) {
    throw err;
  }
};

export const recalculateEmployeePayslip = async (runId, employeeId) => {
  try {
    return await api.put(`/api/payroll/runs/${runId}/employees/${employeeId}/recalculate`);
  } catch (err) {
    throw err;
  }
};

export const updateRun = async (id, payload) => {
  try {
    return await api.put(`/api/payroll/runs/${id}`, payload);
  } catch (err) {
    throw err;
  }
};

export const deletePayRun = async (id) => {
  try {
    return await api.delete(`/api/payroll/runs/${id}`);
  } catch (err) {
    throw err;
  }
};

export const previewPayrollRun = async (employeeIds, country = "IN", periodStart = undefined, periodEnd = undefined, calculationMode = undefined) => {
  try {
    return await api.post("/api/payroll/runs/preview", {
      employeeIds,
      country,
      // Without these, the backend has no pay period to look up attendance
      // records against, so rewards/bonus/other compensation entered on the
      // Attendance screen silently get excluded from the preview totals —
      // even though the actual generated payslip includes them. Sending
      // them here keeps preview and generation in sync.
      ...(periodStart ? { periodStart } : {}),
      ...(periodEnd ? { periodEnd } : {}),
      ...(calculationMode ? { calculationMode } : {}),
    });
  } catch (err) {
    throw err;
  }
};

// ── Company Holidays ─────────────────────────────────────
// Shared calendar backing LOP proration in the payroll engine. Intended to
// also replace whatever separate holiday sources the Attendance/Leave pages
// currently use, so all three agree on the same list.
export const getPayrollHolidays = async (year) => {
  try {
    return await api.get("/api/payroll/holidays", { params: year ? { year } : {} });
  } catch (err) {
    throw err;
  }
};

export const upsertPayrollHolidays = async (holidays) => {
  // holidays: [{ date: "2026-01-26", name: "Republic Day" }, ...]
  return await api.post("/api/payroll/holidays/bulk", { holidays });
};

export const deletePayrollHoliday = async (id) => {
  return await api.delete(`/api/payroll/holidays/${id}`);
};

// ── Payslips ───────────────────────────────────────────
export const getPayslips = async (params) => {
  try {
    const res = await api.get("/api/payroll/payslips", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const getPayslipById = async (id) => {
  try {
    return await api.get(`/api/payroll/payslips/${id}`);
  } catch (err) {
    throw err;
  }
};

export const downloadPayslip = async (payslip) => {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE_URL}/api/payroll/payslips/${payslip.id}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to download payslip");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `payslip-${payslip.id || "download"}.pdf`;
  a.click();
  URL.revokeObjectURL(url);
};

export const downloadRunPayslips = async (runId) => {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE_URL}/api/payroll/runs/${runId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to download payslips");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `payslips_run_${runId}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
};

export const deletePayslip = async (id) => {
  try {
    return await api.delete(`/api/payroll/payslips/${id}`);
  } catch (err) {
    throw err;
  }
};

// ── Jurisdiction Compliance Pack (identity/metadata) ────
export const fetchJurisdictionPack = async (country, state) => {
  try {
    const res = await api.get("/api/payroll/compliance/jurisdiction-packs", {
      params: { country, state: state || undefined },
    });
    const packs = Array.isArray(res) ? res : res?.data || res?.items || [];
    return packs.length > 0 ? packs[0] : null;
  } catch {
    return null;
  }
};

export const upsertJurisdictionPack = async (payload) => {
  try {
    return await api.put("/api/payroll/compliance/jurisdiction-packs", payload);
  } catch (err) {
    throw err;
  }
};

// ── Compliance / Filings ───────────────────────────────
//
// fetchContributionRates / fetchTaxSlabs return exactly what the backend
// has — including an empty array when nothing is configured yet — and
// REJECT on a real fetch failure. Every current caller (ContributionRatesTable,
// TaxSlabTable, TaxConfigurationTab) already has its own loading/error/
// empty-state handling built for this; previously this function intercepted
// both cases and silently substituted the hardcoded RATES_BY_COUNTRY/
// SLABS_BY_COUNTRY tables instead, so an org with real rate-fetch failures
// (or a genuinely unconfigured jurisdiction) still saw a "Live from payroll
// engine" badge over fabricated numbers, with no way to tell the difference.
// RATES_BY_COUNTRY/SLABS_BY_COUNTRY themselves are NOT removed — they're
// still the correct, honestly-labeled source for getPolicyBasedExtraction's
// "policy-based preview" (ComplianceDocuments.jsx explicitly flags that
// path as a fallback to the reader); only this silent, unlabeled use of
// them as a stand-in for live configuration is removed.

export const fetchComplianceData = async (params) => {
  try {
    return await api.get("/api/payroll/filings", { params });
  } catch {
    return { company: null, filings: [] };
  }
};

export const fetchContributionRates = async (countryCode = DEFAULT_COUNTRY) => {
  const res = await api.get("/api/payroll/compliance/contribution-rates", {
    params: { country: countryCode },
  });
  return Array.isArray(res) ? res : res?.data || res?.items || [];
};

export const fetchTaxSlabs = async (countryCode = DEFAULT_COUNTRY) => {
  const res = await api.get("/api/payroll/compliance/tax-slabs", {
    params: { country: countryCode },
  });
  return Array.isArray(res) ? res : res?.data || res?.items || [];
};

// A state/province's own canonical MARGINAL_RATE brackets (US state tax,
// CA provincial/territorial tax) — deliberately a SEPARATE fetch from
// fetchTaxSlabs above, which excludes every state-scoped row by design
// (2026-09-11 fix, keeps them out of federal bracket calculation). Returns
// [] (not an error) when state is falsy, matching the backend's own
// falsy-state short-circuit.
export const fetchStateTaxSlabs = async (countryCode = DEFAULT_COUNTRY, state) => {
  if (!state) return [];
  const res = await api.get("/api/payroll/compliance/tax-slabs/state", {
    params: { country: countryCode, state },
  });
  return Array.isArray(res) ? res : res?.data || res?.items || [];
};

// Real local-tax rates for THIS org's own employees' work_locality codes
// (US City/County/Local Payroll Tax in TaxConfigurationTab.jsx) — resolves
// through the same Active-dataset lookup payroll calculation itself uses,
// so what's shown here is exactly what an employee's paycheck applies.
export const fetchOrgLocalityRates = async (countryCode = DEFAULT_COUNTRY) => {
  const res = await api.get("/api/payroll/compliance/locality-rates", {
    params: { country: countryCode },
  });
  return Array.isArray(res) ? res : res?.data || res?.items || [];
};

export const updateCompanyDetails = async (payload) => {
  try {
    return await api.put("/api/payroll/compliance/company-details", payload);
  } catch (err) {
    throw err;
  }
};

// ── Compliance Documents (upload → extraction) ─────────
//
// This endpoint doesn't exist on the backend yet. Contract it should
// follow, so the frontend (ComplianceDocumentUpload.jsx) already works
// once it's built — no component changes needed, just implement this:
//
// POST /api/payroll/compliance/documents   (multipart/form-data)
//   fields: file, country  (ISO-ish code, e.g. "IN" / "US" / "UK")
//   response 201:
//   {
//     id: string,
//     fileName: string,
//     uploadedAt: string (ISO timestamp),
//     country: string,
//     status: "processing" | "parsed" | "failed",
//     extracted: {
//       contributionRates: [{ id, label, employee, employer, total }] | null,
//       taxSlabs: [{ id, min, max, rate, tax }] | null,
//       requirements: [{ label, note }] | null
//     } | null,
//     error: string | null
//   }
//
// GET /api/payroll/compliance/documents?country=XX
//   response 200: array of the same document shape as above
//
// DELETE /api/payroll/compliance/documents/:id
//   response 204
//
// Until this exists, uploadComplianceDocument() rejects and the UI marks
// the file "unavailable" (queued, not lost) rather than failing silently.

export const uploadComplianceDocument = async (file, countryCode = DEFAULT_COUNTRY) => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("country", countryCode);
  try {
    return await api.post("/api/payroll/compliance/documents", formData);
  } catch (err) {
    throw err;
  }
};

export const fetchComplianceDocuments = async (countryCode = DEFAULT_COUNTRY) => {
  try {
    const res = await api.get("/api/payroll/compliance/documents", { params: { country: countryCode } });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const deleteComplianceDocument = async (id) => {
  try {
    return await api.delete(`/api/payroll/compliance/documents/${id}`);
  } catch (err) {
    throw err;
  }
};

// Promote a single extracted rate/slab row (from an uploaded document) into
// the org's active configuration. NOTE: there is no backend endpoint for
// this yet — /api/payroll/compliance/apply-extracted-rate does not exist
// in router.py today. This is wired on the frontend ahead of the backend
// intentionally, so the UI action exists and is ready the moment the
// corresponding endpoint is built. Until then this will reject, and the
// caller (ComplianceDocumentUpload) shows that as a toast rather than
// silently pretending it worked.
export const applyExtractedRate = async ({ documentId, kind, row, countryCode = DEFAULT_COUNTRY }) => {
  return api.post(`/api/payroll/compliance/apply-extracted-rate`, {
    documentId,
    kind, // "contributionRate" | "taxSlab"
    row,
    countryCode,
  });
};

// ──────────────────────────────────────────────
// Attendance & Compensation (Rewards, Bonus, etc.)
// ──────────────────────────────────────────────

// Fetch all payroll employees as a roster scaffold with default attendance fields.
// WARNING: This does NOT return saved attendance data — it only provides the employee
// list with hardcoded defaults (status: "present", default times, today's date).
// For real saved records, use getAttendanceRecords() or getAttendanceHistory().
export const getEmployeeRoster = async (params = {}) => {
  try {
    const employees = await api.get("/api/payroll/employees/roster", { params });
    const records = Array.isArray(employees) ? employees : [];
    // Add default attendance + compensation fields
    return records.map((emp) => ({
      employeeId: emp.id,
      name: emp.name,
      department: emp.department,
      designation: emp.designation,
      date: new Date().toISOString().split("T")[0],
      checkIn: "09:00",
      checkOut: "18:00",
      checkInPeriod: "AM",
      checkOutPeriod: "PM",
      breakMinutes: 60,
      status: "present",
      hours: "",
      rewards: 0,
      bonus: 0,
      otherCompensation: 0,
      notes: "",
    }));
  } catch {
    return [];
  }
};

// Backward-compatible alias (prefer getEmployeeRoster in new code)
export const getAttendanceBase = getEmployeeRoster;

// Save attendance + compensation records for a pay period
export const saveAttendanceRecords = async (records) => {
  try {
    return await api.post("/api/payroll/attendance/bulk", { records });
  } catch (err) {
    throw err;
  }
};

// Saves attendance in batches so a large range (employees × days) never hits
// the proxy's request-size limit or timeout in a single request. Results are
// aggregated into the same { saved, skipped, skippedDetails, records } shape
// as one call. On failure the thrown error carries `savedCount` (rows the
// server already confirmed in earlier batches) so callers can report partial
// progress honestly.
export const ATTENDANCE_SAVE_BATCH_SIZE = 500;

export const saveAttendanceRecordsInBatches = async (records, { batchSize = ATTENDANCE_SAVE_BATCH_SIZE, onProgress } = {}) => {
  const total = records.length;
  const result = { saved: 0, skipped: 0, skippedDetails: [], records: [] };
  for (let i = 0; i < total; i += batchSize) {
    const batch = records.slice(i, i + batchSize);
    let res;
    try {
      res = await saveAttendanceRecords(batch);
    } catch (err) {
      err.savedCount = result.saved;
      err.totalCount = total;
      throw err;
    }
    result.saved += res?.saved ?? 0;
    result.skipped += res?.skipped ?? 0;
    if (Array.isArray(res?.skippedDetails)) result.skippedDetails.push(...res.skippedDetails);
    if (Array.isArray(res?.records)) result.records.push(...res.records);
    onProgress?.(Math.min(i + batch.length, total), total);
  }
  return result;
};

// Human-readable reason for a failed attendance save — the server's own
// message when it sent one, otherwise a plain explanation of the HTTP status.
export const describeAttendanceSaveError = (err) => {
  const status = err?.status;
  if (status === 413) return "The upload is too large for the server to accept (HTTP 413). Try a smaller date range.";
  if (status === 504 || status === 502) return `The server took too long to respond (HTTP ${status}). Try a smaller date range.`;
  if (status === 403) return err?.message || "You don't have permission to save attendance (HTTP 403).";
  if (status === 0 || err?.name === "TypeError") return "Could not reach the server. Check your connection and try again.";
  return err?.message || "The server rejected the save.";
};

// Per-employee attendance coverage for a pay period — what the payroll run
// gate checks. employeeIds omitted = every Active employee.
export const getAttendanceReadiness = async (periodStart, periodEnd, employeeIds) => {
  return await api.post("/api/payroll/attendance/readiness", {
    periodStart,
    periodEnd,
    ...(employeeIds ? { employeeIds } : {}),
  });
};

// Clear attendance records from the backend (optionally scoped to a date range)
export const clearAttendanceRecords = async (startDate, endDate) => {
  try {
    const params = {};
    if (startDate) params.startDate = startDate;
    if (endDate) params.endDate = endDate;
    return await api.delete("/api/payroll/attendance", { params });
  } catch (err) {
    throw err;
  }
};

// Fetch saved attendance records (with compensation data)
export const getAttendanceRecords = async (params = {}) => {
  try {
    const res = await api.get("/api/payroll/attendance", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

// Paged attendance fetch. Hits /attendance/page, which returns an exact total
// plus a server-computed hasMore — the plain list endpoint cannot express
// either, which is why a client paging it has to keep re-fetching blindly.
export const getAttendanceRecordsPaginated = async (params = {}, limit = 100, offset = 0) => {
  try {
    const res = await api.get("/api/payroll/attendance/page", {
      params: { ...params, limit, offset },
    });
    const items = Array.isArray(res) ? res : res?.data || res?.items || [];
    return {
      items: Array.isArray(items) ? items : [],
      total: Number(res?.total ?? items?.length ?? 0) || 0,
      limit: Number(res?.limit ?? limit) || limit,
      offset: Number(res?.offset ?? offset) || 0,
      hasMore: Boolean(res?.hasMore),
      // Span of the whole filtered set, not of this page. The History tab
      // derives its working-days count from these, so dropping them made the
      // span read zero no matter what range was selected.
      firstDate: res?.firstDate ?? null,
      lastDate: res?.lastDate ?? null,
    };
  } catch {
    // A failed page must not look like "the end of the data", or the UI will
    // silently stop loading. Report it as an error and let the caller decide.
    return { items: [], total: 0, limit, offset, hasMore: false, firstDate: null, lastDate: null, error: true };
  }
};

// Per-employee attendance aggregates for a range, paged server-side. The
// Summary tab used to download every attendance row in range and count days
// in the browser; this does the counting in the database.
//
// `search` is forwarded so the server matches every employee in the
// organization, not only the ones on the page currently loaded in the browser.
// `totals` is the org-wide sum across the whole filtered set: the stat cards
// must not total just the loaded page, which under-reports as soon as there
// is a second page.
export const getAttendanceSummaryByEmployee = async (
  { startDate, endDate, search, limit = 100, offset = 0 } = {}
) => {
  try {
    const res = await api.get("/api/payroll/attendance/summary/by-employee", {
      params: { startDate, endDate, search, limit, offset },
    });
    const items = Array.isArray(res) ? res : res?.data || res?.items || [];
    return {
      items: Array.isArray(items) ? items : [],
      total: Number(res?.total ?? items?.length ?? 0) || 0,
      limit: Number(res?.limit ?? limit) || limit,
      offset: Number(res?.offset ?? offset) || 0,
      hasMore: Boolean(res?.hasMore),
      totals: res?.totals ?? null,
    };
  } catch {
    return { items: [], total: 0, limit, offset, hasMore: false, totals: null, error: true };
  }
};

export const getAttendanceSummary = async () => {
  try {
    const res = await api.get("/api/payroll/attendance/summary");
    return res?.data || res || {};
  } catch {
    return {};
  }
};

// Fetch attendance history for a date range
export const getAttendanceHistory = async (startDate, endDate) => {
  try {
    const res = await api.get("/api/payroll/attendance", {
      params: { startDate, endDate },
    });
    const records = Array.isArray(res) ? res : res?.data || res?.items || [];
    return Array.isArray(records) ? records : [];
  } catch {
    return [];
  }
};

// Combines employee list with attendance + compensation data
export const getEmployeesWithAttendance = async (params = {}) => {
  try {
    const [employees, attendance] = await Promise.all([
      getEmployees(params),
      getAttendanceRecords(params),
    ]);
    const records = Array.isArray(attendance) ? attendance : [];

    const attendanceMap = {};
    const summaryMap = {};
    records.forEach((rec) => {
      const key = String(rec.employeeId || rec.id || "");
      if (!key) return;
      attendanceMap[key] = rec;
      if (!summaryMap[key]) summaryMap[key] = { present: 0, absent: 0, leave: 0, total: 0, totalHours: 0 };
      summaryMap[key].total++;
      if (rec.status === "present") summaryMap[key].present++;
      else if (rec.status === "absent") summaryMap[key].absent++;
      else if (rec.status === "leave") summaryMap[key].leave++;
      summaryMap[key].totalHours += parseFloat(rec.hours) || 0;
    });

    return (Array.isArray(employees) ? employees : []).map((emp) => {
      const key = String(emp.id || "");
      const att = attendanceMap[key] || null;
      const summary = summaryMap[key] || { present: 0, absent: 0, leave: 0, total: 0, totalHours: 0 };
      return {
        ...emp,
        attendance: att,
        attendanceStatus: att?.status || "unknown",
        attendanceSummary: summary,
        rewards: att?.rewards || 0,
        bonus: att?.bonus || 0,
        otherCompensation: att?.otherCompensation || 0,
      };
    });
  } catch {
    return [];
  }
};

export const getHolidays = async (params = {}) => {
  try {
    const res = await api.get("/api/payroll/holidays", { params });
    return Array.isArray(res) ? res : res?.data || res?.holidays || [];
  } catch {
    return [];
  }
};

export const getAttendanceSummaryForEmployees = async (employeeIds = []) => {
  try {
    const attendance = await getAttendanceRecords();
    const records = Array.isArray(attendance) ? attendance : [];
    const total = records.length || employeeIds.length;
    const present = records.filter((r) => r.status === "present").length;
    const absent = records.filter((r) => r.status === "absent").length;
    const leave = records.filter((r) => r.status === "leave").length;
    return { total, present, absent, leave, records };
  } catch {
    return { total: 0, present: 0, absent: 0, leave: 0, records: [] };
  }
};

// ──────────────────────────────────────────────
// Reports
// ──────────────────────────────────────────────

export const getPayrollReports = async (params = {}) => {
  try {
    const res = await api.get("/api/payroll/reports", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

// Leave Allocations (Paid / Unpaid)
export const saveLeaveRecords = async (records) => {
  try {
    return await api.post("/api/payroll/leaves/bulk", { records });
  } catch (err) {
    throw err;
  }
};

export const getLeaveRecords = async (params = {}) => {
  try {
    const res = await api.get("/api/payroll/leaves", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const resetLeaveAllocations = async () => {
  return await api.delete("/api/payroll/leaves/reset");
};

// ── Leave Requests (payroll's own leave request system) ──

export const getPayrollLeaveRequests = async (params = {}) => {
  try {
    const res = await api.get("/api/payroll/leave-requests", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const createPayrollLeaveRequest = async (payload) => {
  try {
    return await api.post("/api/payroll/leave-requests", payload);
  } catch (err) {
    throw err;
  }
};

export const reviewPayrollLeaveRequest = async (requestId, status) => {
  try {
    return await api.put(`/api/payroll/leave-requests/${requestId}/review`, { status });
  } catch (err) {
    throw err;
  }
};

export const downloadReport = async (id, format = "pdf") => {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE_URL}/api/payroll/reports/${id}/download?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to download report");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report-${id}.${format === "pdf" ? "pdf" : "csv"}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
};

// ── Payroll Policy Management ────────────────────────────
// Add this block to src/service/payrollService.js (append near the other
// section blocks — do not replace anything, this is purely additive).
// Uses the same `api` wrapper and try/throw convention as
// updateCompanyDetails() etc. elsewhere in this file.

export const getActivePolicy = async () => {
  try {
    return await api.get("/api/payroll/policy/active");
  } catch (err) {
    throw err;
  }
};

export const updatePolicy = async (policyId, payload) => {
  try {
    return await api.put(`/api/payroll/policy/${policyId}`, payload);
  } catch (err) {
    throw err;
  }
};

export const enablePolicyIntegration = async (policyId, category, providerKey) => {
  try {
    return await api.post(
      `/api/payroll/policy/${policyId}/integrations/${category}/${providerKey}/enable`,
      {}
    );
  } catch (err) {
    throw err;
  }
};

export const disablePolicyIntegration = async (policyId, category, providerKey) => {
  try {
    return await api.post(
      `/api/payroll/policy/${policyId}/integrations/${category}/${providerKey}/disable`,
      {}
    );
  } catch (err) {
    throw err;
  }
};

// ── Enterprise Policy Onboarding ─────────────────────────────────────
// Financial-year ranges are each country's real fiscal year, not a placeholder.
export const ENTERPRISE_JURISDICTIONS = [
  { code: "IN", name: "India", flag: "🇮🇳", currency: "INR", financialYear: "Apr 1 – Mar 31" },
  { code: "US", name: "United States", flag: "🇺🇸", currency: "USD", financialYear: "Jan 1 – Dec 31" },
  { code: "UK", name: "United Kingdom", flag: "🇬🇧", currency: "GBP", financialYear: "Apr 6 – Apr 5" },
  { code: "AU", name: "Australia", flag: "🇦🇺", currency: "AUD", financialYear: "Jul 1 – Jun 30" },
  { code: "DE", name: "Germany", flag: "🇩🇪", currency: "EUR", financialYear: "Jan 1 – Dec 31" },
  { code: "CA", name: "Canada", flag: "🇨🇦", currency: "CAD", financialYear: "Jan 1 – Dec 31" },
{ code: "FR", name: "France", flag: "FR", currency: "EUR", financialYear: "Jan 1 - Dec 31" },
];

export const ENTERPRISE_STATUS_LABELS = {
  not_configured: "Not Configured",
  in_progress: "In Progress",
  configured: "Configured",
  active: "Active",
};

export const getEnterpriseJurisdictions = async () => {
  try {
    const res = await api.get("/api/payroll/enterprise/jurisdictions");
    return Array.isArray(res) ? res : res?.data || [];
  } catch {
    return [];
  }
};

export const addEnterpriseJurisdiction = async (countryCode) => {
  try {
    return await api.post("/api/payroll/enterprise/jurisdictions", { countryCode });
  } catch (err) {
    throw err;
  }
};

export const updateEnterpriseJurisdiction = async (jurisdictionId, payload) => {
  try {
    return await api.put(`/api/payroll/enterprise/jurisdictions/${jurisdictionId}`, payload);
  } catch (err) {
    throw err;
  }
};

export const verifyEnterpriseJurisdiction = async (jurisdictionId) => {
  try {
    return await api.post(`/api/payroll/enterprise/jurisdictions/${jurisdictionId}/verify`, {});
  } catch (err) {
    throw err;
  }
};

export const removeEnterpriseJurisdiction = async (jurisdictionId) => {
  try {
    return await api.delete(`/api/payroll/enterprise/jurisdictions/${jurisdictionId}`);
  } catch (err) {
    throw err;
  }
};

export const getEnterpriseContributionRates = async (jurisdictionId) => {
  try {
    const res = await api.get(`/api/payroll/enterprise/jurisdictions/${jurisdictionId}/contribution-rates`);
    return Array.isArray(res) ? res : res?.data || [];
  } catch {
    return [];
  }
};

export const updateEnterpriseContributionRate = async (jurisdictionId, componentKey, payload) => {
  try {
    return await api.put(
      `/api/payroll/enterprise/jurisdictions/${jurisdictionId}/contribution-rates/${componentKey}`,
      payload
    );
  } catch (err) {
    throw err;
  }
};

export const getEnterpriseValidation = async () => {
  try {
    return await api.get("/api/payroll/enterprise/validation");
  } catch {
    return { canActivate: false, blockingReasons: ["Could not check activation readiness."], configuredJurisdictions: [] };
  }
};

export const activateEnterprise = async () => {
  try {
    return await api.post("/api/payroll/enterprise/activate", {});
  } catch (err) {
    throw err;
  }
};

export const deactivateEnterprise = async () => {
  try {
    return await api.post("/api/payroll/enterprise/deactivate", {});
  } catch (err) {
    throw err;
  }
};

export const getEnterpriseDashboard = async () => {
  try {
    return await api.get("/api/payroll/enterprise/dashboard");
  } catch {
    return { configuredCount: 0, pendingCount: 0, activeCountries: [], completionPct: 0, upcomingFilings: [], recentChanges: [] };
  }
};

// Internal provider keys -> what Payroll Policy Management shows the user.
// Never render category/provider_key strings directly in the UI — always
// go through these maps, per the spec's "do not expose internal
// implementation names" requirement.
export const CALCULATION_MODE_LABELS = {
  simple: "Simple Payroll",
  standard: "Standard Payroll",
  enterprise: "Enterprise Payroll",
};

// Mirrors backend/app/modules/payroll/engine/standard.py's per-country
// employee-side contribution fields (_calc_india/_calc_us/_calc_uk/
// _calc_australia/_calc_germany/_calc_canada). Two field names per entry
// because the same logical amount comes back under different keys
// depending on the endpoint: `previewField` on the payroll-run preview
// response (monthlyPf, monthlySocialSecurity, …) and `payslipField` on a
// persisted PayslipItemResponse (pf, socialSecurity, …). Single source of
// truth for both, instead of assuming India's PF/ESI/PT for every country.
const CONTRIBUTION_COLUMNS_BY_COUNTRY = {
  IN: [
    { id: "pf", label: "PF", previewField: "monthlyPf", payslipField: "pf" },
    { id: "esi", label: "ESI", previewField: "monthlyEsi", payslipField: "esi" },
    { id: "pt", label: "PT", previewField: "monthlyPt", payslipField: "professionalTax" },
  ],
  US: [
    { id: "ss", label: "Social Security", previewField: "monthlySocialSecurity", payslipField: "socialSecurity" },
    { id: "medicare", label: "Medicare", previewField: "monthlyMedicare", payslipField: "medicare" },
  ],
  UK: [
    { id: "ni", label: "National Insurance", previewField: "monthlyNi", payslipField: "niEmployee" },
    // Was silently missing — an employee Workplace Pension % now genuinely
    // deducts money (see uk.py's employee_pension), but with no column
    // here it only showed up as an unexplained drop in Net Pay on the
    // "what you approve is exactly what gets persisted" review screen.
    { id: "workplace-pension", label: "Workplace Pension", previewField: "monthlyEmployeePension", payslipField: "employeePension" },
    // Same "silently missing" gap as Workplace Pension above — Student/
    // Postgraduate Loan genuinely reduces Net Pay but had no column here.
    { id: "student-loan", label: "Student Loan Deduction", previewField: "monthlyStudyLoanDeduction", payslipField: "studyLoanDeduction" },
    // Same gap, found 2026-09-09 gap-closure Phase 3 — a concurrent
    // Postgraduate Loan also reduces Net Pay and had no column here.
    { id: "postgrad-loan", label: "Postgraduate Loan Deduction", previewField: "monthlyPostgradLoanDeduction", payslipField: "postgradLoanDeduction" },
  ],
  AU: [
    { id: "medicare-levy", label: "Medicare Levy", previewField: "monthlyMedicare", payslipField: "medicare" },
  ],
  DE: [
    { id: "pension", label: "Pension", previewField: "monthlyPf", payslipField: "pf" },
    { id: "social", label: "Social Insurance", previewField: "monthlyEsi", payslipField: "esi" },
  ],
  CA: [
    { id: "cpp", label: "CPP", previewField: "monthlySocialSecurity", payslipField: "socialSecurity" },
    { id: "ei", label: "EI", previewField: "monthlyEsi", payslipField: "esi" },
  ],
};

export function getContributionColumns(country) {
  // Deliberately NOT normalizeCountryCode() here — that helper maps
  // "uk" -> "GB" for currency/country-name purposes, but this map's own
  // key is "UK" (matching jurisdiction_country's stored value and
  // getPayrollLabels' identical plain-uppercase approach below). Running
  // "UK" through normalizeCountryCode silently returned "GB", missed
  // every key in CONTRIBUTION_COLUMNS_BY_COUNTRY, and dropped the
  // National Insurance column entirely for every UK org.
  const code = (country || "IN").toUpperCase();
  return CONTRIBUTION_COLUMNS_BY_COUNTRY[code] || [];
}

export const INTEGRATION_LABELS = {
  // attendance
  zoiko_time: "Zoiko Time",
  manual_attendance: "Manual Attendance",
  csv_import: "CSV Import",
  biometric: "Biometric",
  // banking
  manual_transfer: "Manual Bank Transfer",
  excel_export: "Excel Bank Export",
  csv_export: "CSV Bank Export",
  bank_api: "Bank API",
  // notifications
  email: "Email",
  sms: "SMS",
  whatsapp: "WhatsApp",
  slack: "Slack",
  teams: "Microsoft Teams",
};

export const EMPLOYEE_CATEGORY_LABELS = {
  full_time: "Full Time",
  part_time: "Part Time",
  intern: "Intern",
  contract: "Contract",
  consultant: "Consultant",
  freelancer: "Freelancer",
};

// ── Payroll Mail (SMTP send identity) ───────────────────────────────────

export const getEmailSettings = async () => {
  try {
    return await api.get("/api/payroll/mail/settings");
  } catch (err) {
    throw err;
  }
};

export const updateEmailSettings = async (payload) => {
  try {
    return await api.put("/api/payroll/mail/settings", payload);
  } catch (err) {
    throw err;
  }
};

// ── Send Template (custom fields, form templates, sending, review) ──────

export const getCustomFields = async () => {
  try {
    return await api.get("/api/payroll/employee-forms/custom-fields");
  } catch (err) {
    throw err;
  }
};

export const createCustomField = async (payload) => {
  try {
    return await api.post("/api/payroll/employee-forms/custom-fields", payload);
  } catch (err) {
    throw err;
  }
};

export const deleteCustomField = async (id) => {
  try {
    return await api.delete(`/api/payroll/employee-forms/custom-fields/${id}`);
  } catch (err) {
    throw err;
  }
};

export const getUpdateForms = async () => {
  try {
    return await api.get("/api/payroll/employee-forms/templates");
  } catch (err) {
    throw err;
  }
};

export const createUpdateForm = async (payload) => {
  try {
    return await api.post("/api/payroll/employee-forms/templates", payload);
  } catch (err) {
    throw err;
  }
};

export const sendUpdateForm = async (formId, employeeIds) => {
  try {
    return await api.post(`/api/payroll/employee-forms/templates/${formId}/send`, { employeeIds });
  } catch (err) {
    throw err;
  }
};

export const getFormSubmissions = async (status) => {
  try {
    return await api.get("/api/payroll/employee-forms/submissions", { params: status ? { status } : undefined });
  } catch (err) {
    throw err;
  }
};

export const approveFormSubmission = async (id, notes) => {
  try {
    return await api.post(`/api/payroll/employee-forms/submissions/${id}/approve`, { notes });
  } catch (err) {
    throw err;
  }
};

export const rejectFormSubmission = async (id, notes) => {
  try {
    return await api.post(`/api/payroll/employee-forms/submissions/${id}/reject`, { notes });
  } catch (err) {
    throw err;
  }
};

// Public, unauthenticated — reached via the emailed link, no token attached.
export const getPublicForm = async (token) => {
  try {
    return await api.get(`/api/public/employee-forms/${token}`, { auth: false });
  } catch (err) {
    throw err;
  }
};

export const submitPublicForm = async (token, values) => {
  try {
    return await api.post(`/api/public/employee-forms/${token}/submit`, { values }, { auth: false });
  } catch (err) {
    throw err;
  }
};

// ── Report Generation (template-driven) ──────────────────────────────
// Organization-side consumption of Super Admin-published Report Templates
// — the org only ever selects a jurisdiction/year/period/run/report and
// generates; it never authors template structure (that's superAdminService.js).

// Mirrors backend PAYROLL_STATUS_ORDER (models.py) — kept as its own local
// copy, same convention RunStatusTimeline.jsx already uses, rather than
// importing across files for a single constant.
export const PAYROLL_STATUS_ORDER = ["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"];

export const isRunFinalized = (run) => PAYROLL_STATUS_ORDER.indexOf(run?.status) >= PAYROLL_STATUS_ORDER.indexOf("Approved");

export const getAvailableReports = async (params = {}) => {
  // { reportingYear } -> [{ reportType, name }] — real, backend-owned list
  // of reports with a Published/Active template for this org's jurisdiction+year.
  try {
    const res = await api.get("/api/payroll/report-templates/available", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const getApplicableReportTemplate = async (params = {}) => {
  // { reportingYear, reportType, payrollRunId? } — returns { template, validation }.
  // validation is only populated when payrollRunId is passed.
  try {
    return await api.get("/api/payroll/report-templates/applicable", { params });
  } catch (err) {
    throw err;
  }
};

export const generateReport = async (payload) => {
  // { reportTemplateId, payrollRunId, reportingPeriod? }
  try {
    return await api.post("/api/payroll/generated-reports", payload);
  } catch (err) {
    throw err;
  }
};

export const getGeneratedReports = async (params = {}) => {
  try {
    const res = await api.get("/api/payroll/generated-reports", { params });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

export const getGeneratedReport = async (id) => {
  try {
    return await api.get(`/api/payroll/generated-reports/${id}`);
  } catch (err) {
    throw err;
  }
};

export const voidGeneratedReport = async (id, reason) => {
  try {
    return await api.post(`/api/payroll/generated-reports/${id}/void`, { reason });
  } catch (err) {
    throw err;
  }
};

// This org's upcoming Active statutory filing due dates — never
// hardcoded/guessed client-side, always whatever Super Admin has
// published for this org's jurisdiction.
export const getUpcomingFilingDates = async (limit = 10) => {
  try {
    const res = await api.get("/api/payroll/report-templates/filing-calendar", { params: { limit } });
    return Array.isArray(res) ? res : res?.data || res?.items || [];
  } catch {
    return [];
  }
};

// Single-employee certificate download (Form 130/P60-style PER_EMPLOYEE
// reports only) — same manual-fetch-blob-download pattern as downloadReport.
export const downloadReportCertificate = async (generatedReportId, employeeId, employeeName) => {
  const token = getAccessToken();
  const res = await fetch(
    `${API_BASE_URL}/api/payroll/generated-reports/${generatedReportId}/certificate/${employeeId}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) throw new Error("Failed to download certificate");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `certificate-${(employeeName || employeeId).toString().replace(/\s+/g, "_")}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
};

// All employees' certificates for a PER_EMPLOYEE generated report, as one ZIP.
export const downloadReportCertificatesZip = async (generatedReportId) => {
  const token = getAccessToken();
  const res = await fetch(
    `${API_BASE_URL}/api/payroll/generated-reports/${generatedReportId}/certificates.zip`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) throw new Error("Failed to download certificates");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `certificates-${generatedReportId}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
};

// ── India: Gratuity (ZP-TAX-IN-2026-27-001 §11, gap-closure Phase D) ─────
// calculate_india_employee_gratuity has always existed on the backend but
// had NO frontend anywhere — this is that missing call.
export const calculateIndiaGratuity = async (payload) => {
  return await api.post("/api/payroll/india/gratuity/calculate", {
    employee_id: payload.employeeId,
    eligibility_event: payload.eligibilityEvent,
    is_fixed_term: payload.isFixedTerm || false,
    date_of_leaving: payload.dateOfLeaving || null,
    last_drawn_monthly_wage: payload.lastDrawnMonthlyWage || null,
  });
};

// ── India: Form 122 salary TDS declaration (§6.2, gap-closure Phase E) ───
export const listIndiaSalaryTdsDeclarations = async (employeeId, taxYear) => {
  const params = new URLSearchParams();
  if (employeeId) params.set("employeeId", employeeId);
  if (taxYear) params.set("taxYear", taxYear);
  const query = params.toString() ? `?${params.toString()}` : "";
  return await api.get(`/api/payroll/india/salary-tds-declarations${query}`);
};

export const createIndiaSalaryTdsDeclaration = async (payload) => {
  return await api.post("/api/payroll/india/salary-tds-declarations", {
    employee_id: payload.employeeId,
    tax_year: payload.taxYear,
    prior_employer_salary: payload.priorEmployerSalary || 0,
    prior_employer_tds_deducted: payload.priorEmployerTdsDeducted || 0,
    other_income: payload.otherIncome || 0,
    house_property_loss: payload.housePropertyLoss || 0,
  });
};

export const submitIndiaSalaryTdsDeclaration = async (id) => {
  return await api.put(`/api/payroll/india/salary-tds-declarations/${id}/submit`);
};

export const approveIndiaSalaryTdsDeclaration = async (id) => {
  return await api.put(`/api/payroll/india/salary-tds-declarations/${id}/approve`);
};

// ── India: Form 124 salary TDS claims (§6.2, gap-closure Phase E) ────────
export const listIndiaSalaryTdsClaims = async (employeeId, taxYear) => {
  const params = new URLSearchParams();
  if (employeeId) params.set("employeeId", employeeId);
  if (taxYear) params.set("taxYear", taxYear);
  const query = params.toString() ? `?${params.toString()}` : "";
  return await api.get(`/api/payroll/india/salary-tds-claims${query}`);
};

export const createIndiaSalaryTdsClaim = async (payload) => {
  return await api.post("/api/payroll/india/salary-tds-claims", {
    employee_id: payload.employeeId,
    tax_year: payload.taxYear,
    claim_type: payload.claimType,
    claimed_amount: payload.claimedAmount,
    evidence_reference: payload.evidenceReference || null,
  });
};

export const submitIndiaSalaryTdsClaim = async (id) => {
  return await api.put(`/api/payroll/india/salary-tds-claims/${id}/submit`);
};

export const approveIndiaSalaryTdsClaim = async (id) => {
  return await api.put(`/api/payroll/india/salary-tds-claims/${id}/approve`);
};

export const rejectIndiaSalaryTdsClaim = async (id, reason) => {
  return await api.put(`/api/payroll/india/salary-tds-claims/${id}/reject`, { reason });
};

// ── India: Form 123 employee benefit valuation (§6.2/§7, gap-closure ─────
// Phase E) — Zoiko does NOT compute perquisite valuation formulas (the
// statutory pack gives none); the org enters its own already-determined
// taxable value here.
export const listIndiaEmployeeBenefitValuations = async (employeeId, taxYear) => {
  const params = new URLSearchParams();
  if (employeeId) params.set("employeeId", employeeId);
  if (taxYear) params.set("taxYear", taxYear);
  const query = params.toString() ? `?${params.toString()}` : "";
  return await api.get(`/api/payroll/india/employee-benefit-valuations${query}`);
};

export const createIndiaEmployeeBenefitValuation = async (payload) => {
  return await api.post("/api/payroll/india/employee-benefit-valuations", {
    employee_id: payload.employeeId,
    tax_year: payload.taxYear,
    benefit_type: payload.benefitType,
    taxable_value: payload.taxableValue,
    description: payload.description || null,
  });
};

export const issueIndiaEmployeeBenefitValuation = async (id) => {
  return await api.put(`/api/payroll/india/employee-benefit-valuations/${id}/issue`);
};

// ── India: Form 130/138/123 generation (gap-closure Phase E) — these are
// NOT run-scoped like the generic generateReport() above, so they use
// their own dedicated endpoints, same as UK's P45/P60/EPS.
export const generateIndiaForm130 = async (payload) => {
  return await api.post("/api/payroll/india/reports/form130", {
    report_template_id: payload.reportTemplateId,
    employee_id: payload.employeeId,
    as_of_date: payload.asOfDate,
  });
};

export const generateIndiaForm138 = async (payload) => {
  return await api.post("/api/payroll/india/reports/form138", {
    report_template_id: payload.reportTemplateId,
    reporting_year: payload.reportingYear,
    period_key: payload.periodKey,
  });
};

export const generateIndiaForm123 = async (payload) => {
  return await api.post("/api/payroll/india/reports/form123", {
    report_template_id: payload.reportTemplateId,
    employee_id: payload.employeeId,
    tax_year: payload.taxYear,
  });
};

// ── US: Form W-2 (Production-Readiness Plan Phase 5) ───────────────────
// Same shape as India's Form 123 above (report_template_id/employee_id/
// tax_year) — a calendar-year "2026", not India's fiscal-year "2026-27".
export const generateUsW2 = async (payload) => {
  return await api.post("/api/payroll/us/reports/w2", {
    report_template_id: payload.reportTemplateId,
    employee_id: payload.employeeId,
    tax_year: payload.taxYear,
  });
};

// ── US: Form 941/940 (Production-Readiness Plan Phase 5) ───────────────
// Aggregate, employer-level — no employeeId, same footing as CA's PD7A.
export const generateUs941 = async (payload) => {
  return await api.post("/api/payroll/us/reports/941", {
    report_template_id: payload.reportTemplateId,
    year: payload.year,
    quarter: payload.quarter,
  });
};

export const generateUs940 = async (payload) => {
  return await api.post("/api/payroll/us/reports/940", {
    report_template_id: payload.reportTemplateId,
    year: payload.year,
  });
};

// ── US: New Hire Reporting (Production-Readiness Plan Phase 5) ─────────
// Compliance tracking (due-date + mark-filed), not report generation —
// a Pending row is auto-created for every new US employee server-side.
export const getUsNewHireReports = async (status) => {
  return await api.get("/api/payroll/us/new-hire-reports", { params: status ? { status } : {} });
};

export const createUsNewHireReport = async (payload) => {
  return await api.post("/api/payroll/us/new-hire-reports", {
    employeeId: payload.employeeId,
    hireDate: payload.hireDate || null,
    workState: payload.workState || null,
    dueDateDays: payload.dueDateDays || null,
  });
};

export const markUsNewHireReportFiled = async (reportId, payload = {}) => {
  return await api.post(`/api/payroll/us/new-hire-reports/${reportId}/mark-filed`, {
    filedDate: payload.filedDate || null,
    notes: payload.notes || null,
  });
};

// ── Canada: T4/RL-1/ROE (per-employee) + PD7A (per-period) generation ──
// (ZP-TAX-CA-2026-001, forms/reports gap-closure). T4/RL-1/ROE share the
// same shape as India's Form 130 above (report_template_id/employee_id/
// as_of_date) — same widened backend endpoint family, just Canada's own
// paths.
export const generateCaT4 = async (payload) => {
  return await api.post("/api/payroll/canada/reports/t4", {
    report_template_id: payload.reportTemplateId,
    employee_id: payload.employeeId,
    as_of_date: payload.asOfDate,
  });
};

export const generateCaRl1 = async (payload) => {
  return await api.post("/api/payroll/canada/reports/rl1", {
    report_template_id: payload.reportTemplateId,
    employee_id: payload.employeeId,
    as_of_date: payload.asOfDate,
  });
};

export const generateCaRoe = async (payload) => {
  return await api.post("/api/payroll/canada/reports/roe", {
    report_template_id: payload.reportTemplateId,
    employee_id: payload.employeeId,
    as_of_date: payload.asOfDate,
  });
};

export const generateCaPd7a = async (payload) => {
  return await api.post("/api/payroll/canada/reports/pd7a", {
    report_template_id: payload.reportTemplateId,
    period_start: payload.periodStart,
    period_end: payload.periodEnd,
  });
};

// Canada bonus/retroactive-pay/vacation-not-taken/accumulated-overtime
// special-payment method (§19) — a standalone calculator, same footing
// as calculateIndiaGratuity, not a payroll-run deduction.
export const calculateCaSpecialPayment = async (payload) => {
  return await api.post("/api/payroll/canada/special-payment/calculate", {
    employee_id: payload.employeeId,
    regular_annual_pay: payload.regularAnnualPay,
    special_payment_amount: payload.specialPaymentAmount,
    payroll_date: payload.payrollDate || null,
  });
};

// US supplemental wages flat-rate method (ZP-TAX-US-2026-001 §3.1, IRS
// Pub. 15) — a standalone calculator, same footing as
// calculateCaSpecialPayment: 22% flat, mandatory 37% on cumulative
// calendar-year supplemental wages above $1,000,000.
export const calculateUsSupplementalWages = async (payload) => {
  return await api.post("/api/payroll/us/supplemental-wages/calculate", {
    employee_id: payload.employeeId,
    supplemental_wage_amount: payload.supplementalWageAmount,
    cytd_supplemental_wages_before: payload.cytdSupplementalWagesBefore || 0,
  });
};

// US federal deposit/filing calendar (ZP-TAX-US-2026-001 §3.5) — org-
// scoped (no employee), a standalone calculator: depositor status,
// deposit due date, $100,000 next-day rule, $500 FUTA deposit trigger,
// Form W-2/W-3 January 31 deadline.
export const calculateUsFederalDepositSchedule = async (payload) => {
  return await api.post("/api/payroll/us/federal-deposit-schedule/calculate", {
    lookback_period_liability: payload.lookbackPeriodLiability,
    payroll_date: payload.payrollDate,
    accumulated_undeposited_liability: payload.accumulatedUndepositedLiability || null,
    quarterly_futa_liability: payload.quarterlyFutaLiability || null,
  });
};

// Canada retiring allowance/severance lump-sum withholding (§19) — rate-
// table lookup, resolves to 0%/unconfigured until Tax Ops enters real
// CRA-sourced bands via Super Admin.
export const calculateCaRetiringAllowance = async (payload) => {
  return await api.post("/api/payroll/canada/retiring-allowance/calculate", {
    employee_id: payload.employeeId,
    amount: payload.amount,
    payroll_date: payload.payrollDate || null,
  });
};

// Canada TD1X commission formula (§18/§19) — recommended per-period
// withholding for a commission employee with TD1X estimates on file.
export const calculateCaTd1xCommission = async (payload) => {
  return await api.post("/api/payroll/canada/td1x-commission/calculate", {
    employee_id: payload.employeeId,
    payroll_date: payload.payrollDate || null,
    pay_periods_per_year: payload.payPeriodsPerYear || 12,
  });
};

// Quebec WSDRF shortfall (§13/§15) — annual reconciliation, employer-
// level, not tied to a single employee or payroll run.
export const calculateCaWsdrf = async (payload) => {
  return await api.post("/api/payroll/canada/wsdrf/calculate", {
    period_start: payload.periodStart,
    period_end: payload.periodEnd,
    training_expenditure_override: payload.trainingExpenditureOverride || null,
  });
};

// ————— France (ZP-FR-ENG-001, 2026-09-24) ————
// Org-facing surface: the employer opens its France DSN, follows the four
// lifecycle signals (FR-032) and drives its own idempotent outbox
// (FR-033). Authority data — PAS rates, establishment AT/MP rate packs,
// governed effectif, employer profile — is Super Admin-owned and lives in
// superAdminService (compliance/france/*), exactly as the backend splits
// them.
export const createFranceDsnSubmission = async (payload) => {
  try {
    return await api.post("/api/payroll/france/dsn-submissions", payload);
  } catch (err) {
    throw err;
  }
};

export const listFranceDsnSubmissionsForOrg = async (params = {}) => {
  try {
    return await api.get("/api/payroll/france/dsn-submissions", { params });
  } catch (err) {
    throw err;
  }
};

export const transitionFranceDsnSubmission = async (submissionId, payload) => {
  try {
    return await api.put(`/api/payroll/france/dsn-submissions/${submissionId}/status`, payload);
  } catch (err) {
    throw err;
  }
};

export const createFranceDsnOutboxItem = async (payload) => {
  try {
    return await api.post("/api/payroll/france/dsn-outbox", payload);
  } catch (err) {
    throw err;
  }
};

export const transitionFranceDsnOutboxItem = async (itemId, status, lastError) => {
  try {
    return await api.put(`/api/payroll/france/dsn-outbox/${itemId}/status`, undefined, {
      params: { status, last_error: lastError || null },
    });
  } catch (err) {
    throw err;
  }
};

// Italy (ZP-IT-ENG-001 §17) — this organization's employer profile. The
// readiness status in the response is recomputed server-side, never sent.
export const getItalyEmployerProfile = async () => {
  try {
    return await api.get("/api/payroll/italy/employer-profile");
  } catch (err) {
    throw err;
  }
};

export const saveItalyEmployerProfile = async (payload) => {
  try {
    return await api.put("/api/payroll/italy/employer-profile", payload);
  } catch (err) {
    throw err;
  }
};

export const getFranceReadinessForOrg = async (forPeriod) => {
  try {
    return await api.get("/api/payroll/france/readiness", {
      params: { for_period: forPeriod || undefined },
    });
  } catch (err) {
    throw err;
  }
};

// ── Switzerland (ZP-CH-PAYROLL-001) — this organization's CH data ─────────
// Every CH WRITE needs an Idempotency-Key header (switzerland_http.py refuses
// writes without one) — baked into these wrappers so callers never worry; a
// retry with the same key replays the stored response instead of writing
// twice. Readiness everywhere is recomputed server-side, never client-sent.
function chIdempotencyKey() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `ch-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const chWriteHeaders = () => ({ "Idempotency-Key": chIdempotencyKey() });

// Employer profile (ChEntityProfileUpsert: uid, seatCanton,
// cantonRegistrations, compensationOfficeSchemeId, fakSchemeId, effectiveFrom,
// reason). Returns { current, readinessNow, versions }.
export const getSwissEntityProfile = async (on) => {
  try {
    return await api.get("/api/payroll/switzerland/entity-profile", { params: on ? { on } : {} });
  } catch (err) {
    throw err;
  }
};

export const saveSwissEntityProfile = async (payload) => {
  try {
    return await api.put("/api/payroll/switzerland/entity-profile", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

// Employer scheme profiles + the platform catalog (org's own rows first).
export const listSwissSchemes = async (params = {}) => {
  try {
    return await api.get("/api/payroll/switzerland/schemes", { params });
  } catch (err) {
    throw err;
  }
};

export const getSwissScheme = async (schemeId) => {
  try {
    return await api.get(`/api/payroll/switzerland/schemes/${schemeId}`);
  } catch (err) {
    throw err;
  }
};

export const createSwissScheme = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/schemes", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const updateSwissScheme = async (schemeId, payload) => {
  try {
    return await api.put(`/api/payroll/switzerland/schemes/${schemeId}`, payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const deleteSwissScheme = async (schemeId) => {
  try {
    return await api.delete(`/api/payroll/switzerland/schemes/${schemeId}`, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const approveSwissScheme = async (schemeId, reason) => {
  try {
    return await api.post(`/api/payroll/switzerland/schemes/${schemeId}/approve`, { reason: reason || null }, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const activateSwissScheme = async (schemeId, reason) => {
  try {
    return await api.post(`/api/payroll/switzerland/schemes/${schemeId}/activate`, { reason: reason || null }, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

// Read-only, ADVISORY QST check (ChQstResolveRequest) — the profile's
// human-recorded ch_qst_subject stays authoritative.
export const resolveSwissQst = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/qst/resolve", payload);
  } catch (err) {
    throw err;
  }
};

// Read-only: CH packs / QST tariff / LIVE schemes / Approved classification /
// Active wage floors in force on a date (canton defaults to the seat canton).
export const getSwissRulesEffective = async (on, canton) => {
  try {
    return await api.get("/api/payroll/switzerland/rules/effective", {
      params: { on: on || undefined, canton: canton || undefined },
    });
  } catch (err) {
    throw err;
  }
};

// Family-allowance entitlements (REQUESTED / APPROVED).
export const listSwissFamilyAllowances = async (params = {}) => {
  try {
    return await api.get("/api/payroll/switzerland/family-allowances", { params });
  } catch (err) {
    throw err;
  }
};

export const getSwissFamilyAllowance = async (entitlementId) => {
  try {
    return await api.get(`/api/payroll/switzerland/family-allowances/${entitlementId}`);
  } catch (err) {
    throw err;
  }
};

export const createSwissFamilyAllowance = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/family-allowances", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const updateSwissFamilyAllowance = async (entitlementId, payload) => {
  try {
    return await api.put(`/api/payroll/switzerland/family-allowances/${entitlementId}`, payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const deleteSwissFamilyAllowance = async (entitlementId) => {
  try {
    return await api.delete(`/api/payroll/switzerland/family-allowances/${entitlementId}`, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const approveSwissFamilyAllowance = async (entitlementId, reason) => {
  try {
    return await api.post(`/api/payroll/switzerland/family-allowances/${entitlementId}/approve`, { reason: reason || null }, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

// Absence-benefit events (maternity, accident, sickness, ...).
export const listSwissAbsenceEvents = async (params = {}) => {
  try {
    return await api.get("/api/payroll/switzerland/absence-events", { params });
  } catch (err) {
    throw err;
  }
};

export const getSwissAbsenceEvent = async (eventId) => {
  try {
    return await api.get(`/api/payroll/switzerland/absence-events/${eventId}`);
  } catch (err) {
    throw err;
  }
};

export const createSwissAbsenceEvent = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/absence-events", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const updateSwissAbsenceEvent = async (eventId, payload) => {
  try {
    return await api.put(`/api/payroll/switzerland/absence-events/${eventId}`, payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const deleteSwissAbsenceEvent = async (eventId) => {
  try {
    return await api.delete(`/api/payroll/switzerland/absence-events/${eventId}`, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

// Append-only payslip corrections (Step 13) — the original payer record is
// never modified; the correction books the per-obligation delta.
export const createSwissCorrection = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/corrections", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const listSwissCorrections = async (payslipId) => {
  try {
    return await api.get(`/api/payroll/switzerland/payslips/${payslipId}/corrections`);
  } catch (err) {
    throw err;
  }
};

// Lohnausweis (Step 14): { employeeId, year, templateId? } generates the
// certificate; only committed payslips feed it.
export const generateSwissLohnausweis = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/lohnausweis/generate", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const listSwissLohnausweis = async (params = {}) => {
  try {
    return await api.get("/api/payroll/switzerland/lohnausweis/certificates", { params });
  } catch (err) {
    throw err;
  }
};

export const getSwissLohnausweisCertificate = async (reportId) => {
  try {
    return await api.get(`/api/payroll/switzerland/lohnausweis/${reportId}/certificate`);
  } catch (err) {
    throw err;
  }
};

// ELM submissions: build envelopes (idempotent, from committed payslips only
// — never a network call), list them, and record the authority RECEIVE/REJECT.
export const buildSwissElmSubmissions = async (payload) => {
  try {
    return await api.post("/api/payroll/switzerland/elm/submissions", payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const listSwissElmSubmissions = async (params = {}) => {
  try {
    return await api.get("/api/payroll/switzerland/elm/submissions", { params });
  } catch (err) {
    throw err;
  }
};

export const transitionSwissElmSubmission = async (submissionId, payload) => {
  try {
    return await api.post(`/api/payroll/switzerland/elm/submissions/${submissionId}/transition`, payload, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};

export const transmitSwissElmSubmission = async (submissionId) => {
  try {
    return await api.post(`/api/payroll/switzerland/elm/submissions/${submissionId}/transmit`, undefined, { headers: chWriteHeaders() });
  } catch (err) {
    throw err;
  }
};
// ── Singapore IR21 tax clearance (hold / clearance / release) ──────────
// Tenant-scoped on the server (the caller's own organization only);
// lifting a hold needs a distinct approver, enforced server-side.
export const listSgIr21Cases = async (params = {}) => {
  const res = await api.get("/api/payroll/singapore/ir21-cases", { params });
  return Array.isArray(res) ? res : res?.data || [];
};

export const createSgIr21Case = async (payload) =>
  // { employeeId, triggerType, triggerDate, awareDate }
  api.post("/api/payroll/singapore/ir21-cases", payload);

export const transitionSgIr21Case = async (caseId, payload) =>
  // { status, filedDate?, filingReference?, directiveDate?, directiveReference?, directiveTaxAmount?, exemptionCategory?, reason? }
  api.post(`/api/payroll/singapore/ir21-cases/${caseId}/transition`, payload);

// ── Singapore Phase 5 — readiness, preflight, CPF EZPay, Compliance Centre ──
// Every figure and status is computed by the server; these calls only fetch
// or submit an operator's decision.
export const getSgEmployerReadiness = async () => api.get("/api/payroll/singapore/readiness");

export const getSgComplianceCentre = async () => api.get("/api/payroll/singapore/compliance-centre");

export const getSgRunPreflight = async (runId) => api.get(`/api/payroll/singapore/runs/${runId}/preflight`);

export const getSgAisReadiness = async (year) => api.get("/api/payroll/singapore/ais-readiness", { params: { year } });

export const listSgPwmClassifications = async () => {
  const res = await api.get("/api/payroll/singapore/pwm-classifications");
  return Array.isArray(res) ? res : res?.data || [];
};

export const recordSgCessation = async (employeeId, dateOfLeaving) =>
  api.post(`/api/payroll/singapore/employees/${employeeId}/cessation`, { dateOfLeaving });

export const listSgCpfEzpay = async () => {
  const res = await api.get("/api/payroll/generated-reports", { params: { reportType: "SG_CPF_EZPAY" } });
  return Array.isArray(res) ? res : res?.data || [];
};

export const prepareSgCpfEzpay = async ({ year, month, adviceCode = "01" }) => {
  const applicable = await api.get("/api/payroll/report-templates/applicable", {
    params: { reportingYear: String(year), reportType: "SG_CPF_EZPAY" },
  });
  const templateId = applicable?.template?.id ?? applicable?.templateId ?? applicable?.id;
  if (!templateId) throw new Error("No Active CPF EZPay template for this year.");
  return api.post("/api/payroll/singapore/reports/cpf-ezpay", { reportTemplateId: templateId, year, month, adviceCode });
};

// Singapore Phase 5.7 — internal compliance reports (PWM / LQS per CPF wage
// month, IR21 register per year) generated server-side from the existing
// evaluators. Resolves the Active template like prepareSgCpfEzpay; these
// routes take snake_case bodies (GY/JM monthly/annual request schemas).
const SG_COMPLIANCE_REPORTS = {
  SG_PWM_COMPLIANCE: "pwm-compliance",
  SG_LQS_COMPLIANCE: "lqs-compliance",
  SG_IR21_REGISTER: "ir21-register",
};

export const generateSgComplianceReport = async (reportType, { year, month }) => {
  const applicable = await api.get("/api/payroll/report-templates/applicable", {
    params: { reportingYear: String(year), reportType },
  });
  const templateId = applicable?.template?.id ?? applicable?.templateId ?? applicable?.id;
  if (!templateId) throw new Error(`No Active ${reportType} template for ${year}.`);
  const body = reportType === "SG_IR21_REGISTER"
    ? { report_template_id: templateId, year }
    : { report_template_id: templateId, year, month };
  return api.post(`/api/payroll/singapore/reports/${SG_COMPLIANCE_REPORTS[reportType]}`, body);
};

export const transitionSgCpfEzpay = async (reportId, payload) =>
  // { status: APPROVED | SUBMITTED | ACCEPTED | REJECTED | UNKNOWN, reference?, note? }
  api.post(`/api/payroll/singapore/reports/cpf-ezpay/${reportId}/transition`, payload);

export const downloadSgCpfEzpayFile = async (reportId) => {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE_URL}/api/payroll/singapore/reports/cpf-ezpay/${reportId}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = "The CPF EZPay file could not be downloaded.";
    try { detail = (await res.json())?.detail || detail; } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  const blob = await res.blob();
  const match = (res.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `cpf-ezpay-${reportId}.DTL`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 100);
  return { filename };
};

// ── Singapore Phase 5.1 — corrections, salary deductions, DR freeze ─────
export const correctSgPayslip = async (payslipId, reason) =>
  api.post(`/api/payroll/singapore/payslips/${payslipId}/corrections`, { reason });

export const listSgPayslipCorrections = async (payslipId) =>
  api.get(`/api/payroll/singapore/payslips/${payslipId}/corrections`);

export const createSgSalaryDeduction = async (employeeId, payload) =>
  // { category, startDate, endDate?, evidenceRef, evidenceDate, amount? | ratePct?, totalToCollect?, priority? }
  api.post(`/api/payroll/singapore/employees/${employeeId}/deductions`, payload);

export const listSgSalaryDeductions = async (employeeId) =>
  api.get(`/api/payroll/singapore/employees/${employeeId}/deductions`);

export const freezeSgAfterRestore = async (restorePoint, restoreDate) =>
  api.post("/api/payroll/singapore/disaster-recovery/freeze", { restorePoint, restoreDate: restoreDate || null });

// Singapore SG-047 — release a post-restore bank-export hold after the bank reconciliation.
export const releaseSgBankExportHold = async (runId, reference) =>
  api.post(`/api/payroll/singapore/disaster-recovery/bank-hold/${runId}/release`, { reference });

// Singapore SG-023 — IR8A extracts and their controlled manual-submission record (API DIRECT SUBMISSION: NOT READY).
export const listSgIr8a = async () => {
  const res = await api.get("/api/payroll/singapore/reports/ir8a");
  return Array.isArray(res) ? res : res?.data || [];
};
export const transitionSgIr8a = async (reportId, { status, reference, note }) =>
  api.post(`/api/payroll/singapore/reports/ir8a/${reportId}/transition`, { status, reference, note });
// Prepare an EXPORT_READY IR8A extract for one income year from the Active SG_IR8A template.
export const generateSgIr8a = async (year) => {
  const applicable = await api.get("/api/payroll/report-templates/applicable", {
    params: { reportingYear: String(year), reportType: "SG_IR8A" },
  });
  const templateId = applicable?.template?.id ?? applicable?.templateId ?? applicable?.id;
  if (!templateId) throw new Error(`No Active IR8A template for ${year}.`);
  return api.post("/api/payroll/singapore/reports/ir8a", { report_template_id: templateId, year });
};
// Phase 6.8 (G3) — Revision (full values) / Amendment (differences) of an IRAS-acknowledged extract.
export const createSgIr8aModification = async (reportId, { method, reason }) =>
  api.post(`/api/payroll/singapore/reports/ir8a/${reportId}/modifications`, { method, reason });

// ── Hong Kong (ZP-HK-ENG-001) — tenant workflows ───────────────────────
// Every rule (MPF, IR56G hold, IRD, eMPF, entitlements, SP/LSP, four-eyes)
// is enforced server-side; these calls only fetch or submit operator input.
const HK = "/api/payroll/hong-kong";
const SA = "/api/payroll/saudi-arabia";
export const recordHkWorkHours = (employeeId, payload) => api.post(`${HK}/employees/${employeeId}/work-hours`, payload);
export const getHkContinuousContract = (employeeId, asOf) =>
  api.get(`${HK}/employees/${employeeId}/continuous-contract`, { params: { as_of: asOf } });
export const listHkTaxClearanceCases = async () => {
  const res = await api.get(`${HK}/tax-clearance`);
  return Array.isArray(res) ? res : res?.data || [];
};
export const identifyHkDeparture = (payload) => api.post(`${HK}/tax-clearance`, payload);
export const recordHkIr56gFiled = (holdId, payload) => api.post(`${HK}/tax-clearance/${holdId}/filed`, payload);
export const requestHkHoldRelease = (holdId, payload) => api.post(`${HK}/tax-clearance/${holdId}/release-request`, payload);
export const approveHkHoldRelease = (holdId) => api.post(`${HK}/tax-clearance/${holdId}/release-approve`, {});
export const changeHkDeparture = (holdId, payload) => api.post(`${HK}/tax-clearance/${holdId}/change`, payload);
export const closeHkHold = (holdId) => api.post(`${HK}/tax-clearance/${holdId}/close`, {});
export const listHkIrdCases = async (yearOfAssessment) => {
  const res = await api.get(`${HK}/ird/cases`, { params: yearOfAssessment ? { year_of_assessment: yearOfAssessment } : {} });
  return Array.isArray(res) ? res : res?.data || [];
};
export const createHkIrdEventCases = (employeeId) => api.post(`${HK}/ird/employees/${employeeId}/event-cases`, {});
export const generateHkAnnualReturn = (yearOfAssessment) => api.post(`${HK}/ird/annual-return`, { yearOfAssessment });
export const transitionHkIrdCase = (caseId, payload) => api.post(`${HK}/ird/cases/${caseId}/transition`, payload);
export const amendHkIrdCase = (caseId, reason) => api.post(`${HK}/ird/cases/${caseId}/amend`, { reason });
export const getHkIrdCaseHistory = async (caseId) => {
  const res = await api.get(`${HK}/ird/cases/${caseId}/history`);
  return Array.isArray(res) ? res : res?.data || [];
};
export const calculateHkAverageWage = (employeeId, payload) => api.post(`${HK}/employees/${employeeId}/average-wage`, payload);
export const calculateHkEntitlement = (employeeId, payload) => api.post(`${HK}/employees/${employeeId}/entitlements`, payload);
export const calculateHkTermination = (employeeId, payload) => api.post(`${HK}/employees/${employeeId}/termination`, payload);
export const approveHkTermination = (resultId) => api.post(`${HK}/termination/${resultId}/approve`, {});
export const listHkEmpfSubmissions = async () => {
  const res = await api.get(`${HK}/empf/submissions`);
  return Array.isArray(res) ? res : res?.data || [];
};
export const prepareHkEmpfSubmission = (contributionPeriod) => api.post(`${HK}/empf/submissions`, { contributionPeriod });
export const transitionHkEmpfSubmission = (id, payload) => api.post(`${HK}/empf/submissions/${id}/transition`, payload);
export const estimateHkSalariesTax = (payload) => api.post(`${HK}/salaries-tax/estimate`, payload);
export const getHkRunPreflight = (runId) => api.get(`${HK}/runs/${runId}/preflight`);
export const getSaRunPreflight = (runId) => api.get(`${SA}/runs/${runId}/preflight`);
export const getSaRunFingerprint = (runId) => api.get(`${SA}/runs/${runId}/fingerprint`);
export const createSaCorrection = (payslipId, payload) => api.post(`${SA}/payslips/${payslipId}/correction`, payload);
export const listSaCorrections = (payslipId, organizationId) => api.get(`${SA}/payslips/${payslipId}/corrections`, { params: { organizationId } });
export const getHkEmployerReadiness = () => api.get(`${HK}/readiness`);
export const getSaEmployerReadiness = () => api.get(`${SA}/readiness`);
export const previewSaudiArabiaCalculation = (payload) => api.post(`${SA}/calculation-preview`, payload);

// SA ledger operations (org-scoped)
export const listSaGosiLiabilities = (organizationId) => api.get(`${SA}/gosi-liabilities`, { params: { organizationId } });
export const buildSaGosiLiability = (runId) => api.post(`${SA}/runs/${runId}/gosi-liability`, {});
export const listSaEosLedger = (organizationId, employeeId) => api.get(`${SA}/eos-ledger`, { params: employeeId ? { organizationId, employeeId } : { organizationId } });
export const accrueSaEos = (runId) => api.post(`${SA}/runs/${runId}/eos-accrual`, {});
export const listSaFinalSettlements = (organizationId, employeeId) => api.get(`${SA}/final-settlements`, { params: employeeId ? { organizationId, employeeId } : { organizationId } });
export const createSaFinalSettlement = (payload) => api.post(`${SA}/final-settlements`, payload);
export const approveSaFinalSettlement = (settlementId) => api.post(`${SA}/final-settlements/${settlementId}/approve`, {});
export const paySaFinalSettlement = (settlementId, paymentReference) => api.post(`${SA}/final-settlements/${settlementId}/pay`, { paymentReference });
export const listSaWpsFiles = (organizationId) => api.get(`${SA}/wps-files`, { params: { organizationId } });
export const buildSaWpsFile = (runId) => api.post(`${SA}/runs/${runId}/wps-file`, {});
export const listSaWpsObservations = (organizationId, wpsFileId) => api.get(`${SA}/wps-files/${wpsFileId}/observations`, { params: { organizationId } });
export const acceptSaWpsFile = (wpsFileId) => api.post(`${SA}/wps-files/${wpsFileId}/accepted`, {});
export const rejectSaWpsFile = (wpsFileId, reason) => api.post(`${SA}/wps-files/${wpsFileId}/rejected`, { reason });

export const recordHkEmployeeCopy = (caseId, evidenceRef) => api.post(`${HK}/ird/cases/${caseId}/employee-copy`, { evidenceRef });
// HK statutory reports (GeneratedReport from an Active template). Bodies are
// snake_case exactly as the server's request schemas declare them.
export const generateHkBir56a = (reportTemplateId, yearOfAssessment) =>
  api.post(`${HK}/reports/bir56a`, { report_template_id: reportTemplateId, year_of_assessment: yearOfAssessment });
export const generateHkIr56b = (reportTemplateId, employeeId, yearOfAssessment) =>
  api.post(`${HK}/reports/ir56b`, { report_template_id: reportTemplateId, employee_id: employeeId, year_of_assessment: yearOfAssessment });
export const generateHkIr56Notification = (reportTemplateId, caseId) =>
  api.post(`${HK}/reports/ir56-notification`, { report_template_id: reportTemplateId, case_id: caseId });
export const generateHkEmpfRemittance = (reportTemplateId, submissionId) =>
  api.post(`${HK}/reports/empf-remittance`, { report_template_id: reportTemplateId, submission_id: submissionId });
export const generateHkMpfContributionRecord = (reportTemplateId, employeeId, contributionPeriod) =>
  api.post(`${HK}/reports/mpf-contribution-record`, { report_template_id: reportTemplateId, employee_id: employeeId, contribution_period: contributionPeriod });
export const generateHkTerminationStatement = (reportTemplateId, terminationResultId) =>
  api.post(`${HK}/reports/termination-statement`, { report_template_id: reportTemplateId, termination_result_id: terminationResultId });
// D-14 linked corrections of committed HK payroll (maker requests, a different checker approves).
export const requestHkCorrection = (payslipId, reason) => api.post(`${HK}/payslips/${payslipId}/corrections`, { reason });
export const listHkCorrections = async (employeeId) => {
  const res = await api.get(`${HK}/corrections`, { params: employeeId ? { employee_id: employeeId } : {} });
  return Array.isArray(res) ? res : res?.data || [];
};
export const listHkTerminationResults = async (employeeId) => {
  const res = await api.get(`${HK}/termination-results`, { params: employeeId ? { employee_id: employeeId } : {} });
  return Array.isArray(res) ? res : res?.data || [];
};
export const listHkAverageWageSnapshots = async (employeeId) => {
  const res = await api.get(`${HK}/employees/${employeeId}/average-wage-snapshots`);
  return Array.isArray(res) ? res : res?.data || [];
};
export const requestHkAverageWageOverride = (snapshotId, payload) => api.post(`${HK}/average-wage/${snapshotId}/override-request`, payload);
export const approveHkAverageWageOverride = (snapshotId) => api.post(`${HK}/average-wage/${snapshotId}/override-approve`, {});
export const approveHkCorrection = (correctionId) => api.post(`${HK}/corrections/${correctionId}/approve`, {});
export const rejectHkCorrection = (correctionId, reason) => api.post(`${HK}/corrections/${correctionId}/reject`, { reason });
// D-19 legal holds and the HK statutory-data access log.
export const listHkLegalHolds = async () => {
  const res = await api.get(`${HK}/legal-holds`);
  return Array.isArray(res) ? res : res?.data || [];
};
export const placeHkLegalHold = (payload) => api.post(`${HK}/legal-holds`, payload);
export const releaseHkLegalHold = (holdId, reason) => api.post(`${HK}/legal-holds/${holdId}/release`, { reason });
export const listHkAccessEvents = async (employeeId) => {
  const res = await api.get(`${HK}/access-events`, { params: employeeId ? { employee_id: employeeId } : {} });
  return Array.isArray(res) ? res : res?.data || [];
};
