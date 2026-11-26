import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { BarChart3, FileText, History, Download, TrendingUp, Banknote, Landmark, Users, Info } from "lucide-react";
import { useToast } from "../ToastContext";
import {
  getPayrollReports, downloadReport, downloadBankTransferFile, getBankTransferSummary, getReportCatalog, fetchRuns,
} from "../../../service/payrollService";
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
import StatutoryFormPanel from "./StatutoryFormPanel";
import ReportCountrySelector from "./ReportCountrySelector";
import { normalizeCountryCode, getCountryNameFromCode, getCurrencyForJurisdiction, createCurrencyFormatterForCode } from "../../../utils/currency";
import { useEntitledCountries, toEmployeeCountryCode } from "../EntitledCountriesContext";
import ZAFilingPanel from "./ZAFilingPanel";
import { usePayrollSetup } from "../PayrollSetupContext";

const PAYROLL_REPORTS_TAB = { id: "payroll-reports", label: "Payroll register & bank file", icon: BarChart3 };
const TRAILING_TABS = [
  { id: "generate-report", label: "Generate Report", icon: FileText },
  { id: "report-history", label: "Report History", icon: History },
];
const BASE_TAB_IDS = new Set([PAYROLL_REPORTS_TAB.id, ...TRAILING_TABS.map((t) => t.id)]);

// Built-in country tools with their own panels. They predate the Super Admin
// report catalog and some are not report templates at all (New Hire / ASUME
// tracking, UK employer charges), so they stay — next to every form the
// catalog lists. `reportType` lets a catalog form of the same type replace
// the built-in tab rather than show twice.
const BUILTIN_TOOLS = {
  IN: [{ id: "in-form-138", label: "Form 138", icon: FileText, reportType: "FORM_138" }],
  US: [
    { id: "us-941", label: "Form 941", icon: Landmark },
    { id: "us-940", label: "Form 940", icon: Landmark },
    { id: "us-new-hire", label: "New Hire Reporting", icon: FileText },
  ],
  UK: [{ id: "uk-employer-charges", label: "Employer Charges", icon: Landmark }],
  CA: [
    { id: "ca-pd7a", label: "PD7A", icon: Landmark, reportType: "PD7A" },
    { id: "ca-wsdrf", label: "Quebec WSDRF", icon: Landmark },
  ],
  PR: [{ id: "pr-asume", label: "ASUME Reporting", icon: FileText }],
  CH: [{ id: "ch-elm", label: "ELM submissions", icon: Landmark }],
  NL: [
    { id: "nl-loonaangifte", label: "Loonaangifte", icon: Landmark },
    { id: "nl-jaaropgaaf", label: "Jaaropgaaf", icon: FileText },
  ],
  ZA: [{ id: "za-filing", label: "SARS Filing", icon: Landmark }],
};

const BUILTIN_PANELS = {
  "uk-employer-charges": () => <UKEmployerChargesPanel />,
  "in-form-138": () => <INForm138Panel />,
  "ca-pd7a": () => <CAPd7aPanel />,
  "ca-wsdrf": () => <CAWsdrfPanel />,
  "ch-elm": () => <CHElmSubmissionsPanel />,
  "nl-loonaangifte": () => <NLLoonaangiftePanel />,
  "nl-jaaropgaaf": () => <NLJaaropgaafPanel />,
  "za-filing": () => <ZAFilingPanel />,
  "us-941": () => <USForm941Panel />,
  "us-940": () => <USForm940Panel />,
  "us-new-hire": () => <USNewHireReportingPanel />,
  "pr-asume": () => (
    <USNewHireReportingPanel
      title="ASUME Reporting"
      subtitle={
        "Every new or rehired Puerto Rico employee is required to be reported to ASUME within the statutory window. " +
        "A Pending row is created automatically when a new Puerto Rico employee is added. The due date shown is a " +
        "SUGGESTION (hire date + 20 days, per current official ASUME new-hire guidance) — verify and mark filed once " +
        "actually reported."
      }
    />
  ),
};

