import { useState, useEffect, useCallback, useMemo } from "react";
import { BarChart3, FileText, History, Download, TrendingUp, Banknote, Landmark, Globe2, Users } from "lucide-react";
import { useToast } from "../ToastContext";
import { getPayrollReports, downloadReport, downloadBankTransferFile, getBankTransferSummary } from "../../../service/payrollService";
import ReportGenerationPanel from "./ReportGenerationPanel";
import GeneratedReportPreview from "./GeneratedReportPreview";
import GeneratedReportsHistoryTable from "./GeneratedReportsHistoryTable";
import UKEmployerChargesPanel from "./UKEmployerChargesPanel";
import INForm138Panel from "./INForm138Panel";
import CAPd7aPanel from "./CAPd7aPanel";
import CAWsdrfPanel from "./CAWsdrfPanel";
import USForm941Panel from "./USForm941Panel";
import USForm940Panel from "./USForm940Panel";
import USNewHireReportingPanel from "./USNewHireReportingPanel";
import CHElmSubmissionsPanel from "./CHElmSubmissionsPanel";
import NLLoonaangiftePanel from "./NLLoonaangiftePanel";
import NLJaaropgaafPanel from "./NLJaaropgaafPanel";
import { normalizeCountryCode, getCountryNameFromCode, getCurrencyForJurisdiction, createCurrencyFormatterForCode } from "../../../utils/currency";
import { useEntitledCountries, toEmployeeCountryCode } from "../EntitledCountriesContext";
import { usePayrollSetup } from "../PayrollSetupContext";

const BASE_TABS = [
  { id: "payroll-reports", label: "Payroll Reports", icon: BarChart3 },
  { id: "generate-report",  label: "Generate Report", icon: FileText },
  { id: "report-history",   label: "Report History",  icon: History },
];

// UK Employer Annual Charges (ZP-TAX-UK-2026-27-001 §9.3/§14 gap-closure
// Phase 6, 2026-09-09) is a whole-tax-year, run-independent employer
// liability, unlike everything else on this page — shown as its own tab,
// only for a UK org, rather than forced into the per-run Generate Report
// flow it doesn't fit.
const UK_EMPLOYER_CHARGES_TAB = { id: "uk-employer-charges", label: "Employer Charges", icon: Landmark, country: "UK" };
// India Form 138 (§6.2/§6.3, gap-closure Phase E, 2026-09-10) is
// quarter-level, employer-wide, and never tied to a single PayrollRun —
// same reasoning as the UK Employer Charges tab above for its own tab
// rather than being forced into the run-scoped Generate Report flow.
const IN_FORM_138_TAB = { id: "in-form-138", label: "Form 138", icon: FileText, country: "IN" };
// Canada PD7A (ZP-TAX-CA-2026-001, forms/reports gap-closure) is a
// remittance-period, employer-wide statement, never tied to a single
// PayrollRun — same reasoning as the India Form 138 tab above.
const CA_PD7A_TAB = { id: "ca-pd7a", label: "PD7A", icon: Landmark, country: "CA" };
const CH_ELM_TAB = { id: "ch-elm", label: "ELM submissions", icon: Landmark, country: "CH" };
// Netherlands payroll-tax returns and annual statements — period/year-level,
// employer-wide, never tied to a single PayrollRun (same reasoning as PD7A).
const NL_LOONAANGIFTE_TAB = { id: "nl-loonaangifte", label: "Loonaangifte", icon: Landmark, country: "NL" };
const NL_JAAROPGAAF_TAB = { id: "nl-jaaropgaaf", label: "Jaaropgaaf", icon: FileText, country: "NL" };
// Quebec WSDRF (gap-closure Phase 7) — same employer-wide, non-run-based
// reasoning as the PD7A tab above.
const CA_WSDRF_TAB = { id: "ca-wsdrf", label: "Quebec WSDRF", icon: Landmark, country: "CA" };
// US Form 941/940 (Production-Readiness Plan Phase 5) — quarter/year-
// level, employer-wide, never tied to a single PayrollRun, same reasoning
// as the PD7A tab above.
const US_941_TAB = { id: "us-941", label: "Form 941", icon: Landmark, country: "US" };
const US_940_TAB = { id: "us-940", label: "Form 940", icon: Landmark, country: "US" };
// New Hire Reporting is compliance TRACKING (a due-date + mark-filed
// list), not report generation like 941/940 above — still its own tab,
// same "doesn't fit the run-scoped Generate Report flow" reasoning.
const US_NEW_HIRE_TAB = { id: "us-new-hire", label: "New Hire Reporting", icon: FileText, country: "US" };
// ASUME reporting (PR-007/PR-023) reuses the exact same NewHireReport
// tracking mechanism/API as US New Hire Reporting above (org-scoped only,
// no country filter server-side — see USNewHireReportingPanel's own
// comment) — its own tab/copy since Puerto Rico orgs shouldn't see "state
// new-hire registry" language for a Puerto Rico child-support agency.
const PR_ASUME_TAB = { id: "pr-asume", label: "ASUME Reporting", icon: FileText, country: "PR" };
// Statutory report tabs per payroll country, in this order.
const COUNTRY_TABS = {
  IN: [IN_FORM_138_TAB],
  US: [US_941_TAB, US_940_TAB, US_NEW_HIRE_TAB],
  UK: [UK_EMPLOYER_CHARGES_TAB],
  CA: [CA_PD7A_TAB, CA_WSDRF_TAB],
  PR: [PR_ASUME_TAB],
  CH: [CH_ELM_TAB],
  NL: [NL_LOONAANGIFTE_TAB, NL_JAAROPGAAF_TAB],
};

