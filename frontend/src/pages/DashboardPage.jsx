import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Building2, Users, ShieldCheck, CreditCard, RefreshCcw, LayoutGrid, Info,
} from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

import { apiFetch } from "../api/client";
import StatusPill from "../components/StatusPill";
import DateRangeFilter from "../components/DateRangeFilter";
import { resolveDateRange } from "../utils/dateRangePresets";
import { getDashboardCharts } from "../service/superAdminService";

const CARDS = [
  { key: "total_organizations", label: "Organizations", icon: Building2 },
  { key: "active_organizations", label: "Active Organizations", icon: Building2 },
  { key: "total_users", label: "Users", icon: Users },
  { key: "super_admins", label: "Super Admins", icon: ShieldCheck },
  { key: "org_admins", label: "Org Admins", icon: Users },
  { key: "payroll_admins", label: "Payroll Admins", icon: Users },
  { key: "total_payroll_employees", label: "Payroll Employees", icon: CreditCard },
  { key: "total_payroll_runs", label: "Payroll Runs", icon: RefreshCcw },
];

const PIE_COLORS = [
  "var(--color-primary)",
  "var(--color-category-teal)",
  "var(--color-success)",
  "var(--color-info)",
  "var(--color-error)",
  "var(--color-warning)",
  "var(--color-brand-cyan)",
];

function CardSkeleton() {
  return (
    <div className="bg-surface rounded-xl shadow-sm p-5 animate-pulse">
      <div className="h-7 w-12 rounded bg-border" />
      <div className="mt-2 h-3 w-24 rounded bg-surface-muted" />
    </div>
  );
}

function ChartCard({ title, note, children, height = 280 }) {
  return (
    <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
      <div className="mb-4 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {note && (
          <span title={note} className="flex items-center gap-1 text-xs text-foreground-disabled">
            <Info size={13} />
          </span>
        )}
      </div>
      <div style={{ height }}>{children}</div>
    </div>
  );
}

