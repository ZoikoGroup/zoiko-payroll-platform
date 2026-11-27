import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus, ChevronLeft, ChevronRight } from "lucide-react";
import StatCards from "./StatCards";
import CostTrendChart from "./CostTrendChart";
import BreakdownsChart from "./BreakdownsChart";
import RecentActivity from "./RecentActivity";
import TrialProgressBar from "./TrialProgressBar";
import { CALCULATION_MODE_LABELS } from "../../../service/payrollService";
import { usePayrollSetup } from "../PayrollSetupContext";
import { useEntitledCountries } from "../EntitledCountriesContext";
import { getCountryNameFromCode, getCurrencyForJurisdiction } from "../../../utils/currency";
import CountrySelect from "../../../components/jurisdiction/CountrySelect";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const POLL_INTERVAL_MS = 30000;

function getInitialMonth() {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

function navigateMonth(current, direction) {
  let { year, month } = current;
  if (direction === "prev") {
    month -= 1;
    if (month < 1) { month = 12; year -= 1; }
  } else {
    month += 1;
    if (month > 12) { month = 1; year += 1; }
  }
  return { year, month };
}

export default function DashboardPage({ onNewPayrollRun }) {
  const [filter, setFilter] = useState(getInitialMonth);
  const [allMonths, setAllMonths] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  // Shared across the whole Payroll module — fetched once per session
  // instead of every sub-module (this Dashboard, Employees, Payroll Runs,
  // Reports, Payslips) independently calling getCompanyProfile()/
  // getActivePolicy() on its own mount. Also handles the focus-refresh that
  // used to be duplicated per-page here.
  const { currencyCode, calculationMode } = usePayrollSetup();
  const entitlement = useEntitledCountries();
  // Server-resolved primary currency (Organization.currency override
  // included) + whether the period mixes currencies — from the summary.
  const [summaryMeta, setSummaryMeta] = useState({ currency: null, defaultCountry: null, mixedCurrencies: false });
  const onSummary = useCallback((meta) => setSummaryMeta(meta), []);

  // Country filter: "ALL" or one active payroll country, kept in ?country=.
  const [searchParams, setSearchParams] = useSearchParams();
  const activeCountries = useMemo(
    () => (entitlement.loaded ? entitlement.entitledEmployeeCodes : []),
    [entitlement.loaded, entitlement.entitledEmployeeCodes],
  );
  const primaryCountry = summaryMeta.defaultCountry || entitlement.primaryEmployeeCode || activeCountries[0] || null;
  const countryParam = (searchParams.get("country") || "").toUpperCase();
  const country = activeCountries.includes(countryParam) ? countryParam : "ALL";
  const setCountry = (code) => setSearchParams((prev) => {
    const next = new URLSearchParams(prev);
    if (code === "ALL") next.delete("country"); else next.set("country", code);
    return next;
  }, { replace: true });

  const multiCountry = activeCountries.length > 1 || summaryMeta.mixedCurrencies;
  // The org's own currency: the server's answer, else the compliance
  // country's, else the primary country's — never a hardcoded USD.
  const primaryCurrency = summaryMeta.currency || currencyCode
    || (primaryCountry ? getCurrencyForJurisdiction(primaryCountry)?.code : null) || null;
  const currencyFor = (code) => (code === primaryCountry ? primaryCurrency : getCurrencyForJurisdiction(code)?.code || null);
  // One currency per view: a selected country uses its own; "All" uses the
  // org's currency when it pays in one country, and otherwise charts the
  // primary country (amounts in different currencies are never added up).
  const viewCurrency = country !== "ALL" ? currencyFor(country) : multiCountry ? null : primaryCurrency;
  const trendCountry = country !== "ALL" ? country : multiCountry ? primaryCountry : null;
  const trendCurrency = country !== "ALL" ? currencyFor(country) : primaryCurrency;
  const trendNote = country === "ALL" && multiCountry && primaryCountry
    ? `${getCountryNameFromCode(primaryCountry) || primaryCountry} (primary) — currencies are never added together; pick a country to see its trend`
    : country !== "ALL" ? getCountryNameFromCode(country) || country : "";

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") setRefreshTick((t) => t + 1);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const effectiveFilter = allMonths ? {} : filter;
  const monthLabel = allMonths ? "All months" : `${MONTHS[filter.month - 1]} ${filter.year}`;
  const isCurrentMonth = allMonths ? false : (() => {
    const now = new Date();
    return filter.year === now.getFullYear() && filter.month === now.getMonth() + 1;
  })();

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-[1480px] space-y-6 px-4 py-6 sm:space-y-8 sm:px-6 sm:py-8 lg:px-10">
        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-foreground">
              Payroll Dashboard
            </h1>
            <p className="mt-1.5 text-[13px] font-medium text-foreground-muted">
              Overview for {monthLabel}
              <span className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${
                calculationMode === "simple"
                  ? "bg-warning/10 text-warning"
                  : "bg-primary/10 text-primary"
              }`}>
                {CALCULATION_MODE_LABELS[calculationMode] || "Standard Payroll"}
              </span>
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Month Navigator */}
            <div className="inline-flex items-center gap-0.5 rounded-[14px] border border-border bg-surface px-1.5 py-1.5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <button
                onClick={() => { setAllMonths(false); setFilter((f) => navigateMonth(f, "prev")); }}
                disabled={allMonths}
                className="rounded-[10px] p-1.5 text-foreground-muted hover:text-foreground hover:bg-surface-muted transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={16} strokeWidth={2} />
              </button>
              <span className="px-3 text-[13px] font-semibold text-foreground min-w-[140px] text-center select-none">
                {monthLabel}
              </span>
              <button
                onClick={() => { setAllMonths(false); setFilter((f) => navigateMonth(f, "next")); }}
                disabled={allMonths}
                className="rounded-[10px] p-1.5 text-foreground-muted hover:text-foreground hover:bg-surface-muted transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronRight size={16} strokeWidth={2} />
              </button>
              {!allMonths && !isCurrentMonth && (
                <button
                  onClick={() => setFilter(getInitialMonth())}
                  className="ml-1 rounded-[10px] px-3 py-1 text-[11px] font-bold text-primary hover:bg-primary/10 transition-all duration-200 whitespace-nowrap"
                >
                  Today
                </button>
              )}
            </div>

            {/* Country filter — each country's totals in its own currency */}
            {activeCountries.length > 0 && (
              <CountrySelect
                value={country}
                onChange={setCountry}
                ariaLabel="Country"
                testId="dashboard-country-filter"
                className="w-56"
                buttonClassName="h-9! rounded-[12px] bg-surface text-[13px] font-semibold shadow-[0_1px_3px_rgba(0,0,0,0.04)]"
                options={[
                  { value: "ALL", label: "All countries" },
                  ...activeCountries.map((code) => ({
                    value: code, code, label: getCountryNameFromCode(code) || code, hint: currencyFor(code) || undefined,
                  })),
                ]}
              />
            )}

            <button
              onClick={() => setAllMonths((v) => !v)}
              aria-pressed={allMonths}
              title="Show every month instead of one"
              className={`inline-flex items-center rounded-[12px] px-4 py-2 text-[13px] font-bold transition-all duration-200 shadow-[0_1px_3px_rgba(0,0,0,0.04)] ${
                allMonths
                  ? "bg-primary text-white shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
                  : "border border-border bg-surface text-foreground-muted hover:text-primary hover:border-primary"
              }`}
            >
              All months
            </button>

            <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3.5 py-1.5 text-[11px] font-semibold text-foreground-muted shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
              </span>
              Live Data
            </span>

            <button
              onClick={onNewPayrollRun}
              className="inline-flex items-center gap-2 rounded-[12px] bg-primary px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] active:translate-y-0"
            >
              <Plus size={16} strokeWidth={2.5} />
              New Payroll Run
            </button>
          </div>
        </div>

        {/* Trial progress (evaluation workspaces only) */}
        <TrialProgressBar />

        {/* Stat Cards */}
        <StatCards filter={effectiveFilter} refreshTick={refreshTick} calculationMode={calculationMode} country={country} primaryCurrency={primaryCurrency} onSummary={onSummary} />

        {/* Trend Chart — always Jan → current month, always one currency */}
        <CostTrendChart refreshTick={refreshTick} calculationMode={calculationMode} country={trendCountry} currencyCode={trendCurrency} scopeNote={trendNote} />

        {/* Breakdowns: Department Donut + Pay Type Bar + Deductions (org-wide) */}
        <BreakdownsChart filter={effectiveFilter} refreshTick={refreshTick} calculationMode={calculationMode} currencyCode={primaryCurrency} mixedCurrencies={multiCountry} />

        {/* Recent Activity — each run shows its own per-country currencies */}
        <RecentActivity filter={effectiveFilter} refreshTick={refreshTick} currencyCode={viewCurrency || primaryCurrency} />
      </div>
    </div>
  );
}
