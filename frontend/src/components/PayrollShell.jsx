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
  ChevronsLeft,
  ChevronsRight,
  ChevronRight,
  Bell,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useOrganization } from "../context/OrganizationContext";
import { ROLE_LABELS, ROLES } from "../config/roles";
import ThemeToggle from "./ThemeToggle";

const SIDEBAR_COLLAPSE_KEY = "zoiko_pay_sidebar_collapsed";

// Enterprise SaaS grouping for the Organization Admin / HR Admin nav. Every
// href below maps to a route that already exists in App.jsx / the payroll
// module's internal page map — nothing here is a placeholder page.
function getMyOrgHref(role) {
  return role === ROLES.PAYROLL_ADMIN ? "/hr-admin/my-organization" : "/organization-admin/organization";
}

function buildNavGroups(role) {
  const overviewItems = [
    { label: "Dashboard", href: "/payroll", icon: LayoutDashboard, end: true },
    { label: "My Organization", href: getMyOrgHref(role), icon: Building2, end: true },
  ];
  // Only an Org Admin can invite/manage Payroll Admins — Payroll Admins
  // themselves have no user-creation rights (see ROLE_CREATION_RULES on
  // the backend), so they don't get this nav item at all.
  if (role === ROLES.ORG_ADMIN) {
    overviewItems.push({ label: "Team", href: "/organization-admin/team", icon: Users, end: true });
  }
  return [
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
        <p className="mb-3 px-1 text-[10px] font-semibold uppercase tracking-[0.28em] text-white/40">{title}</p>
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
              className={`group flex items-center gap-3 rounded-[10px] border-l-[3px] px-3.5 py-2.5 text-sm transition duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring ${
                collapsed ? "justify-center px-0" : ""
              } ${
                active
                  ? "border-brand-cyan bg-white/10 text-white"
                  : "border-transparent text-white/60 hover:bg-white/5 hover:text-white"
              }`}
            >
              <item.icon className={`h-4 w-4 shrink-0 ${active ? "text-brand-cyan" : ""}`} />
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
          <Link to="/payroll" onClick={onNavigate} className="flex h-9 w-9 items-center justify-center">
            <img src="/zoikopayroll-icon.png" alt="Zoiko Payroll" className="h-9 w-9 rounded-xl object-contain" />
          </Link>
        ) : (
          <div className="flex flex-col gap-1.5">
            <Link to="/payroll" onClick={onNavigate} className="inline-flex w-fit rounded-lg bg-white px-2.5 py-1.5">
              <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-6 w-auto object-contain" />
            </Link>
            {ROLE_LABELS[role] ? (
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-white/60">{ROLE_LABELS[role]}</p>
            ) : null}
          </div>
        )}
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onNavigate}
          aria-label="Close menu"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-white transition hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-white transition hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring lg:inline-flex"
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
              <p className="truncate text-xs text-white/60">{ROLE_LABELS[role] || ""}</p>
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
          className={`flex w-full items-center gap-3 rounded-[12px] border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white/60 transition duration-150 hover:border-error/40 hover:bg-error/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring ${
            collapsed ? "justify-center px-0" : ""
          }`}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
        {!collapsed && (
          <div className="flex items-center gap-2">
            <img src="/zoikopayroll-icon.png" alt="" className="h-6 w-6 rounded-md object-contain" />
            <div>
              <p className="text-[9px] tracking-[0.28em] text-white/40">POWERED BY</p>
              <p className="text-[14px] font-extrabold text-white">Zoiko Payroll</p>
            </div>
          </div>
        )}
      </div>
    </div>
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
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-foreground-muted transition hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        <Bell size={18} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-2 w-72 rounded-xl border border-border bg-surface py-4 px-4 text-center shadow-lg"
          >
            <p className="text-sm text-foreground-muted">You're all caught up — no new notifications.</p>
          </div>
        </>
      )}
    </div>
  );
}

function CurrentDateBadge() {
  const [today] = useState(() => new Date());
  const formatted = today.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  return <span className="hidden shrink-0 text-sm text-foreground-muted sm:inline">{formatted}</span>;
}

function Header({ onOpenMobileSidebar, onToggleCollapse, collapsed, menuButtonRef }) {
  const { role } = useAuth();
  const { organization } = useOrganization();
  const { pathname } = useLocation();
  const companyName = organization?.name || organization?.organization_name || "";
  const logo = organization?.logo_data_uri;
  const pageLabel = getPageLabel(role, pathname);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-surface/95 px-4 backdrop-blur sm:px-6">
      <button
        ref={menuButtonRef}
        type="button"
        onClick={onOpenMobileSidebar}
        aria-label="Open menu"
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-foreground-muted transition hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring lg:hidden"
      >
        <Menu size={18} />
      </button>
      <button
        type="button"
        onClick={onToggleCollapse}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg text-foreground-muted transition hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring lg:inline-flex"
      >
        {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
      </button>

      <div className="flex min-w-0 items-center gap-2">
        <Link
          to={getMyOrgHref(role)}
          title="Go to My Organization"
          className="flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 transition hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-muted text-foreground-muted">
            {logo ? <img src={logo} alt="" className="h-full w-full object-cover" /> : <Building2 size={16} />}
          </span>
          {companyName && (
            <span className="hidden truncate text-sm font-semibold text-foreground sm:inline">{companyName}</span>
          )}
        </Link>
        <ChevronRight size={14} className="hidden shrink-0 text-border-strong sm:inline" />
        <span className="truncate text-sm font-semibold text-foreground">{pageLabel}</span>
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
    <div className="min-h-screen bg-background">
      <div
        className={`fixed inset-0 z-30 bg-slate-950/40 transition-opacity lg:hidden ${
          sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside
        role="navigation"
        aria-label="Sidebar"
        className={`fixed inset-y-0 left-0 z-40 overflow-hidden border-r border-white/10 bg-gradient-to-b from-brand-navy to-brand-navy-deep px-4 py-6 shadow-[0_8px_28px_rgba(8,43,69,0.28)] transition-[transform,width] duration-200 lg:translate-x-0 ${
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
    </div>
  );
}
