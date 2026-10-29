import { useState, useEffect } from "react";
import { Wallet, Users, Receipt, Building2, TrendingUp, Minus, TrendingDown } from "lucide-react";
import { getDashboardSummary } from "../../../service/payrollService";
import { formatCurrency } from "../../../utils/currency";
import CountryTotalsTable from "../../../components/payroll/CountryTotalsTable";

// Per-country breakdown columns (summary.byCountry) for an org paying
// employees in more than one country — each row in its own currency.
const BY_COUNTRY_COLUMNS = [
  { key: "payslips", label: "Payslips" },
  { key: "totalGross", label: "Gross", money: true },
  { key: "totalTaxes", label: "Taxes", money: true, accent: "text-error" },
  { key: "totalNet", label: "Net", money: true, accent: "text-primary" },
];
const MULTI_CURRENCY_LABEL = "Multiple currencies";

function fmtCurrency(n, currencyCode) {
  if (n == null) return formatCurrency(0, currencyCode);
  const v = Number(n);
  return formatCurrency(v, currencyCode);
}

export default function StatCards({ filter, refreshTick, currencyCode, onMixedCurrenciesChange }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const isAllTime = !filter?.year && !filter?.month;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getDashboardSummary(filter);
        if (!cancelled) setData(res);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [filter?.year, filter?.month, refreshTick]);

  // Tells the dashboard whether this summary spans several currencies, so the
  // trend/breakdown charts (cross-currency sums) can say so.
  const spansCurrencies = (data?.byCountry?.length || 0) > 1;
  useEffect(() => {
    onMixedCurrenciesChange?.(spansCurrencies);
  }, [spansCurrencies, onMixedCurrenciesChange]);

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="rounded-[18px] border border-border bg-surface p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] animate-pulse">
            <div className="h-3 w-20 rounded-md bg-surface-muted" />
            <div className="mt-4 h-8 w-28 rounded-md bg-surface-muted" />
            <div className="mt-2.5 h-3 w-24 rounded-md bg-surface-muted" />
          </div>
        ))}
      </div>
    );
  }

  // The top-level money totals add every country's currency together, so
  // with more than one country they're replaced by the by-country table.
  const byCountry = data?.byCountry || [];
  const isMultiCountry = byCountry.length > 1;
  const changePct = isMultiCountry ? null : data?.totalPayrollCostChangePct;
  const isUp = changePct != null && changePct > 0;
  const isDown = changePct != null && changePct < 0;
  const isStable = changePct == null || changePct === 0;

  const totalDeductions = (Number(data?.totalTaxes) || 0) + (Number(data?.totalAttendanceDeduction) || 0);
  const attendanceDed = Number(data?.totalAttendanceDeduction) || 0;

  const cards = [
    {
      key: "total",
      icon: Wallet,
      label: isAllTime ? "Total Payroll (All Time)" : "Total Payroll (Net)",
      value: isMultiCountry ? MULTI_CURRENCY_LABEL : fmtCurrency(data?.totalNet ?? data?.totalPayrollCost, currencyCode),
      indicator: isMultiCountry
        ? "See totals by country below"
        : changePct != null ? `${isUp ? "+" : ""}${changePct}% vs last month` : "No prior data",
      indicatorColor: isStable
        ? "text-foreground-muted"
        : isUp
          ? "text-primary"
          : "text-error",
      iconBg: "bg-primary/10",
      iconColor: "text-primary",
      trendIcon: isStable ? Minus : isUp ? TrendingUp : TrendingDown,
    },
    {
      key: "employees",
      icon: Users,
      label: "Active Employees",
      value: String(data?.activeCount ?? 0),
      indicator: `${data?.headcount ?? 0} total \u00b7 ${data?.onLeaveCount ?? 0} on leave`,
      indicatorColor: "text-foreground-muted",
      iconBg: "bg-info/10",
      iconColor: "text-info",
      trendIcon: Minus,
    },
    {
      key: "deduction",
      icon: Receipt,
      label: isAllTime ? "Deduction (All Time)" : "Deduction (This Month)",
      value: isMultiCountry ? MULTI_CURRENCY_LABEL : fmtCurrency(totalDeductions, currencyCode),
      indicator: attendanceDed > 0 && !isMultiCountry
        ? `${fmtCurrency(attendanceDed, currencyCode)} attendance`
        : `${data?.pendingApprovals ?? 0} runs pending approval`,
      indicatorColor: attendanceDed > 0 && !isMultiCountry ? "text-error" : "text-warning",
      iconBg: "bg-error/10",
      iconColor: "text-error",
      trendIcon: Minus,
    },
    {
      key: "gross",
      icon: Building2,
      label: isAllTime ? "Gross Pay (All Time)" : "Gross Pay (This Month)",
      value: isMultiCountry ? MULTI_CURRENCY_LABEL : fmtCurrency(data?.totalGross, currencyCode),
      indicator: isMultiCountry ? "See totals by country below" : "Before deductions",
      indicatorColor: "text-foreground-muted",
      iconBg: "bg-category-teal/10",
      iconColor: "text-category-teal",
      trendIcon: Minus,
    },
  ];

  const cardGrid = (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        const TrendIcon = card.trendIcon;
        return (
          <div
            key={card.key}
            className="group rounded-[18px] border border-border bg-surface p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] dark:hover:shadow-[0_8px_24px_rgba(0,0,0,0.2)] hover:-translate-y-0.5"
          >
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                {card.label}
              </p>
              <div className={`flex h-10 w-10 items-center justify-center rounded-[12px] ${card.iconBg} transition-transform duration-200 group-hover:scale-110`}>
                <Icon size={18} className={card.iconColor} strokeWidth={2} />
              </div>
            </div>
            <p className="mt-4 text-[26px] font-extrabold tracking-tight text-foreground">
              {card.value}
            </p>
            <p className={`mt-2 flex items-center gap-1.5 text-[12px] font-semibold ${card.indicatorColor}`}>
              <TrendIcon size={13} strokeWidth={2.5} />
              {card.indicator.replace(/^[+\u2191\u2014]\s*/, "")}
            </p>
          </div>
        );
      })}
    </div>
  );

  if (!isMultiCountry) return cardGrid;

  return (
    <div className="space-y-5">
      {cardGrid}
      <div className="rounded-[18px] border border-border bg-surface p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          {isAllTime ? "Payroll by Country (All Time)" : "Payroll by Country (This Month)"}
        </p>
        <p className="mt-1 mb-3 text-[12px] text-foreground-muted">
          Employees are paid in {byCountry.length} countries — each total is in that country&apos;s own currency and they are not added together.
        </p>
        <CountryTotalsTable rows={byCountry} columns={BY_COUNTRY_COLUMNS} />
      </div>
    </div>
  );
}
