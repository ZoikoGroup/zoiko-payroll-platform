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

export const deleteEmployee = async (id) => {
  try {
    return await api.delete(`/api/payroll/employees/${id}`);
  } catch (err) {
    throw err;
  }
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
    const employees = await getEmployees(params);
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