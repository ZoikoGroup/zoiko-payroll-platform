import { useEffect, useRef, useState } from "react";
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
  ScanSearch,
  ChevronsLeft,
  ChevronsRight,
  ChevronRight,
  Sun,
  Moon,
  Bell,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useOrganization } from "../context/OrganizationContext";
import { useDarkMode } from "../context/DarkModeContext";
import { ROLE_LABELS, ROLES } from "../config/roles";
import AssistLauncher from "../modules/assist/AssistLauncher";

const OPERATOR_ROLES = new Set([ROLES.ORG_ADMIN, ROLES.PAYROLL_ADMIN, ROLES.SUPER_ADMIN]);

const SIDEBAR_COLLAPSE_KEY = "zoiko_pay_sidebar_collapsed";

// Enterprise SaaS grouping for the Organization Admin / HR Admin nav. Every
// href below maps to a route that already exists in App.jsx / the payroll
// module's internal page map — nothing here is a placeholder page.
function getMyOrgHref(role) {
  return role === ROLES.PAYROLL_ADMIN ? "/hr-admin/my-organization" : "/organization-admin/organization";
}

function buildNavGroups(role) {
  // "My Organization" lives in the header (see getMyOrgHref usage below),
  // not this list — kept out of Overview intentionally by the sidebar
  // redesign, not an oversight.
  const overviewItems = [{ label: "Dashboard", href: "/payroll", icon: LayoutDashboard, end: true }];
  // Only an Org Admin can invite/manage Payroll Admins — Payroll Admins
  // themselves have no user-creation rights (see ROLE_CREATION_RULES on
  // the backend), so they don't get this nav item at all.
  if (role === ROLES.ORG_ADMIN) {
    overviewItems.push({ label: "Team", href: "/organization-admin/team", icon: Users, end: true });
  }
  const groups = [
    {
      title: "Overview",
      items: overviewItems,
    },
    {
      title: "People",
      items: [
        { label: "Employees", href: "/payroll/employees", icon: Users },
        { label: "Attendance", href: "/payroll/attendance", icon: CalendarCheck },
        { label: "Leaves", href: "/payroll/leaves", icon: BookOpen },
      ],
    },
    {
      title: "Payroll",
      items: [
        { label: "Policy", href: "/payroll/policy", icon: Settings },
        { label: "Payroll Runs", href: "/payroll/payroll-runs", icon: PlayCircle },
        { label: "Payslips", href: "/payroll/payslips", icon: FileText },
      ],
    },
    {
      title: "Compliance",
      items: [{ label: "Compliance", href: "/payroll/compliances", icon: ShieldCheck }],
    },
    {
      title: "Reporting",
      items: [{ label: "Reports", href: "/payroll/reports", icon: BarChart3 }],
    },
  ];
  if (OPERATOR_ROLES.has(role)) {
    groups.push({
      title: "Assist",
      items: [{ label: "Assist Admin", href: "/payroll/assist-admin", icon: ScanSearch }],
    });
  }
  return groups;
}

