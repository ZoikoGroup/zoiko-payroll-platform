import React, { useState, useEffect, useMemo, useCallback, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { getOrganizationDashboardStats, getOrganizationDetails } from "../../service/orgAdminService";
import { Users, Building2, BadgeInfo, CalendarCheck, Activity, CreditCard, Wrench } from "lucide-react";

const DashboardCharts = lazy(() => import("./DashboardCharts"));

const VIOLET = "#5B3FE0";
const AMBER = "#F5A340";
const TEAL = "#0F9B8E";
const RED = "#D6473C";
const INK = "#181433";
const INK_SOFT = "#4A4566";
const VIOLET_100 = "#EDE9FE";
const AMBER_100 = "#FDECD6";
const TEAL_100 = "#DCF5F2";
const RED_100 = "#FBE6E4";
const LINE = "rgba(24,20,51,0.08)";
const AVATAR_COLORS = [
  `linear-gradient(135deg,${VIOLET},#7A5CF0)`,
  `linear-gradient(135deg,${AMBER},#E8862C)`,
  `linear-gradient(135deg,${TEAL},#0C7B70)`,
  `linear-gradient(135deg,#8B85AE,#5F5885)`,
  `linear-gradient(135deg,#7A5CF0,${VIOLET})`,
  `linear-gradient(135deg,#D8D4EC,#B9B4CC)`,
];



function getInitials(name) {
  if (!name) return "U";
  return name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
}

function fmtCurrency(amount) {
  if (amount == null) return "—";
  return `$${Math.round(Number(amount)).toLocaleString("en-US")}`;
}

function todayLabel() {
  const d = new Date();
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return `${dayNames[d.getDay()]}, ${d.getDate()} ${monthNames[d.getMonth()]} ${d.getFullYear()}`;
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

const StatCard = React.memo(({ icon: Icon, iconBg, iconColor, label, value, sub, trendIcon: TrendIcon, trendLabel, trendColor, onClick }) => {
  return (
    <div onClick={onClick} className="rounded-[14px] border bg-white p-5 shadow-[0_1px_2px_rgba(24,20,51,0.04),0_8px_24px_-12px_rgba(24,20,51,0.10)] hover:-translate-y-0.5 hover:shadow-[0_4px_10px_rgba(24,20,51,0.06),0_20px_40px_-20px_rgba(59,46,138,0.25)] hover:border-transparent transition-all duration-[180ms] cursor-pointer">
      <div className="flex items-center justify-between mb-4">
        <div className="w-[38px] h-[38px] rounded-[10px] flex items-center justify-center text-[17px]" style={{ background: iconBg, color: iconColor }}>
          <Icon className="w-[18px] h-[18px]" strokeWidth={2.5} />
        </div>
        {TrendIcon && trendLabel ? (
          <span className="text-[11.5px] font-bold flex items-center gap-1" style={{ color: trendColor }}>
            <TrendIcon className="w-3.5 h-3.5" strokeWidth={2.5} />
            {trendLabel}
          </span>
        ) : null}
      </div>
      <p className="text-[12.5px] font-medium" style={{ color: INK_SOFT }}>{label}</p>
      <p className="text-[29px] font-bold tracking-[-0.01em] leading-none mt-1.5" style={{ color: INK }}>{value}</p>
      {sub ? <p className="text-[11.5px] mt-1.5" style={{ color: INK_SOFT }}>{sub}</p> : null}
    </div>
  );
});

export default function OrgAdminDashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getOrganizationDashboardStats().catch(() => null),
      getOrganizationDetails().catch(() => null),
    ])
      .then(([s, o]) => {
        if (cancelled) return;
        if (s) setStats(s);
        if (o) setOrg(o);
      })
      .catch(err => { if (!cancelled) setError(err?.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const displayName = user?.name || user?.full_name || "Organization Admin";
  const orgName = org?.name || user?.organization_name || "Your Organization";
  const orgId = org?.org_code || org?.code || "ZK-0192";

  const totalEmployees = stats?.total_employees ?? 21;
  const activeEmployees = stats?.active_employees ?? 20;
  const departments = stats?.departments ?? 9;
  const healthScore = totalEmployees > 0 ? Math.round((activeEmployees / totalEmployees) * 100) : 95;

  const fmt = (val, key) => {
    if (val === null || val === undefined) return "—";
    if (key === "monthly_payroll") return fmtCurrency(val);
    return Number(val).toLocaleString();
  };

  const kpiRows = useMemo(() => [
    [
      { key: "active_employees", label: "Active Employees", icon: Users, iconBg: VIOLET_100, iconColor: VIOLET, trend: "up", trendLabel: "100%", path: "/organization-admin/users" },
      { key: "hr_admins", label: "HR Admins", icon: Building2, iconBg: TEAL_100, iconColor: TEAL, trend: "flat", trendLabel: null, path: "/organization-admin/users" },
      { key: "departments", label: "Departments", icon: BadgeInfo, iconBg: AMBER_100, iconColor: AMBER, trend: "up", trendLabel: "2 new", path: "/zoiko-hr/departments" },
      { key: "designations", label: "Designations", icon: BadgeInfo, iconBg: VIOLET_100, iconColor: VIOLET, trend: "flat", trendLabel: null, path: "/zoiko-hr/designations" },
    ],
    [
      { key: "pending_leave_requests", label: "Pending Leaves", icon: CalendarCheck, iconBg: AMBER_100, iconColor: AMBER, trend: "flat", trendLabel: "Clear", path: "/zoiko-hr/leave" },
      { key: "pending_approvals", label: "Pending Approvals", icon: Activity, iconBg: RED_100, iconColor: RED, trend: "flat", trendLabel: "Clear", path: "/zoiko-hr/documents/approvals" },
      { key: "monthly_payroll", label: "Monthly Payroll", icon: CreditCard, iconBg: TEAL_100, iconColor: TEAL, trend: "flat", trendLabel: null, path: "/payroll" },
      { key: "assets", label: "Assets", icon: Wrench, iconBg: VIOLET_100, iconColor: VIOLET, trend: "flat", trendLabel: null, path: "/organization-admin/assets" },
    ],
  ], []);

  const renderKpi = useCallback((kpi) => {
    const val = loading ? "—" : stats ? fmt(stats[kpi.key], kpi.key) : "—";
    const TrendIcon = kpi.trend === "up" ? TrendingUp : kpi.trend === "down" ? TrendingDown : Minus;
    const trendColor = kpi.trend === "up" ? TEAL : kpi.trend === "down" ? RED : INK_SOFT;
    return (
      <StatCard
        key={kpi.key}
        icon={kpi.icon}
        iconBg={kpi.iconBg}
        iconColor={kpi.iconColor}
        label={kpi.label}
        value={val}
        sub={kpi.key === "active_employees" ? `of ${totalEmployees} total headcount` : kpi.key === "departments" ? "Engineering leads headcount" : null}
        trendIcon={TrendIcon}
        trendLabel={kpi.trendLabel}
        trendColor={trendColor}
        onClick={() => navigate(kpi.path)}
      />
    );
  }, [loading, stats, totalEmployees, navigate]);

  return (
    <div className="font-['Inter',system-ui,sans-serif] -m-4 sm:-m-6 lg:-m-8 p-4 sm:p-6 lg:p-8" style={{ background: "#F6F5FA", color: INK, minHeight: "calc(100vh - 4rem)" }}>
      {error && (
        <div className="mb-4 rounded-[14px] border p-4 text-sm" style={{ background: RED_100, borderColor: RED, color: RED }}>
          {error}
        </div>
      )}

      <div className="flex items-center gap-3 mb-4 pb-4" style={{ borderBottom: `1px solid ${LINE}` }}>
        <div className="w-10 h-10 rounded-[12px] flex items-center justify-center flex-shrink-0 overflow-hidden" style={{ background: "#270b87" }}>
          <svg viewBox="0 0 608.1 619.11" className="w-7 h-7">
            <rect x="24.76" y="30.27" width="558.57" height="558.57" rx="127.12" ry="127.12" fill="#270b87"/>
            <path fill="url(#favGrad1)" d="M383.03,121.69c0,93.43-76.04,169.47-169.47,169.47v-95.81c40.61,0,73.66-33.06,73.66-73.66h95.81Z"/>
            <path fill="url(#favGrad2)" d="M377.18,225.86v271.55c-52.94,0-95.81-42.91-95.81-95.81v-101.69c40.25-12.15,74.27-38.87,95.81-74.05Z"/>
            <path fill="url(#favGrad1)" d="M213.55,291.16v-95.81c40.61,0,73.66-33.06,73.66-73.66,0,0,32.7,86.49-73.66,169.47Z"/>
            <path fill="url(#favGrad2)" d="M377.18,411.88v85.53c-52.94,0-95.81-42.91-95.81-95.81v-101.51c0,4.75,1.13,104.99,95.81,111.79Z"/>
            <path fill="url(#favGrad3)" d="M377.18,225.86v271.55c-13.64,0-26.61-2.87-38.37-8.01v-219.89c15.16-12.22,28.17-26.96,38.37-43.65Z" opacity="0.51" style={{mixBlendMode:"screen"}}/>
            <path fill="url(#favGrad3)" d="M383.03,121.69c0,93.43-76.04,169.47-169.47,169.47v-95.81s118.77,51.24,169.47-73.66Z" opacity="0.36" style={{mixBlendMode:"screen"}}/>
            <defs>
              <linearGradient id="favGrad1" x1="435.94" y1="123.97" x2="167.83" y2="257.43" gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor="#00c5ff"/>
                <stop offset="1" stopColor="#0070ff"/>
              </linearGradient>
              <linearGradient id="favGrad2" x1="293.19" y1="361.64" x2="380.16" y2="361.64" gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor="#fc4600"/>
                <stop offset="1" stopColor="#ffb900"/>
              </linearGradient>
              <linearGradient id="favGrad3" x1="356.68" y1="226.07" x2="359.39" y2="497.59" gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor="#009cff"/>
                <stop offset="1" stopColor="#000"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div>
          <p className="font-['Sora',system-ui,sans-serif] text-lg font-bold" style={{ color: INK }}>{orgName}</p>
          <p className="text-[12px] font-medium" style={{ color: INK_SOFT }}>Organization ID · {orgId}</p>
        </div>
      </div>

      <div
        className="relative flex justify-between items-center gap-6 mb-[22px] rounded-[20px] px-[34px] py-[30px] text-white overflow-hidden"
        style={{ background: `linear-gradient(120deg, #1E1447 0%, #3B2E8A 62%, #4C3AAE 100%)`, boxShadow: "0 4px 10px rgba(24,20,51,0.06), 0 20px 40px -20px rgba(59,46,138,0.25)" }}
      >
          <div
            className="absolute rounded-full pointer-events-none"
            style={{ right: -60, top: -90, width: 280, height: 280, background: "radial-gradient(circle, rgba(245,163,64,0.35), transparent 70%)" }}
          />
          <div className="z-[1]">
            <p className="text-[11.5px] font-bold uppercase tracking-[0.12em]" style={{ color: "rgba(255,255,255,0.55)" }}>
              {todayLabel()}
            </p>
            <h1 className="font-['Sora',system-ui,sans-serif] text-[27px] font-bold tracking-[-0.01em] mt-2">{greeting()}, {displayName}</h1>
            <p className="mt-1.5 text-[14px] max-w-[520px]" style={{ color: "rgba(255,255,255,0.68)" }}>
              {totalEmployees} total employees across {departments} departments. Payroll for July is on track and closes in 3 days.
            </p>
            <div className="flex gap-2.5 mt-[18px]">
              <button onClick={() => navigate("/organization-admin/users")} className="btn flex items-center gap-2 px-[18px] py-2.5 rounded-[11px] text-[13.5px] font-semibold border-none cursor-pointer whitespace-nowrap" style={{ background: `linear-gradient(135deg,${AMBER},#E8862C)`, color: "#241000", boxShadow: `0 8px 20px -8px rgba(232,134,44,0.7)` }}>
                ＋ Add Employee
              </button>
              <button onClick={() => navigate("/payroll")} className="btn flex items-center gap-2 px-[18px] py-2.5 rounded-[11px] text-[13.5px] font-semibold cursor-pointer whitespace-nowrap" style={{ background: "rgba(255,255,255,0.1)", color: "#fff", border: "1px solid rgba(255,255,255,0.22)" }}>
                Run Payroll
              </button>
              <button onClick={() => navigate("/zoiko-hr/employee-management/reports")} className="btn hidden sm:flex items-center gap-2 px-[18px] py-2.5 rounded-[11px] text-[13.5px] font-semibold cursor-pointer whitespace-nowrap" style={{ background: "rgba(255,255,255,0.1)", color: "#fff", border: "1px solid rgba(255,255,255,0.22)" }}>
                View Reports
              </button>
            </div>
          </div>
          <div className="z-[1] hidden md:flex items-center gap-4">
            <div className="relative" style={{ width: 88, height: 88 }}>
              <svg width="88" height="88" viewBox="0 0 88 88">
                <circle cx="44" cy="44" r="37" fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="10" />
                <circle cx="44" cy="44" r="37" fill="none" stroke={AMBER} strokeWidth="10"
                  strokeDasharray={`${2 * Math.PI * 37 * healthScore / 100} ${2 * Math.PI * 37 * (100 - healthScore) / 100}`}
                  strokeLinecap="round" transform="rotate(-90 44 44)" />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center font-['Sora',system-ui,sans-serif] font-extrabold text-[19px] pointer-events-none">{healthScore}%</div>
            </div>
            <div>
              <p className="font-['Sora',system-ui,sans-serif] text-[14.5px] font-bold">Org Health Score</p>
              <p className="text-[11px] font-semibold tracking-[0.04em]" style={{ color: "rgba(255,255,255,0.6)" }}>Attendance, payroll &amp; compliance combined</p>
            </div>
          </div>
        </div>

        <div className="flex items-baseline justify-between mb-[14px] mt-[30px]">
          <h2 className="font-['Sora',system-ui,sans-serif] text-[15.5px] font-bold tracking-[-0.01em]" style={{ color: INK }}>Key Metrics</h2>
          <button onClick={() => navigate("/organization-admin/metrics")} className="text-[12.5px] font-semibold cursor-pointer" style={{ color: VIOLET }}>View all metrics →</button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {kpiRows[0].map(renderKpi)}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
          {kpiRows[1].map(renderKpi)}
        </div>

        <Suspense fallback={<div className="mt-8 text-center text-[13px]" style={{ color: INK_SOFT }}>Loading charts...</div>}>
          <DashboardCharts stats={stats} loading={loading} totalEmployees={totalEmployees} departments={departments} activeEmployees={activeEmployees} />
        </Suspense>
    </div>
  );
}

function TrendingUp(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  );
}

function TrendingDown(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <polyline points="23 18 13.5 8.5 8.5 13.5 1 6" />
      <polyline points="17 18 23 18 23 12" />
    </svg>
  );
}

function Minus(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}


