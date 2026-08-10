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
import { getCurrencySymbol } from "../../../utils/currency";

// Lakh/Crore abbreviations are an India-specific numbering convention \u2014
// kept exactly as-is for INR, but every other currency uses the more
// universal K/M (thousand/million) abbreviation instead.
function fmt(n, currencyCode) {
  const v = Number(n || 0);
  const symbol = getCurrencySymbol(currencyCode);
  if (currencyCode === "INR") {
    if (v >= 10000000) return `${symbol} ${(v / 10000000).toFixed(1)}Cr`;
    if (v >= 100000) return `${symbol} ${(v / 100000).toFixed(1)}L`;
    if (v >= 1000) return `${symbol} ${(v / 1000).toFixed(0)}K`;
    return `${symbol} ${v.toLocaleString("en-IN")}`;
  }
  if (v >= 1000000) return `${symbol}${(v / 1000000).toFixed(1)}M`;
  if (v >= 1000) return `${symbol}${(v / 1000).toFixed(0)}K`;
  return `${symbol}${v.toLocaleString()}`;
}

function ChartTooltip({ active, payload, label, currencyCode }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-[14px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-[#9E9690]">{label}</p>
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
    <div className="flex gap-0.5 rounded-[12px] bg-[#F0EDE8] dark:bg-[#38312D] p-1">
      {options.map((opt) => (
        <button
          key={opt.id}
          onClick={() => onChange(opt.id)}
          className={`rounded-[10px] px-4 py-1.5 text-[11px] font-bold transition-all duration-200 ${
            value === opt.id
              ? "bg-white dark:bg-[#221D1A] text-[#1A1816] dark:text-[#F0EDE8] shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
              : "text-[#9E9690] hover:text-[#1A1816] dark:hover:text-[#F0EDE8]"
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
    <div className="flex flex-col items-center justify-center py-20 text-[#9E9690]">
      <div className="mb-3 h-10 w-10 rounded-full bg-[#F0EDE8] dark:bg-[#38312D] flex items-center justify-center">
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

export default function CostTrendChart({ refreshTick, currencyCode }) {
  const [series, setSeries] = useState("both");
  const [trendData, setTrendData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const now = new Date();
        const currentMonth = now.getMonth() + 1;
        const currentYear = now.getFullYear();
        const res = await getDashboardTrend({ months: currentMonth, year: currentYear, month: currentMonth });
        if (!cancelled) {
          const rawData = Array.isArray(res) ? res : [];
          setTrendData(buildJanToCurrentData(rawData));
        }
      } catch {
        if (!cancelled) setTrendData([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [refreshTick]);

  const showGross = series === "gross" || series === "both";
  const showNet = series === "net" || series === "both";

  const GROSS_COLOR = "#19C58A";
  const NET_COLOR = "#35B6F5";

  // Fixed Y-axis ceiling computed from BOTH datasets, regardless of which
  // toggle is active — otherwise recharts auto-scales the axis to only the
  // currently-rendered series, making the smaller value (Net) appear to
  // reach higher up the chart than Gross when toggled individually.
  const allValues = trendData.flatMap((d) => [Number(d.gross) || 0, Number(d.net) || 0]);
  const rawMax = Math.max(0, ...allValues);
  const yAxisMax = rawMax === 0 ? 1000 : Math.ceil((rawMax * 1.1) / 50000) * 50000;

  return (
    <div className="rounded-[18px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="mb-6 flex items-center justify-between">
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
          Payroll Cost Trend
        </h3>
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
          <Loader2 size={22} className="animate-spin text-[#19C58A]" />
        </div>
      ) : trendData.length === 0 ? (
        <EmptyState message="No payroll trend data yet. Complete a payroll run to see trends." />
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={trendData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
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
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E0D9" dark={{ stroke: "#38312D" }} vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: "#9E9690", fontWeight: 500 }}
              axisLine={{ stroke: "#E5E0D9" }}
              tickLine={false}
              dy={8}
            />
            <YAxis
              domain={[0, yAxisMax]}
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "#9E9690", fontWeight: 500 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `${getCurrencySymbol(currencyCode)}${(v / 1000).toFixed(0)}k`}
              width={55}
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
