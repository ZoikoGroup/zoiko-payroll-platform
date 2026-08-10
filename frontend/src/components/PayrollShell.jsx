import { useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  X,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  Users,
  CalendarCheck,
  BookOpen,
  PlayCircle,
  FileText,
  BarChart3,
  Building2,
  Menu,
  LogOut,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { ROLE_LABELS, ROLES } from "../config/roles";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/payroll", icon: LayoutDashboard },
  { label: "Policy", href: "/payroll/policy", icon: Settings },
  { label: "Compliances", href: "/payroll/compliances", icon: ShieldCheck },
  { label: "Employees", href: "/payroll/employees", icon: Users },
  { label: "Attendance", href: "/payroll/attendance", icon: CalendarCheck },
  { label: "Leaves", href: "/payroll/leaves", icon: BookOpen },
  { label: "Payroll Runs", href: "/payroll/payroll-runs", icon: PlayCircle },
  { label: "Payslips", href: "/payroll/payslips", icon: FileText },
  { label: "Reports", href: "/payroll/reports", icon: BarChart3 },
];

// Mirrors the main ZoikoOne platform's "ORGANIZATION ADMIN" / "HR ADMIN"
// sidebar sections — same Dashboard + My Organization items, just scoped to
// this standalone platform's org_admin / payroll_admin roles.
const ROLE_SECTIONS = {
  [ROLES.ORG_ADMIN]: {
    title: "Organization Admin",
    items: [
      { label: "Dashboard", href: "/organization-admin/dashboard", icon: LayoutDashboard },
      { label: "My Organization", href: "/organization-admin/organization", icon: Building2 },
    ],
  },
  [ROLES.PAYROLL_ADMIN]: {
    title: "HR Admin",
    items: [
      { label: "Dashboard", href: "/hr-admin/dashboard", icon: LayoutDashboard },
      { label: "My Organization", href: "/hr-admin/my-organization", icon: Building2 },
    ],
  },
};

function isActive(href, pathname) {
  const clean = href.split(/[?#]/)[0];
  if (clean === "/payroll") return pathname === "/payroll";
  return pathname === clean || pathname.startsWith(`${clean}/`);
}

function NavSection({ title, items, pathname, onNavigate }) {
  return (
    <div>
      <p className="mb-4 text-[10px] uppercase tracking-[0.32em] text-[#8A82B7]">{title}</p>
      <div className="space-y-2">
        {items.map((item) => (
          <NavLink
            key={item.href}
            to={item.href}
            end={item.href === "/payroll"}
            onClick={onNavigate}
            className={`group flex items-center gap-3 rounded-[14px] border px-4 py-3 text-sm transition duration-200 ${
              isActive(item.href, pathname)
                ? "border-[#7B3AEB]/40 bg-gradient-to-r from-[#4C2CC5] via-[#7B3AEB] to-[#6033D3] text-white shadow-[0_18px_40px_rgba(70,38,156,0.18)]"
                : "border-white/10 bg-white/5 text-[#B2ACC8] hover:border-white/20 hover:bg-white/10 hover:text-white"
            }`}
          >
            <item.icon className="h-4 w-4 shrink-0" />
            <span className="flex-1 truncate">{item.label}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );
}

function SidebarContent({ onNavigate, role }) {
  const { pathname } = useLocation();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const roleSection = ROLE_SECTIONS[role];

  return (
    <div className="flex h-full flex-col">
      <div className="mb-8 flex items-center justify-between gap-3">
        <div className="flex flex-col gap-2">
          <Link to="/payroll" onClick={onNavigate} className="text-[22px] font-extrabold tracking-tight text-white">
            <span>Zoiko</span>
            <span className="text-[#FC7800]">One</span>
          </Link>
          {ROLE_LABELS[role] ? (
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-[#B2ACC8]">
              {ROLE_LABELS[role]}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onNavigate}
          className="inline-flex h-9 w-9 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-white transition hover:border-white/20 hover:bg-white/10 lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-7 pb-8">
        {roleSection ? (
          <NavSection title={roleSection.title} items={roleSection.items} pathname={pathname} onNavigate={onNavigate} />
        ) : null}
        <NavSection title="Zoiko Payroll" items={NAV_ITEMS} pathname={pathname} onNavigate={onNavigate} />
      </div>

      <div className="mt-auto space-y-4">
        <button
          type="button"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
          className="flex w-full items-center gap-3 rounded-[14px] border border-white/10 bg-white/5 px-4 py-3 text-sm text-[#B2ACC8] transition duration-200 hover:border-[#FF6E86]/40 hover:bg-[#FF6E86]/10 hover:text-white"
        >
          <LogOut className="h-4 w-4" />
          <span>Sign out</span>
        </button>
        <div className="border-t border-white/10 pt-5">
          <p className="text-[9px] tracking-[0.28em] text-[#7A7396]">POWERED BY</p>
          <p className="text-[14px] font-extrabold text-white">
            <span>Zoiko</span>
            <span className="text-[#FC7800]">One</span>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function PayrollShell({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { role } = useAuth();

  return (
    <div className="min-h-screen bg-[#F8F7F4]">
      <div
        className={`fixed inset-0 z-30 bg-slate-950/40 transition-opacity lg:hidden ${
          sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-72 overflow-y-auto border-r border-white/10 bg-gradient-to-b from-[#1F0B63] to-[#160845] px-4 py-6 shadow-[0_24px_80px_rgba(8,6,37,0.42)] transition-transform lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <SidebarContent onNavigate={() => setSidebarOpen(false)} role={role} />
      </aside>

      <div className="lg:pl-72">
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="fixed top-4 left-4 z-20 inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-[#E5E0D9] bg-white text-[#6B6560] shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] lg:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>
        <main className="w-full">{children}</main>
      </div>
    </div>
  );
}