function isItemActive(item, pathname) {
  const clean = item.href.split(/[?#]/)[0];
  if (item.end) return pathname === clean;
  return pathname === clean || pathname.startsWith(`${clean}/`);
}

// Centralized route → page-name mapping reused by the header's dynamic title.
// Single source of truth shared with the sidebar nav groups.
function getPageLabel(role, pathname) {
  const entries = buildNavGroups(role).flatMap((group) => group.items);
  const match = entries.find((item) => isItemActive(item, pathname));
  return match?.label || "Dashboard";
}

function getInitials(name) {
  return (
    (name || "")
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase() || "?"
  );
}

function NavSection({ title, items, pathname, onNavigate, collapsed }) {
  return (
    <div>
      {!collapsed && (
        <p className="mb-3 px-1 text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8A82B7]">{title}</p>
      )}
      <div className="space-y-1.5">
        {items.map((item) => {
          const active = isItemActive(item, pathname);
          return (
            <NavLink
              key={item.href}
              to={item.href}
              end={item.end}
              onClick={onNavigate}
              title={collapsed ? item.label : undefined}
              aria-current={active ? "page" : undefined}
              className={`group flex items-center gap-3 rounded-[12px] border px-3.5 py-2.5 text-sm transition duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9E7BFF] ${
                collapsed ? "justify-center px-0" : ""
              } ${
                active
                  ? "border-[#7B3AEB]/40 bg-gradient-to-r from-[#4C2CC5] via-[#7B3AEB] to-[#6033D3] text-white shadow-[0_12px_28px_rgba(70,38,156,0.22)]"
                  : "border-transparent text-[#B2ACC8] hover:border-white/10 hover:bg-white/8 hover:text-white"
              }`}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
            </NavLink>
          );
        })}
      </div>
    </div>
  );
}

function SidebarContent({ onNavigate, role, collapsed, onToggleCollapse, closeButtonRef }) {
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const navGroups = buildNavGroups(role);
  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "Account";

  return (
    <div className="flex h-full flex-col">
      <div className={`mb-5 flex items-center gap-3 ${collapsed ? "flex-col" : "justify-between"}`}>
        {collapsed ? (
          <Link
            to="/payroll"
            onClick={onNavigate}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 text-sm font-extrabold text-[#FC7800]"
          >
            Z
          </Link>
        ) : (
          <div className="flex flex-col gap-1.5">
            <Link to="/payroll" onClick={onNavigate} className="text-[22px] font-extrabold tracking-tight text-white">
              <span>Zoiko</span>
              <span className="text-[#FC7800]">-Pay</span>
            </Link>
            {ROLE_LABELS[role] ? (
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-[#B2ACC8]">{ROLE_LABELS[role]}</p>
            ) : null}
          </div>
        )}
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onNavigate}
          aria-label="Close menu"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-white transition hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9E7BFF] lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-white transition hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9E7BFF] lg:inline-flex"
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
        </button>
      </div>

      <nav aria-label="Organization admin navigation" className="scrollbar-hide flex-1 space-y-6 overflow-y-auto pb-6">
        {navGroups.map((group) => (
          <NavSection
            key={group.title}
            title={group.title}
            items={group.items}
            pathname={pathname}
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
        ))}
      </nav>

      <div className="mt-auto space-y-4 border-t border-white/10 pt-5">
        <div className={`flex items-center gap-3 ${collapsed ? "justify-center" : ""}`} title={collapsed ? displayName : undefined}>
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-semibold text-white">
            {getInitials(displayName)}
          </span>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-white">{displayName}</p>
              <p className="truncate text-xs text-[#B2ACC8]">{ROLE_LABELS[role] || ""}</p>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
          title={collapsed ? "Sign out" : undefined}
          className={`flex w-full items-center gap-3 rounded-[12px] border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-[#B2ACC8] transition duration-150 hover:border-[#FF6E86]/40 hover:bg-[#FF6E86]/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9E7BFF] ${
            collapsed ? "justify-center px-0" : ""
          }`}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
        {!collapsed && (
          <div>
            <p className="text-[9px] tracking-[0.28em] text-[#7A7396]">POWERED BY</p>
            <p className="text-[14px] font-extrabold text-white">
              <span>Zoiko</span>
              <span className="text-[#FC7800]">-Pay</span>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function ThemeToggle() {
  const { isDark, toggle } = useDarkMode();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#6B6560] transition hover:bg-[#F8F7F4] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7B3AEB] dark:text-[#A69B93] dark:hover:bg-white/10"
    >
      {isDark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Notifications"
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#6B6560] transition hover:bg-[#F8F7F4] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7B3AEB]"
      >
        <Bell size={18} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-2 w-72 rounded-xl border border-[#E5E0D9] bg-white py-4 px-4 text-center shadow-lg"
          >
            <p className="text-sm text-[#9E9690]">You're all caught up — no new notifications.</p>
          </div>
        </>
      )}
    </div>
  );
}

function CurrentDateBadge() {
  const [today] = useState(() => new Date());
  const formatted = today.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  return <span className="hidden shrink-0 text-sm text-[#6B6560] sm:inline">{formatted}</span>;
}

function Header({ onOpenMobileSidebar, onToggleCollapse, collapsed, menuButtonRef }) {
  const { role } = useAuth();
  const { organization } = useOrganization();
  const { pathname } = useLocation();
  const companyName = organization?.name || organization?.organization_name || "";
  const logo = organization?.logo_data_uri;
  const pageLabel = getPageLabel(role, pathname);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-[#EFEBE3] bg-white/95 px-4 backdrop-blur sm:px-6">
      <button
        ref={menuButtonRef}
        type="button"
        onClick={onOpenMobileSidebar}
        aria-label="Open menu"
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#6B6560] transition hover:bg-[#F8F7F4] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7B3AEB] lg:hidden"
      >
        <Menu size={18} />
      </button>
      <button
        type="button"
        onClick={onToggleCollapse}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#6B6560] transition hover:bg-[#F8F7F4] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7B3AEB] lg:inline-flex"
      >
        {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
      </button>

      <div className="flex min-w-0 items-center gap-2">
        <Link
          to={getMyOrgHref(role)}
          title="Go to My Organization"
          className="flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 transition hover:bg-[#F8F7F4] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7B3AEB]"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[#F3F1EC] text-[#8A82B7]">
            {logo ? <img src={logo} alt="" className="h-full w-full object-cover" /> : <Building2 size={16} />}
          </span>
          {companyName && (
            <span className="hidden truncate text-sm font-semibold text-[#1A1816] sm:inline">{companyName}</span>
          )}
        </Link>
        <ChevronRight size={14} className="hidden shrink-0 text-[#C7C1B8] sm:inline" />
        <span className="truncate text-sm font-semibold text-[#1A1816]">{pageLabel}</span>
      </div>

      <div className="ml-auto flex items-center gap-1.5 sm:gap-3">
        <ThemeToggle />
        <NotificationBell />
        <CurrentDateBadge />
      </div>
    </header>
  );
}

export default function PayrollShell({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1";
  });
  const { role } = useAuth();
  const menuButtonRef = useRef(null);
  const closeButtonRef = useRef(null);
  const wasOpenRef = useRef(false);

  function toggleCollapse() {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(SIDEBAR_COLLAPSE_KEY, next ? "1" : "0");
      return next;
    });
  }

  useEffect(() => {
    if (sidebarOpen) {
      closeButtonRef.current?.focus();
      wasOpenRef.current = true;
    } else if (wasOpenRef.current) {
      menuButtonRef.current?.focus();
      wasOpenRef.current = false;
    }
  }, [sidebarOpen]);

  return (
    <div className="min-h-screen bg-[#F8F7F4]">
      <div
        className={`fixed inset-0 z-30 bg-slate-950/40 transition-opacity lg:hidden ${
          sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside
        role="navigation"
        aria-label="Sidebar"
        className={`fixed inset-y-0 left-0 z-40 overflow-hidden border-r border-white/10 bg-gradient-to-b from-[#1F0B63] to-[#160845] px-4 py-6 shadow-[0_24px_80px_rgba(8,6,37,0.42)] transition-[transform,width] duration-200 lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "w-72 lg:w-20" : "w-72 lg:w-[272px]"}`}
      >
        <SidebarContent
          onNavigate={() => setSidebarOpen(false)}
          role={role}
          collapsed={collapsed && !sidebarOpen}
          onToggleCollapse={toggleCollapse}
          closeButtonRef={closeButtonRef}
        />
      </aside>

      <div className={`transition-[padding] duration-200 ${collapsed ? "lg:pl-20" : "lg:pl-[272px]"}`}>
        <Header
          onOpenMobileSidebar={() => setSidebarOpen(true)}
          onToggleCollapse={toggleCollapse}
          collapsed={collapsed}
          menuButtonRef={menuButtonRef}
        />
        <main className="w-full">{children}</main>
      </div>

      <AssistLauncher />
    </div>
  );
}
