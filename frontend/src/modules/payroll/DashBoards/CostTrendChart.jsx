import { useState, useEffect } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Loader2 } from "lucide-react";
import { getDashboardTrend } from "../../../service/payrollService";
import { formatCompactCurrency, formatCurrency } from "../../../utils/currency";

// Tooltip: the exact amount, locale-grouped (₹1,00,000.00). Axis ticks: the
// compact form — lakh/crore for INR, K/M elsewhere (formatCompactCurrency).
const fmt = (n, currencyCode) => formatCurrency(Number(n || 0), currencyCode);

// A "nice" axis ceiling (1/2/2.5/5 x 10^n) above the data, so ticks read
// cleanly in any currency.
function niceCeiling(max) {
  if (max <= 0) return 1000;
  const target = max * 1.1;
  const pow = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * pow >= target);
  return step * pow;
}

function ChartTooltip({ active, payload, label, currencyCode }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-[14px] border border-border bg-surface-muted px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2 text-[13px] font-semibold" style={{ color: p.color }}>
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          {p.name}: {fmt(p.value, currencyCode)}
        </p>
      ))}
    </div>
  );
}

function PillToggle({ options, value, onChange }) {
  return (
    <div className="flex gap-0.5 rounded-[12px] bg-surface-muted p-1">
      {options.map((opt) => (
        <button
          key={opt.id}
          onClick={() => onChange(opt.id)}
          className={`rounded-[10px] px-4 py-1.5 text-[11px] font-bold transition-all duration-200 ${
            value === opt.id
              ? "bg-surface text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
              : "text-foreground-muted hover:text-foreground"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function EmptyState({ message }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-foreground-muted">
      <div className="mb-3 h-10 w-10 rounded-full bg-surface-muted flex items-center justify-center">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 3v18h18" />
          <path d="M18 17V9" />
          <path d="M13 17V5" />
          <path d="M8 17v-3" />
        </svg>
      </div>
      <p className="text-[13px] font-medium">{message}</p>
    </div>
  );
}

function buildJanToCurrentData(rawData) {
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth();
  const result = [];

  for (let m = 0; m <= currentMonth; m++) {
    const label = `${monthNames[m]} ${currentYear}`;
    const existing = (rawData || []).find((d) => d.month === label);
    result.push(existing || { month: label, gross: 0, net: 0 });
  }

  return result;
}

// Always ONE currency: `country` asks the trend endpoint for that country's
// payslips only (points come back with their `currency`); without it the org
// is single-currency and `currencyCode` names it. `scopeNote` says which
// country a multi-currency org is looking at.
export default function CostTrendChart({ refreshTick, currencyCode: viewCurrencyCode, country = null, scopeNote = "" }) {
  const [series, setSeries] = useState("both");
  const [trendData, setTrendData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [serverCurrency, setServerCurrency] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const now = new Date();
        const currentMonth = now.getMonth() + 1;
        const currentYear = now.getFullYear();
        const res = await getDashboardTrend({ months: currentMonth, year: currentYear, month: currentMonth, country: country || undefined });
        if (!cancelled) {
          const rawData = Array.isArray(res) ? res : [];
          setTrendData(buildJanToCurrentData(rawData));
          setServerCurrency(rawData.find((d) => d.currency)?.currency || null);
        }
      } catch {
        if (!cancelled) setTrendData([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [refreshTick, country]);

  const currencyCode = serverCurrency || viewCurrencyCode || null;
  const showGross = series === "gross" || series === "both";
  const showNet = series === "net" || series === "both";

  const GROSS_COLOR = "var(--color-primary)";
  const NET_COLOR = "var(--color-category-teal)";

  // Fixed Y-axis ceiling computed from BOTH datasets, regardless of which
  // toggle is active — otherwise recharts auto-scales the axis to only the
  // currently-rendered series, making the smaller value (Net) appear to
  // reach higher up the chart than Gross when toggled individually.
  const allValues = trendData.flatMap((d) => [Number(d.gross) || 0, Number(d.net) || 0]);
  const rawMax = Math.max(0, ...allValues);
  const yAxisMax = niceCeiling(rawMax);

  return (
    <div className="rounded-[18px] border border-border bg-surface p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h3 className="text-[15px] font-bold text-foreground">
            Payroll Cost Trend
          </h3>
          <p className="mt-0.5 text-[12px] font-medium text-foreground-muted" data-testid="trend-currency">
            {currencyCode ? `Amounts in ${currencyCode}` : "Currency not set"}{scopeNote ? ` · ${scopeNote}` : ""}
          </p>
        </div>
        <PillToggle
          options={[
            { id: "gross", label: "Gross" },
            { id: "net", label: "Net" },
            { id: "both", label: "Both" },
          ]}
          value={series}
          onChange={setSeries}
        />
      </div>


      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 size={22} className="animate-spin text-primary" />
        </div>
      ) : trendData.length === 0 ? (
        <EmptyState message="No payroll trend data yet. Complete a payroll run to see trends." />
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={trendData} margin={{ top: 10, right: 20, left: 12, bottom: 0 }}>
            <defs>
              <linearGradient id="gradGross" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={GROSS_COLOR} stopOpacity={0.15} />
                <stop offset="100%" stopColor={GROSS_COLOR} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gradNet" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={NET_COLOR} stopOpacity={0.15} />
                <stop offset="100%" stopColor={NET_COLOR} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: "var(--color-foreground-muted)", fontWeight: 500 }}
              axisLine={{ stroke: "var(--color-border)" }}
              tickLine={false}
              dy={8}
            />
            <YAxis
              domain={[0, yAxisMax]}
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "var(--color-foreground-muted)", fontWeight: 500 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => formatCompactCurrency(v, currencyCode)}
              width={70}
              label={currencyCode ? {
                value: `Amount (${currencyCode})`, angle: -90, position: "insideLeft", offset: -4,
                style: { fontSize: 11, fill: "var(--color-foreground-muted)", fontWeight: 600, textAnchor: "middle" },
              } : undefined}
            />
            <Tooltip content={<ChartTooltip currencyCode={currencyCode} />} />
            {showGross && (
              <Area
                type="monotone"
                dataKey="gross"
                name="Gross"
                stroke={GROSS_COLOR}
                strokeWidth={3}
                fill="url(#gradGross)"
                dot={{ r: 5, fill: GROSS_COLOR, strokeWidth: 3, stroke: "#fff" }}
                activeDot={{ r: 7, strokeWidth: 3, stroke: "#fff", fill: GROSS_COLOR }}
              />
            )}
            {showNet && (
              <Area
                type="monotone"
                dataKey="net"
                name="Net"
                stroke={NET_COLOR}
                strokeWidth={2.5}
                strokeDasharray="7 4"
                fill="url(#gradNet)"
                dot={{ r: 3.5, fill: NET_COLOR, strokeWidth: 2, stroke: "#fff" }}
                activeDot={{ r: 6, strokeWidth: 2, stroke: "#fff", fill: NET_COLOR }}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