function EmptyChart({ message }) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-foreground-disabled">
      {message}
    </div>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface-muted px-3 py-2 text-xs shadow-lg">
      {label && <p className="mb-1 font-semibold text-foreground-muted">{label}</p>}
      {payload.map((p) => (
        <p key={p.dataKey || p.name} className="flex items-center gap-1.5" style={{ color: p.color || p.fill }}>
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color || p.fill }} />
          {p.name}: {typeof p.value === "number" ? p.value.toLocaleString() : p.value}
        </p>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [charts, setCharts] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [dateRange, setDateRange] = useState({ preset: "thisYear", ...resolveDateRange("thisYear") });

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      apiFetch("/api/super-admin/dashboard/stats"),
      getDashboardCharts({ start_date: dateRange.startDate || undefined, end_date: dateRange.endDate || undefined }),
    ])
      .then(([statsRes, chartsRes]) => {
        setStats(statsRes);
        setCharts(chartsRes);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [dateRange]);

  useEffect(() => {
    load();
  }, [load]);

  const orgStatusData = charts
    ? [
        { name: "Active", value: charts.organizationsByStatus?.active || 0 },
        { name: "Inactive", value: charts.organizationsByStatus?.inactive || 0 },
      ]
    : [];
  const orgCountryData = charts?.organizationsByCountry?.map((r) => ({ name: r.country, value: r.count })) || [];
  const complianceByStatus = charts ? Object.entries(charts.complianceOverview?.byStatus || {}).map(([name, value]) => ({ name, value })) : [];

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Dashboard</h1>
          <p className="text-sm text-foreground-muted mt-0.5">Monitor and manage your Zoiko Payroll platform.</p>
        </div>
        <div className="flex items-center gap-2">
          <DateRangeFilter value={dateRange} onChange={setDateRange} />
          <button
            onClick={load}
            disabled={loading}
            title="Refresh stats"
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCcw size={15} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats == null && loading
          ? CARDS.map(({ key }) => <CardSkeleton key={key} />)
          : stats &&
            CARDS.map(({ key, label, icon: Icon }) => (
              <div key={key} className="bg-surface border border-border rounded-xl shadow-sm p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-3xl font-bold text-foreground">{stats[key] ?? 0}</div>
                    <div className="text-xs text-foreground-muted mt-1">{label}</div>
                  </div>
                  <Icon size={20} className="text-primary" />
                </div>
              </div>
            ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-8">
        <ChartCard
          title="Payroll Trend"
          note="Operational trend only — sums across every organization's currency. For currency-accurate totals, see Finance."
        >
          {!charts || charts.payrollTrend.length === 0 ? (
            <EmptyChart message="No payroll runs in this period." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={charts.payrollTrend} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="gGross" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-primary)" stopOpacity={0.18} />
                    <stop offset="100%" stopColor="var(--color-primary)" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gNet" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-category-teal)" stopOpacity={0.18} />
                    <stop offset="100%" stopColor="var(--color-category-teal)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={{ stroke: "var(--color-border)" }} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={false} tickLine={false} width={50} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="gross" name="Gross" stroke="var(--color-primary)" fill="url(#gGross)" strokeWidth={2} />
                <Area type="monotone" dataKey="net" name="Net" stroke="var(--color-category-teal)" fill="url(#gNet)" strokeWidth={2} strokeDasharray="5 3" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard
          title="Gross vs Net Pay"
          note="Operational total for the selected period — sums across every organization's currency."
        >
          {!charts || (!charts.grossVsNet?.gross && !charts.grossVsNet?.net) ? (
            <EmptyChart message="No payroll data in this period." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={[{ name: "Selected Period", gross: charts.grossVsNet.gross, net: charts.grossVsNet.net }]} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={{ stroke: "var(--color-border)" }} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={false} tickLine={false} width={50} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="gross" name="Gross" fill="var(--color-primary)" radius={[6, 6, 0, 0]} maxBarSize={80} />
                <Bar dataKey="net" name="Net" fill="var(--color-category-teal)" radius={[6, 6, 0, 0]} maxBarSize={80} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Payroll by Jurisdiction" note="Each bar is its own currency — figures are never combined across countries.">
          {!charts || charts.payrollByJurisdiction.length === 0 ? (
            <EmptyChart message="No payroll data yet." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={charts.payrollByJurisdiction} layout="vertical" margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--color-border)" />
                <XAxis type="number" tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="country" tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={false} tickLine={false} width={70} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="grossPay" name="Gross Pay" fill="var(--color-primary)" radius={[0, 6, 6, 0]} maxBarSize={22} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Organization Distribution">
          {orgCountryData.length === 0 ? (
            <EmptyChart message="No organizations yet." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={orgCountryData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
                  {orgCountryData.map((entry, i) => <Cell key={entry.name} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Compliance Overview" height={240}>
          {!charts ? (
            <EmptyChart message="Loading…" />
          ) : (
            <div className="flex h-full flex-col justify-between">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-amber-50 dark:bg-amber-950/30 px-3 py-2.5">
                  <div className="text-xl font-bold text-amber-600 dark:text-amber-400">{charts.complianceOverview.expiringSoon}</div>
                  <div className="text-xs text-amber-700/80 dark:text-amber-400/70">Expiring within 60 days</div>
                </div>
                <div className="rounded-lg bg-rose-50 dark:bg-rose-950/30 px-3 py-2.5">
                  <div className="text-xl font-bold text-rose-600 dark:text-rose-400">{charts.complianceOverview.pendingReview}</div>
                  <div className="text-xs text-rose-700/80 dark:text-rose-400/70">Pending review</div>
                </div>
              </div>
              {complianceByStatus.length > 0 && (
                <ResponsiveContainer width="100%" height={120}>
                  <BarChart data={complianceByStatus} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-foreground-muted)" }} axisLine={false} tickLine={false} interval={0} angle={-15} textAnchor="end" height={40} />
                    <YAxis hide />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="value" name="Policies" fill="var(--color-category-teal)" radius={[4, 4, 0, 0]} maxBarSize={32} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          )}
        </ChartCard>

        <ChartCard title="Employee Distribution by Jurisdiction">
          {!charts || charts.employeesByCountry.length === 0 ? (
            <EmptyChart message="No employees yet." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={charts.employeesByCountry} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="country" tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={{ stroke: "var(--color-border)" }} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "var(--color-foreground-muted)" }} axisLine={false} tickLine={false} width={40} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="employees" name="Employees" fill="var(--color-info)" radius={[6, 6, 0, 0]} maxBarSize={44} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      <div className="flex items-center justify-between mt-8 mb-3">
        <h2 className="text-lg font-semibold text-foreground">Recent Organizations</h2>
        <Link to="/super-admin/organizations" className="text-sm font-medium text-primary-hover hover:text-primary-active">
          View all →
        </Link>
      </div>
      <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Code</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {(stats?.recent_organizations || []).map((org) => (
              <tr key={org.id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">{org.organization_name}</td>
                <td className="px-4 py-3 font-mono text-xs text-foreground-muted">{org.organization_code}</td>
                <td className="px-4 py-3">
                  <StatusPill status={org.is_active ? "active" : "inactive"} />
                </td>
                <td className="px-4 py-3 text-foreground-muted">
                  {new Date(org.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {stats && (stats.recent_organizations || []).length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <LayoutGrid size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No organizations yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}