const countryLabel = (code) => getCountryNameFromCode(code) || code;
const currencyOf = (code) => getCurrencyForJurisdiction(code)?.code || "";
// Locale-grouped amount in one explicit currency (₹1,00,000.00 / $8,000.00 / £5,000.00).
const formatMoney = (amount, code) => createCurrencyFormatterForCode(code)(amount);

export default function ReportsPage() {
  const { addToast } = useToast();
  const { company, currencyCode } = usePayrollSetup();
  const entitlement = useEntitledCountries();
  const jurisdictionCountry = (company?.jurisdictionCountry || company?.jurisdiction_country || "").toUpperCase();
  // Every country the org pays employees in (Compliance → Countries), primary
  // first — each gets its own statutory reports, not just the primary one.
  // Permissive default-to-IN for an org with no country set yet (most orgs
  // never explicitly set the jurisdiction field).
  const primaryCountry = entitlement.primaryEmployeeCode
    || toEmployeeCountryCode(normalizeCountryCode(jurisdictionCountry) || jurisdictionCountry) || "IN";
  const orgCountries = (() => {
    const codes = entitlement.loaded && entitlement.entitledEmployeeCodes.length > 0
      ? entitlement.entitledEmployeeCodes : [primaryCountry];
    return [...new Set(codes)].sort((a, b) => (a === primaryCountry ? -1 : b === primaryCountry ? 1 : 0));
  })();
  const paysIn = (code) => orgCountries.includes(code);
  const isUk = paysIn("UK");
  const isIndia = paysIn("IN");
  const isCanada = paysIn("CA");
  const isUs = paysIn("US");
  const isPr = paysIn("PR");
  const isSwitzerland = paysIn("CH");
  const isNetherlands = paysIn("NL");
  const employeeCountByCountry = Object.fromEntries(
    (entitlement.countries || []).map((c) => [toEmployeeCountryCode(c.code), c.employeeCount ?? null])
  );
  const countryTabGroups = orgCountries
    .map((code) => ({ code, tabs: COUNTRY_TABS[code] || [] }))
    .filter((g) => g.tabs.length > 0);
  const tabs = [...BASE_TABS, ...countryTabGroups.flatMap((g) => g.tabs)];
  const [activeTab, setActiveTab] = useState("payroll-reports");
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadCount, setDownloadCount] = useState(0);
  const [bankFileFormat, setBankFileFormat] = useState({});
  const [downloadingBankFileId, setDownloadingBankFileId] = useState(null);
  // reportId -> the run's countries (bank-transfer-summary `countries`),
  // looked up on first download. A run paying more than one country needs
  // one bank file per country — the backend rejects a combined file.
  const [bankFileCountries, setBankFileCountries] = useState({});

  // The most recently generated statutory report (Generate Report tab) —
  // shown as a preview until the user generates another one or leaves
  // the tab. History of every past generation lives in Report History,
  // driven independently by GeneratedReportsHistoryTable's own fetch.
  const [latestGenerated, setLatestGenerated] = useState(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  const latestReport = useMemo(() => {
    if (!reports.length) return null;
    return [...reports].sort((a, b) => {
      const dateA = new Date(a.generatedAt || a.generated || 0);
      const dateB = new Date(b.generatedAt || b.generated || 0);
      return dateB - dateA;
    })[0];
  }, [reports]);

  const handleDownloadReport = useCallback(async (report) => {
    if (!report?.id) return;
    setDownloadingId(report.id);
    try {
      await downloadReport(report.id);
      setDownloadCount((c) => c + 1);
      addToast?.("Report downloaded successfully.", "success");
    } catch {
      addToast?.("Failed to download report.", "error");
    } finally {
      setDownloadingId(null);
    }
  }, [addToast]);

  const handleDownloadBankFile = useCallback(async (report, country) => {
    if (!report?.id) return;
    const format = bankFileFormat[report.id] || "csv";
    setDownloadingBankFileId(country ? `${report.id}:${country}` : report.id);
    try {
      if (!country) {
        let countries = bankFileCountries[report.id];
        if (!countries) {
          const summary = await getBankTransferSummary(report.id);
          countries = summary?.countries || [];
          setBankFileCountries((prev) => ({ ...prev, [report.id]: countries }));
        }
        if (countries.length > 1) {
          addToast?.(`This run pays employees in ${countries.length} countries — download one bank file per country.`, "info");
          return;
        }
      }
      await downloadBankTransferFile(report.id, format, country);
      setDownloadCount((c) => c + 1);
      const countryName = country ? `${getCountryNameFromCode(country) || country} ` : "";
      addToast?.(`${countryName}Bank transfer file (${format.toUpperCase()}) downloaded.`, "success");
    } catch (err) {
      addToast?.(err?.message || "Failed to generate bank transfer file.", "error");
    } finally {
      setDownloadingBankFileId(null);
    }
  }, [addToast, bankFileFormat, bankFileCountries]);

  const thisPeriodLabel = useMemo(() => {
    if (!latestReport) return "--";
    return latestReport.period || "--";
  }, [latestReport]);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPayrollReports();
      setReports(Array.isArray(data) ? data : []);
    } catch {
      addToast?.("Failed to load reports.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  return (
    <div className="bg-background min-h-screen p-6 lg:p-8 space-y-6">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-[12px] bg-primary flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
          <BarChart3 size={20} className="text-white" />
        </div>
        <div>
          <h1 className="text-[28px] font-extrabold tracking-tight text-foreground">Payroll Reports</h1>
          <p className="text-[13px] font-medium text-foreground-muted">Generate and download payroll reports</p>
        </div>
      </div>

      <div className="bg-surface border border-border rounded-[18px] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)]" data-testid="report-countries">
        <p className="mb-3 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          <Globe2 size={13} /> Reporting for {orgCountries.length} {orgCountries.length === 1 ? "country" : "countries"}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {orgCountries.map((code) => (
            <div key={code} className="rounded-[14px] border border-border bg-background px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[15px] font-bold text-foreground">{countryLabel(code)}</p>
                {code === primaryCountry && (
                  <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-primary">Primary</span>
                )}
              </div>
              <p className="mt-0.5 text-[12px] text-foreground-muted">
                {code}{currencyOf(code) ? ` · ${currencyOf(code)}` : ""}
                {employeeCountByCountry[code] != null && ` · ${employeeCountByCountry[code]} employee${employeeCountByCountry[code] === 1 ? "" : "s"}`}
              </p>
              <p className="mt-1.5 text-[11px] text-foreground-muted">
                {(COUNTRY_TABS[code] || []).length > 0
                  ? `Statutory reports: ${(COUNTRY_TABS[code] || []).map((t) => t.label).join(", ")}`
                  : "Payroll register and bank file in Payroll Reports"}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex gap-1 bg-surface-muted rounded-[14px] p-1 w-fit flex-wrap">
          {BASE_TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
                activeTab === t.id ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
              }`}
            >
              <t.icon size={15} />
              {t.label}
            </button>
          ))}
        </div>
        {countryTabGroups.length > 0 && (
          <div className="flex flex-wrap items-center gap-2" data-testid="country-report-tabs">
            {countryTabGroups.map((group) => (
              <div key={group.code} className="flex items-center gap-1 rounded-[14px] bg-surface-muted p-1">
                <span className="px-2.5 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{countryLabel(group.code)}</span>
                {group.tabs.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setActiveTab(t.id)}
                    title={`${countryLabel(group.code)} — ${t.label}`}
                    className={`flex items-center gap-1.5 px-3.5 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
                      activeTab === t.id ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    <t.icon size={14} />
                    {t.label}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      {(() => {
        const active = tabs.find((t) => t.id === activeTab);
        return active?.country ? (
          <p className="text-[13px] font-semibold text-foreground">
            {countryLabel(active.country)} <span className="text-foreground-muted font-medium">· {active.label} · amounts in {currencyOf(active.country)}</span>
          </p>
        ) : null;
      })()}

      {activeTab === "payroll-reports" && (
        <div className="space-y-6">
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
              <div className="p-2.5 rounded-[12px] bg-primary/10">
                <FileText className="w-5 h-5 text-primary" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-foreground">{reports.length}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Total Reports</p>
              </div>
            </div>
            <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
              <div className="p-2.5 rounded-[12px] bg-info/10">
                <TrendingUp className="w-5 h-5 text-info" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-foreground">{thisPeriodLabel}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">This Period</p>
              </div>
            </div>
            <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
              <div className="p-2.5 rounded-[12px] bg-warning/10">
                <Download className="w-5 h-5 text-warning" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-foreground">{downloadCount}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Downloads</p>
              </div>
            </div>
          </div>

          {latestReport?.countries?.length > 0 && (
            <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]" data-testid="latest-run-by-country">
              <p className="mb-3 text-[13px] font-bold text-foreground">
                {latestReport.period || "Latest run"} <span className="font-medium text-foreground-muted">· by country, each in its own currency</span>
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {latestReport.countries.map((c) => (
                  <div key={c.country} className="rounded-[14px] border border-border bg-background p-4">
                    <div className="flex items-center justify-between">
                      <p className="text-[14px] font-bold text-foreground">{countryLabel(c.country)}</p>
                      <span className="flex items-center gap-1 text-[12px] text-foreground-muted"><Users size={12} /> {c.employeeCount}</span>
                    </div>
                    <dl className="mt-2 space-y-1 text-[12px]">
                      <div className="flex justify-between"><dt className="text-foreground-muted">Gross pay</dt><dd className="font-semibold text-foreground">{formatMoney(c.totalGross, c.currency)}</dd></div>
                      <div className="flex justify-between"><dt className="text-foreground-muted">Deductions</dt><dd className="text-foreground">{formatMoney(c.totalDeductions, c.currency)}</dd></div>
                      <div className="flex justify-between"><dt className="text-foreground-muted">Employer cost</dt><dd className="text-foreground">{formatMoney(c.totalEmployerContribution, c.currency)}</dd></div>
                      <div className="flex justify-between border-t border-border pt-1"><dt className="font-semibold text-foreground">Net pay</dt><dd className="font-bold text-primary">{formatMoney(c.totalNet, c.currency)}</dd></div>
                    </dl>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
            {loading ? (
              <div className="text-center py-12 space-y-3">
                <div className="flex justify-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
                  <div className="h-2 w-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
                  <div className="h-2 w-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
                <p className="text-[13px] text-foreground-muted">Loading reports...</p>
              </div>
            ) : reports.length === 0 ? (
              <div className="text-center py-16">
                <BarChart3 size={40} className="mx-auto mb-3 text-foreground-muted" />
                <p className="text-[15px] font-bold text-foreground">No reports yet</p>
                <p className="text-[13px] text-foreground-muted mt-1">Reports will appear here once payroll runs are completed</p>
              </div>
            ) : (
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Report Name</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Period</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Countries</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Generated</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Status</th>
                    <th className="px-5 py-3.5" />
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Bank Transfer File</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {reports.map((r, i) => (
                    <tr key={r.id || i} className="hover:bg-background dark:hover:bg-surface-muted transition-colors duration-150">
                      <td className="px-5 py-4 font-semibold text-foreground">{r.name || "Payroll Report"}</td>
                      <td className="px-5 py-4 text-[13px] text-foreground-muted">{r.period || "-"}</td>
                      <td className="px-5 py-4">
                        <div className="flex flex-wrap gap-1.5">
                          {(r.countries || []).length === 0 ? <span className="text-[12px] text-foreground-muted">-</span> : r.countries.map((c) => (
                            <span key={c.country} title={`${countryLabel(c.country)}: ${c.employeeCount} employee(s), net ${formatMoney(c.totalNet, c.currency)}`}
                              className="inline-flex items-center gap-1 rounded-full bg-info/10 px-2.5 py-1 text-[11px] font-semibold text-info whitespace-nowrap">
                              {countryLabel(c.country)} · {c.employeeCount} · {formatMoney(c.totalNet, c.currency)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-5 py-4 text-[13px] text-foreground-muted">{r.generatedAt || r.generated || "-"}</td>
                      <td className="px-5 py-4">
                        <span className="inline-flex items-center gap-1 rounded-full bg-info/10 text-info px-3 py-1 text-[11px] font-bold">
                          {r.status || "available"}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <button
                          onClick={() => handleDownloadReport(r)}
                          disabled={downloadingId === r.id}
                          className="flex items-center gap-1.5 rounded-[12px] bg-primary text-white px-3.5 py-2 text-[13px] font-bold hover:bg-primary-hover transition-all duration-200 shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <Download size={12} /> {downloadingId === r.id ? "Downloading..." : "Download"}
                        </button>
                      </td>
                      <td className="px-5 py-4">
                        {r.status === "available" ? (
                          <div className="flex items-center gap-2">
                            <select
                              value={bankFileFormat[r.id] || "csv"}
                              onChange={(e) => setBankFileFormat((prev) => ({ ...prev, [r.id]: e.target.value }))}
                              className="rounded-[10px] border border-border bg-background px-2.5 py-2 text-[12px] font-semibold text-foreground focus:outline-none focus:border-category-teal focus:ring-2 focus:ring-category-teal/20"
                            >
                              <option value="csv">CSV</option>
                              <option value="xlsx">Excel (.xlsx)</option>
                              <option value="txt">TXT</option>
                              <option value="pdf">PDF</option>
                            </select>
                            {(bankFileCountries[r.id] || r.countries || []).length > 1 ? (
                              <div className="flex flex-wrap items-center gap-1.5">
                                {(bankFileCountries[r.id] || r.countries).map((c) => (
                                  <button
                                    key={c.country}
                                    onClick={() => handleDownloadBankFile(r, c.country)}
                                    disabled={downloadingBankFileId === `${r.id}:${c.country}`}
                                    title={`Generate and download this run's ${getCountryNameFromCode(c.country) || c.country} bank transfer file (${c.currency})`}
                                    className="flex items-center gap-1.5 rounded-[12px] bg-category-teal text-white px-3 py-2 text-[12px] font-bold hover:bg-category-teal transition-all duration-200 shadow-[0_2px_8px_rgba(157,123,242,0.3)] disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                                  >
                                    <Banknote size={12} /> {downloadingBankFileId === `${r.id}:${c.country}` ? "Generating..." : (getCountryNameFromCode(c.country) || c.country)}
                                  </button>
                                ))}
                              </div>
                            ) : (
                              <button
                                onClick={() => handleDownloadBankFile(r)}
                                disabled={downloadingBankFileId === r.id}
                                title="Generate and download this run's bank transfer file"
                                className="flex items-center gap-1.5 rounded-[12px] bg-category-teal text-white px-3.5 py-2 text-[13px] font-bold hover:bg-category-teal transition-all duration-200 shadow-[0_2px_8px_rgba(157,123,242,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                <Banknote size={12} /> {downloadingBankFileId === r.id ? "Generating..." : "Download"}
                              </button>
                            )}
                          </div>
                        ) : (
                          <span className="text-[12px] text-foreground-muted">Available once approved</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {activeTab === "generate-report" && (
        <div className="space-y-6">
          <ReportGenerationPanel
            onGenerated={(report) => {
              setLatestGenerated(report);
              setHistoryRefreshKey((k) => k + 1);
            }}
          />
          {latestGenerated && <GeneratedReportPreview report={latestGenerated} currencyCode={currencyCode} />}
        </div>
      )}

      {activeTab === "report-history" && (
        <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
          <GeneratedReportsHistoryTable
            refreshKey={historyRefreshKey}
            onView={(report) => { setLatestGenerated(report); setActiveTab("generate-report"); }}
          />
        </div>
      )}

      {isUk && activeTab === "uk-employer-charges" && <UKEmployerChargesPanel />}
      {isIndia && activeTab === "in-form-138" && <INForm138Panel />}
      {isCanada && activeTab === "ca-pd7a" && <CAPd7aPanel />}
      {isSwitzerland && activeTab === "ch-elm" && <CHElmSubmissionsPanel />}
      {isNetherlands && activeTab === "nl-loonaangifte" && <NLLoonaangiftePanel />}
      {isNetherlands && activeTab === "nl-jaaropgaaf" && <NLJaaropgaafPanel />}
      {isCanada && activeTab === "ca-wsdrf" && <CAWsdrfPanel />}
      {isUs && activeTab === "us-941" && <USForm941Panel />}
      {isUs && activeTab === "us-940" && <USForm940Panel />}
      {isUs && activeTab === "us-new-hire" && <USNewHireReportingPanel />}
      {isPr && activeTab === "pr-asume" && (
        <USNewHireReportingPanel
          title="ASUME Reporting"
          subtitle={
            "Every new or rehired Puerto Rico employee is required to be reported to ASUME within the statutory window. " +
            "A Pending row is created automatically when a new Puerto Rico employee is added. The due date shown is a " +
            "SUGGESTION (hire date + 20 days, per current official ASUME new-hire guidance) — verify and mark filed once " +
            "actually reported."
          }
        />
      )}
    </div>
  );
}
