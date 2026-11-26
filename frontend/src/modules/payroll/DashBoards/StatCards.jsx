import { useState, useEffect } from "react";
import { Wallet, Users, Receipt, Building2, TrendingUp, Minus, TrendingDown } from "lucide-react";
import { getDashboardSummary } from "../../../service/payrollService";
import { formatCurrency, getCountryNameFromCode, getCurrencyForJurisdiction } from "../../../utils/currency";
import CountryTotalsTable from "../../../components/payroll/CountryTotalsTable";

// Per-country breakdown columns (summary.byCountry) for an org paying
// employees in more than one country — each row in its own currency.
const BY_COUNTRY_COLUMNS = [
  { key: "payslips", label: "Payslips" },
  { key: "totalGross", label: "Gross", money: true },
  { key: "totalTaxes", label: "Taxes", money: true, accent: "text-error" },
  { key: "totalNet", label: "Net", money: true, accent: "text-primary" },
];

const countryName = (code) => getCountryNameFromCode(code) || code;
const deductionsOf = (row) => (Number(row?.totalTaxes) || 0) + (Number(row?.totalAttendanceDeduction) || 0);

// One money value per country, each in its own currency — never summed.
function PerCountryValue({ rows, pick }) {
  return (
    <span className="block space-y-1">
      {rows.map((r) => (
        <span key={r.country} className="flex items-baseline justify-between gap-3 text-[15px] font-bold tracking-normal">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground-muted">{countryName(r.country)}</span>
          <span>{formatCurrency(pick(r), r.currency)}</span>
        </span>
      ))}
    </span>
  );
}

// country: "ALL" or one payroll country code. primaryCurrency: the org's own
// currency (server-resolved summary.currency wins once loaded).
export default function StatCards({ filter, refreshTick, country = "ALL", primaryCurrency, onSummary }) {
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

  // Lets the dashboard know the primary currency + whether this period mixes
  // currencies, so the trend chart picks a single-currency view.
  useEffect(() => {
    if (data) onSummary?.({
      currency: data.currency || null,
      defaultCountry: data.defaultCountry || null,
      mixedCurrencies: Boolean(data.mixedCurrencies) || (data.byCountry?.length || 0) > 1,
    });
  }, [data, onSummary]);

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

  const byCountry = data?.byCountry || [];
  const orgCurrency = data?.currency || primaryCurrency || null;
  const singleCountry = country !== "ALL";
  // One country selected: that country's own totals in its own currency (a
  // country with no payslips this period shows zeros in its currency).
  const countryRow = singleCountry
    ? byCountry.find((r) => r.country === country) || {
      country, totalGross: 0, totalNet: 0, totalTaxes: 0, totalAttendanceDeduction: 0,
      currency: country === data?.defaultCountry ? orgCurrency : getCurrencyForJurisdiction(country)?.code || null,
    }
    : null;
  // "All" with several currencies: per-country values, never a blind sum.
  const perCountry = !singleCountry && byCountry.length > 1;
  const viewCurrency = singleCountry ? countryRow.currency : (byCountry[0]?.currency || orgCurrency);
  const money = (pick, combined) => {
    if (data?.unavailable) return "—";
    if (perCountry) return <PerCountryValue rows={byCountry} pick={pick} />;
    return formatCurrency(singleCountry ? pick(countryRow) : combined, viewCurrency);
  };

  // Month-on-month change is only meaningful for one currency.
  const changePct = perCountry || singleCountry ? null : data?.totalPayrollCostChangePct;
  const isUp = changePct != null && changePct > 0;
  const isStable = changePct == null || changePct === 0;
  const attendanceDed = singleCountry ? Number(countryRow.totalAttendanceDeduction) || 0 : Number(data?.totalAttendanceDeduction) || 0;
  const periodWord = isAllTime ? "All Time" : "This Month";
  const scopeNote = singleCountry
    ? `${countryName(country)} · ${viewCurrency || "currency not set"}`
    : perCountry ? "Each country in its own currency" : viewCurrency ? `In ${viewCurrency}` : "";

  const cards = [
    {
      key: "total",
      icon: Wallet,
      label: isAllTime ? "Total Payroll (All Time)" : "Total Payroll (Net)",
      value: money((r) => r.totalNet, data?.totalNet ?? data?.totalPayrollCost),
      indicator: data?.unavailable ? "Figures could not be loaded" : changePct != null
        ? `${isUp ? "+" : ""}${changePct}% vs last month` : scopeNote || "No prior data",
      indicatorColor: isStable ? "text-foreground-muted" : isUp ? "text-primary" : "text-error",
      iconBg: "bg-primary/10",
      iconColor: "text-primary",
      trendIcon: isStable ? Minus : isUp ? TrendingUp : TrendingDown,
    },
    {
      key: "employees",
      icon: Users,
      label: "Active Employees",
      value: String(data?.activeCount ?? 0),
      indicator: `${data?.headcount ?? 0} total · ${data?.onLeaveCount ?? 0} on leave`,
      indicatorColor: "text-foreground-muted",
      iconBg: "bg-info/10",
      iconColor: "text-info",
      trendIcon: Minus,
    },
    {
      key: "deduction",
      icon: Receipt,
      label: `Deduction (${periodWord})`,
      value: money(deductionsOf, (Number(data?.totalTaxes) || 0) + (Number(data?.totalAttendanceDeduction) || 0)),
      indicator: attendanceDed > 0 && !perCountry
        ? `${formatCurrency(attendanceDed, viewCurrency)} attendance`
        : `${data?.pendingApprovals ?? 0} runs pending approval`,
      indicatorColor: attendanceDed > 0 && !perCountry ? "text-error" : "text-warning",
      iconBg: "bg-error/10",
      iconColor: "text-error",
      trendIcon: Minus,
    },
    {
      key: "gross",
      icon: Building2,
      label: `Gross Pay (${periodWord})`,
      value: money((r) => r.totalGross, data?.totalGross),
      indicator: perCountry ? "Not added together across currencies" : "Before deductions",
      indicatorColor: "text-foreground-muted",
      iconBg: "bg-category-teal/10",
      iconColor: "text-category-teal",
      trendIcon: Minus,
    },
  ];

  const cardGrid = (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4" data-testid="dashboard-stat-cards">
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
            <div className="mt-4 text-[26px] font-extrabold tracking-tight text-foreground">
              {card.value}
            </div>
            <p className={`mt-2 flex items-center gap-1.5 text-[12px] font-semibold ${card.indicatorColor}`}>
              <TrendIcon size={13} strokeWidth={2.5} />
              {card.indicator.replace(/^[+↑—]\s*/, "")}
            </p>
          </div>
        );
      })}
    </div>
  );

  if (!perCountry) return cardGrid;

  return (
    <div className="space-y-5">
      {cardGrid}
      <div className="rounded-[18px] border border-border bg-surface p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
          {isAllTime ? "Payroll by Country (All Time)" : "Payroll by Country (This Month)"}
        </p>
        <p className="mt-1 mb-3 text-[12px] text-foreground-muted">
          Employees are paid in {byCountry.length} countries — each total is in that country&apos;s own currency and they
          are not added together (no combined total is shown: Zoiko Payroll has no exchange-rate source to convert them).
        </p>
        <CountryTotalsTable rows={byCountry} columns={BY_COUNTRY_COLUMNS} />
      </div>
    </div>
  );
}