const countryLabel = (code) => getCountryNameFromCode(code) || code;
const currencyOf = (code) => getCurrencyForJurisdiction(code)?.code || "";
// Locale-grouped amount in one explicit currency (₹1,00,000.00 / A$8,000.00 / CHF 5,000.00).
const formatMoney = (amount, code) => (code ? createCurrencyFormatterForCode(code)(amount) : "—");
// "Salary TDS Certificate (Form 130)" -> "Form 130"; otherwise the full name.
const shortFormLabel = (name = "") => {
  const m = name.match(/\(([^)]+)\)\s*$/);
  return m && m[1].length <= 24 ? m[1] : name;
};
const runHasCountry = (report, code, primaryCountry) =>
  (report.countries || []).length === 0 ? code === primaryCountry : report.countries.some((c) => c.country === code);

export default function ReportsPage() {
  const { addToast } = useToast();
  const { company, currencyCode } = usePayrollSetup();
  const entitlement = useEntitledCountries();
  const [searchParams, setSearchParams] = useSearchParams();
  const jurisdictionCountry = (company?.jurisdictionCountry || company?.jurisdiction_country || "").toUpperCase();
  // Every country active in Compliance → Countries, primary first — each gets
  // its own statutory reports, not just the primary one. Permissive
  // default-to-IN for an org with no country set yet.
  const primaryCountry = entitlement.primaryEmployeeCode
    || toEmployeeCountryCode(normalizeCountryCode(jurisdictionCountry) || jurisdictionCountry) || "IN";
  const orgCountries = useMemo(() => {
    const codes = entitlement.loaded && entitlement.entitledEmployeeCodes.length > 0
      ? entitlement.entitledEmployeeCodes : [primaryCountry];
    return [...new Set(codes)].sort((a, b) => (a === primaryCountry ? -1 : b === primaryCountry ? 1 : 0));
  }, [entitlement.loaded, entitlement.entitledEmployeeCodes, primaryCountry]);

  // ── URL state: ?country=IN&tab=form:FORM_130&scope=all ────────────────────
  const countryParam = toEmployeeCountryCode(searchParams.get("country") || "");
  const selectedCountry = orgCountries.includes(countryParam) ? countryParam : primaryCountry;
  const scopeAll = searchParams.get("scope") === "all";
  const updateParams = useCallback((changes) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      Object.entries(changes).forEach(([k, v]) => (v == null || v === "" ? next.delete(k) : next.set(k, v)));
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  // ── Super Admin report catalog (per-country statutory forms) ──────────────
  const [catalog, setCatalog] = useState({});
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  useEffect(() => {
    let cancelled = false;
    getReportCatalog()
      .then((data) => {
        if (cancelled) return;
        setCatalog(Object.fromEntries(data.countries.map((c) => [toEmployeeCountryCode(c.country), c.forms || []])));
      })
      .catch((err) => !cancelled && setCatalogError(err?.message || "Could not load the statutory form catalog."))
      .finally(() => !cancelled && setCatalogLoading(false));
    return () => { cancelled = true; };
  }, []);

  // Tabs for one country: every catalog form, then built-in tools the catalog doesn't already cover.
  const formTabsFor = useCallback((code) => {
    const forms = catalog[code] || [];
    const fromCatalog = forms.map((f) => ({
      id: `form:${f.reportType}`, label: shortFormLabel(f.name), title: f.name, icon: FileText, form: f,
    }));
    const builtins = (BUILTIN_TOOLS[code] || [])
      .filter((t) => !forms.some((f) => (t.reportType && f.reportType === t.reportType)
        || (f.name || "").toLowerCase().includes(t.label.toLowerCase())))
      .map((t) => ({ ...t, title: t.label, builtin: true }));
    return [...fromCatalog, ...builtins];
  }, [catalog]);

  const selectorCountries = useMemo(() => {
    const employeeCountByCountry = Object.fromEntries(
      (entitlement.countries || []).map((c) => [toEmployeeCountryCode(c.code), c.employeeCount ?? null]),
    );
    return orgCountries.map((code) => ({
      code,
      name: countryLabel(code),
      currency: currencyOf(code),
      employeeCount: employeeCountByCountry[code] ?? null,
      isPrimary: code === primaryCountry,
      forms: formTabsFor(code).map((t) => ({ key: t.id, name: t.title })),
    }));
  }, [orgCountries, entitlement.countries, primaryCountry, formTabsFor]);

  const countryTabs = formTabsFor(selectedCountry);
  const tabParam = searchParams.get("tab") || PAYROLL_REPORTS_TAB.id;
  const activeTab = BASE_TAB_IDS.has(tabParam) || countryTabs.some((t) => t.id === tabParam) ? tabParam : PAYROLL_REPORTS_TAB.id;
  const activeCountryTab = countryTabs.find((t) => t.id === activeTab) || null;
  const setActiveTab = (id) => updateParams({ tab: id === PAYROLL_REPORTS_TAB.id ? null : id });
  const selectCountry = (code) => updateParams({
    country: code === primaryCountry ? null : code,
    // Country-specific form tabs don't carry over; shared tabs do.
    tab: BASE_TAB_IDS.has(activeTab) && activeTab !== PAYROLL_REPORTS_TAB.id ? activeTab : null,
  });

  // ── Payroll register / bank file data ─────────────────────────────────────
  const [reports, setReports] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState(null);
  // Every download this session, tagged with the countries it covers, so the
  // counter can follow the country filter.
  const [downloads, setDownloads] = useState([]);
  const [bankFileFormat, setBankFileFormat] = useState({});
  const [downloadingBankFileId, setDownloadingBankFileId] = useState(null);
  // reportId -> the run's countries (bank-transfer-summary `countries`),
  // looked up on first download. A run paying more than one country needs
  // one bank file per country — the backend rejects a combined file.
  const [bankFileCountries, setBankFileCountries] = useState({});

  // The most recently generated statutory report — shown as a preview until
  // the user generates another one or leaves the tab.
  const [latestGenerated, setLatestGenerated] = useState(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const onGenerated = useCallback((report) => {
    setLatestGenerated(report);
    setHistoryRefreshKey((k) => k + 1);
  }, []);

  const scopedReports = useMemo(
    () => (scopeAll ? reports : reports.filter((r) => runHasCountry(r, selectedCountry, primaryCountry))),
    [reports, scopeAll, selectedCountry, primaryCountry],
  );
  const scopedDownloadCount = scopeAll
    ? downloads.length
    : downloads.filter((d) => d.countries.includes(selectedCountry)).length;

  const latestReport = useMemo(() => {
    if (!scopedReports.length) return null;
    return [...scopedReports].sort((a, b) => {
      const dateA = new Date(a.generatedAt || a.generated || 0);
      const dateB = new Date(b.generatedAt || b.generated || 0);
      return dateB - dateA;
    })[0];
  }, [scopedReports]);
  const visibleCountries = (r) => (scopeAll ? (r.countries || []) : (r.countries || []).filter((c) => c.country === selectedCountry));

  const recordDownload = useCallback((countries) => {
    setDownloads((prev) => [...prev, { countries: countries.length ? countries : [primaryCountry] }]);
  }, [primaryCountry]);

  const handleDownloadReport = useCallback(async (report) => {
    if (!report?.id) return;
    setDownloadingId(report.id);
    try {
      await downloadReport(report.id);
      recordDownload((report.countries || []).map((c) => c.country));
      addToast?.("Report downloaded successfully.", "success");
    } catch {
      addToast?.("Failed to download report.", "error");
    } finally {
      setDownloadingId(null);
    }
  }, [addToast, recordDownload]);

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
      recordDownload(country ? [country] : (report.countries || []).map((c) => c.country));
      const countryName = country ? `${countryLabel(country)} ` : "";
      addToast?.(`${countryName}Bank transfer file (${format.toUpperCase()}) downloaded.`, "success");
    } catch (err) {
      addToast?.(err?.message || "Failed to generate bank transfer file.", "error");
    } finally {
      setDownloadingBankFileId(null);
    }
  }, [addToast, bankFileFormat, bankFileCountries, recordDownload]);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const [data, runList] = await Promise.all([getPayrollReports(), fetchRuns()]);
      setReports(Array.isArray(data) ? data : []);
      setRuns(Array.isArray(runList) ? runList : []);
    } catch {
      addToast?.("Failed to load reports.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  const selectedName = countryLabel(selectedCountry);
  const scopeLabel = scopeAll ? "All countries" : selectedName;

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

      <ReportCountrySelector
        countries={selectorCountries}
        selected={selectedCountry}
        onSelect={selectCountry}
        loadingForms={catalogLoading}
      />

      {catalogError && (
        <p className="rounded-[12px] bg-warning/10 px-4 py-2.5 text-[12px] text-warning">
          {catalogError} Built-in reports are still available.
        </p>
      )}

      {/* Scope for the counters, the payroll register table and Report History */}
      <div className="flex flex-wrap items-center gap-2" data-testid="report-scope">
        <span className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Showing</span>
        <div className="flex gap-1 rounded-[12px] bg-surface-muted p-1">
          {[
            { all: false, label: selectedName },
            { all: true, label: "All countries" },
          ].map((opt) => (
            <button
              key={String(opt.all)}
              type="button"
              aria-pressed={scopeAll === opt.all}
              onClick={() => updateParams({ scope: opt.all ? "all" : null })}
              className={`rounded-[10px] px-3 py-1.5 text-[12px] font-semibold transition-all ${
                scopeAll === opt.all ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4" data-testid="report-counters">
        <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="p-2.5 rounded-[12px] bg-primary/10"><FileText className="w-5 h-5 text-primary" /></div>
          <div>
            <p className="text-[22px] font-bold text-foreground">{scopedReports.length}</p>
            <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Total Reports · {scopeLabel}</p>
          </div>
        </div>
        <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="p-2.5 rounded-[12px] bg-info/10"><TrendingUp className="w-5 h-5 text-info" /></div>
          <div>
            <p className="text-[22px] font-bold text-foreground">{latestReport?.period || "--"}</p>
            <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">This Period · {scopeLabel}</p>
          </div>
        </div>
        <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="p-2.5 rounded-[12px] bg-warning/10"><Download className="w-5 h-5 text-warning" /></div>
          <div>
            <p className="text-[22px] font-bold text-foreground">{scopedDownloadCount}</p>
            <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Downloads this session · {scopeLabel}</p>
          </div>
        </div>
      </div>

      {/* Tabs: register & bank file | the selected country's forms | generate | history */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 bg-surface-muted rounded-[14px] p-1 flex-wrap">
            {[PAYROLL_REPORTS_TAB].map((t) => (
              <TabButton key={t.id} tab={t} active={activeTab === t.id} onClick={() => setActiveTab(t.id)} />
            ))}
          </div>
          {countryTabs.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 rounded-[14px] bg-surface-muted p-1" data-testid="country-report-tabs">
              <span className="px-2.5 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{selectedName}</span>
              {countryTabs.map((t) => (
                <TabButton key={t.id} tab={t} active={activeTab === t.id} onClick={() => setActiveTab(t.id)} small />
              ))}
            </div>
          )}
          <div className="flex gap-1 bg-surface-muted rounded-[14px] p-1 flex-wrap">
            {TRAILING_TABS.map((t) => (
              <TabButton key={t.id} tab={t} active={activeTab === t.id} onClick={() => setActiveTab(t.id)} />
            ))}
          </div>
        </div>
        {!catalogLoading && countryTabs.length === 0 && (
          <p className="flex items-center gap-2 rounded-[12px] border border-border bg-surface px-4 py-3 text-[13px] text-foreground-secondary" data-testid="no-statutory-forms">
            <Info size={15} className="shrink-0 text-info" />
            No statutory forms configured for {selectedName} yet. Its payroll register and bank transfer files are below.
          </p>
        )}
      </div>

      {activeCountryTab && (
        <p className="text-[13px] font-semibold text-foreground">
          {selectedName} <span className="text-foreground-muted font-medium">· {activeCountryTab.title} · amounts in {currencyOf(selectedCountry)}</span>
        </p>
      )}

      {activeTab === PAYROLL_REPORTS_TAB.id && (
        <div className="space-y-6">
          {latestReport && visibleCountries(latestReport).length > 0 && (
            <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]" data-testid="latest-run-by-country">
              <p className="mb-3 text-[13px] font-bold text-foreground">
                {latestReport.period || "Latest run"} <span className="font-medium text-foreground-muted">· by country, each in its own currency</span>
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {visibleCountries(latestReport).map((c) => (
                  <div key={c.country} className="rounded-[14px] border border-border bg-background p-4">
                    <div className="flex items-center justify-between">
                      <p className="text-[14px] font-bold text-foreground">{countryLabel(c.country)} <span className="text-[11px] font-medium text-foreground-muted">{c.currency}</span></p>
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
            ) : scopedReports.length === 0 ? (
              <div className="text-center py-16">
                <BarChart3 size={40} className="mx-auto mb-3 text-foreground-muted" />
                <p className="text-[15px] font-bold text-foreground">No reports yet{scopeAll ? "" : ` for ${selectedName}`}</p>
                <p className="text-[13px] text-foreground-muted mt-1">Payroll registers and bank files appear here once payroll runs are completed</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
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
                    {scopedReports.map((r, i) => {
                      // A scoped view offers only the selected country's bank file.
                      const bankCountries = scopeAll ? (bankFileCountries[r.id] || r.countries || []) : visibleCountries(r);
                      return (
                        <tr key={r.id || i} className="hover:bg-background dark:hover:bg-surface-muted transition-colors duration-150">
                          <td className="px-5 py-4 font-semibold text-foreground">{r.name || "Payroll Report"}</td>
                          <td className="px-5 py-4 text-[13px] text-foreground-muted">{r.period || "-"}</td>
                          <td className="px-5 py-4">
                            <div className="flex flex-wrap gap-1.5">
                              {visibleCountries(r).length === 0 ? <span className="text-[12px] text-foreground-muted">-</span> : visibleCountries(r).map((c) => (
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
                              title="Download the payroll register for this run"
                              className="flex items-center gap-1.5 rounded-[12px] bg-primary text-white px-3.5 py-2 text-[13px] font-bold hover:bg-primary-hover transition-all duration-200 shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Download size={12} /> {downloadingId === r.id ? "Downloading..." : "Register"}
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
                                {bankCountries.length > 1 || (!scopeAll && bankCountries.length === 1 && (r.countries || []).length > 1) ? (
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    {bankCountries.map((c) => (
                                      <button
                                        key={c.country}
                                        onClick={() => handleDownloadBankFile(r, c.country)}
                                        disabled={downloadingBankFileId === `${r.id}:${c.country}`}
                                        title={`Generate and download this run's ${countryLabel(c.country)} bank transfer file (${c.currency})`}
                                        className="flex items-center gap-1.5 rounded-[12px] bg-category-teal text-white px-3 py-2 text-[12px] font-bold hover:bg-category-teal transition-all duration-200 shadow-[0_2px_8px_rgba(157,123,242,0.3)] disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                                      >
                                        <Banknote size={12} /> {downloadingBankFileId === `${r.id}:${c.country}` ? "Generating..." : countryLabel(c.country)}
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
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {activeCountryTab?.form && (
        <div className="space-y-6">
          <StatutoryFormPanel
            key={`${selectedCountry}:${activeCountryTab.id}`}
            form={activeCountryTab.form}
            country={selectedCountry}
            countryName={selectedName}
            runs={runs}
            onGenerated={onGenerated}
          />
          {latestGenerated && <GeneratedReportPreview report={latestGenerated} currencyCode={currencyOf(selectedCountry) || currencyCode} />}
        </div>
      )}
      {activeCountryTab?.builtin && BUILTIN_PANELS[activeCountryTab.id]?.()}

      {activeTab === "generate-report" && (
        <div className="space-y-6">
          <ReportGenerationPanel onGenerated={onGenerated} />
          {latestGenerated && <GeneratedReportPreview report={latestGenerated} currencyCode={currencyOf(latestGenerated.jurisdictionCountry) || currencyCode} />}
        </div>
      )}

      {activeTab === "report-history" && (
        <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
          <GeneratedReportsHistoryTable
            refreshKey={historyRefreshKey}
            country={scopeAll ? undefined : selectedCountry}
            onDownloaded={(report) => recordDownload([toEmployeeCountryCode(report.jurisdictionCountry || selectedCountry)])}
            onView={(report) => { setLatestGenerated(report); setActiveTab("generate-report"); }}
          />
        </div>
      )}
    </div>
  );
}

function TabButton({ tab, active, onClick, small = false }) {
  const Icon = tab.icon;
  return (
    <button
      type="button"
      onClick={onClick}
      title={tab.title || tab.label}
      aria-pressed={active}
      className={`flex items-center gap-1.5 ${small ? "px-3.5" : "px-4"} py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
        active ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
      }`}
    >
      {Icon && <Icon size={small ? 14 : 15} />}
      {tab.label}
    </button>
  );
}
