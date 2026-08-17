import { useState, useEffect, useCallback } from "react";
import { Plus, ChevronLeft, ChevronRight } from "lucide-react";
import StatCards from "./StatCards";
import CostTrendChart from "./CostTrendChart";
import BreakdownsChart from "./BreakdownsChart";
import RecentActivity from "./RecentActivity";
import { CALCULATION_MODE_LABELS } from "../../../service/payrollService";
import { usePayrollSetup } from "../PayrollSetupContext";

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

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") setRefreshTick((t) => t + 1);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const effectiveFilter = allMonths ? {} : filter;
  const monthLabel = allMonths ? "All Months" : `${MONTHS[filter.month - 1]} ${filter.year}`;
  const isCurrentMonth = allMonths ? false : (() => {
    const now = new Date();
    return filter.year === now.getFullYear() && filter.month === now.getMonth() + 1;
  })();

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-[1480px] px-8 py-8 lg:px-10 space-y-8">
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

          <div className="flex items-center gap-3">
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

            <button
              onClick={() => setAllMonths((v) => !v)}
              className={`inline-flex items-center rounded-[12px] px-4 py-2 text-[13px] font-bold transition-all duration-200 shadow-[0_1px_3px_rgba(0,0,0,0.04)] ${
                allMonths
                  ? "bg-primary text-white shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
                  : "border border-border bg-surface text-foreground-muted hover:text-primary hover:border-primary"
              }`}
            >
              All
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

        {/* Stat Cards */}
        <StatCards filter={effectiveFilter} refreshTick={refreshTick} calculationMode={calculationMode} currencyCode={currencyCode} />

        {/* Trend Chart — always Jan → current month */}
        <CostTrendChart refreshTick={refreshTick} calculationMode={calculationMode} currencyCode={currencyCode} />

        {/* Breakdowns: Department Donut + Pay Type Bar + Deductions */}
        <BreakdownsChart filter={effectiveFilter} refreshTick={refreshTick} calculationMode={calculationMode} currencyCode={currencyCode} />

        {/* Recent Activity */}
        <RecentActivity filter={effectiveFilter} refreshTick={refreshTick} currencyCode={currencyCode} />
      </div>
    </div>
  );
}
