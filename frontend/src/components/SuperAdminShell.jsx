import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Menu,
  X,
  LayoutDashboard,
  Building2,
  Users,
  Settings,
  LogOut,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  Mail,
  KeyRound,
  Copy,
  Check,
  Wallet,
  FileBarChart,
  ShieldCheck,
  Landmark,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { ToastProvider, useToast } from "../context/ToastContext";
import { apiFetch } from "../api/client";
import Modal from "./Modal";
import ThemeToggle from "./ThemeToggle";

const SIDEBAR_COLLAPSE_KEY = "zoiko_pay_super_admin_sidebar_collapsed";

// Same grouped enterprise-nav format as the Organization Admin sidebar
// (components/PayrollShell.jsx) — short section labels, few items each.
const NAV_GROUPS = [
  {
    title: "Overview",
    items: [{ label: "Dashboard", href: "/super-admin/dashboard", icon: LayoutDashboard, end: true }],
  },
  {
    title: "Organizations",
    items: [
      { label: "Organizations", href: "/super-admin/organizations", icon: Building2 },
      { label: "Users", href: "/super-admin/users", icon: Users },
    ],
  },
  {
    title: "Compliance & Finance",
    items: [
      { label: "Compliance", href: "/super-admin/compliance", icon: ShieldCheck },
      { label: "Statutory Rates", href: "/super-admin/statutory-rates", icon: Landmark },
      { label: "Finance", href: "/super-admin/finance", icon: Wallet },
    ],
  },
  {
    title: "Reporting",
    items: [{ label: "Reports", href: "/super-admin/reports", icon: FileBarChart }],
  },
  {
    title: "System",
    items: [{ label: "Settings", href: "/super-admin/settings", icon: Settings }],
  },
];

function isItemActive(item, pathname) {
  if (item.end) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function getPageLabel(pathname) {
  const entries = NAV_GROUPS.flatMap((group) => group.items);
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

function SidebarContent({ onNavigate, collapsed, onToggleCollapse, closeButtonRef }) {
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "Super Admin";

  return (
    <div className="flex h-full flex-col">
      <div className={`mb-5 flex items-center gap-3 ${collapsed ? "flex-col" : "justify-between"}`}>
        {collapsed ? (
          <img
            src="/zoikopayroll-icon.png"
            alt="Zoiko Payroll"
            className="h-9 w-9 rounded-xl object-contain"
          />
        ) : (
          <div className="flex flex-col gap-1.5">
            <div className="inline-flex w-fit rounded-lg bg-white px-3 py-2.5">
              <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-11 w-auto object-contain" />
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-white/60">Super Admin</p>
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

      <nav aria-label="Super Admin navigation" className="scrollbar-hide flex-1 space-y-6 overflow-y-auto pb-6">
        {NAV_GROUPS.map((group) => (
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
              <p className="truncate text-xs text-white/60">Super Admin</p>
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
          <div>
            <p className="text-[9px] tracking-[0.28em] text-white/40">POWERED BY</p>
            <p className="text-[14px] font-extrabold text-white">Zoiko Payroll</p>
          </div>
        )}
      </div>
    </div>
  );
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="flex items-center gap-1.5 rounded-lg bg-surface-muted px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:bg-border-light"
    >
      {copied ? <Check size={13} className="text-success" /> : <Copy size={13} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function GeneratedPasswordModal({ password, onClose }) {
  return (
    <Modal title="New password generated" onClose={onClose} maxWidth="max-w-md">
      <p className="text-sm text-foreground-secondary mb-4">
        Save this now — it won't be shown again. Use it to sign in, then change it to something memorable.
      </p>
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background-secondary px-3.5 py-3">
        <code className="truncate text-sm font-mono text-foreground">{password}</code>
        <CopyButton text={password} />
      </div>
      <div className="mt-5 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover"
        >
          Done
        </button>
      </div>
    </Modal>
  );
}

function ProfileMenu() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [generatedPassword, setGeneratedPassword] = useState(null);
  const { user } = useAuth();
  const { addToast } = useToast();

  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "Super Admin";

  async function handleEmailReset() {
    setOpen(false);
    setBusy(true);
    try {
      await apiFetch("/api/auth/forgot-password", { method: "POST", body: { email: user?.email } });
      addToast?.(`Reset link sent to ${user?.email}.`);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleGeneratePassword() {
    setOpen(false);
    setBusy(true);
    try {
      const res = await apiFetch("/api/auth/generate-password", { method: "POST" });
      setGeneratedPassword(res.password);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        disabled={busy}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full border border-border py-1 pl-1 pr-2.5 text-sm hover:bg-surface-muted disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-light text-xs font-semibold text-primary">
          {getInitials(displayName)}
        </span>
        <span className="hidden text-foreground sm:inline">{displayName}</span>
        <ChevronDown size={14} className="text-foreground-muted" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-64 rounded-xl border border-border bg-surface py-1 shadow-lg">
            <div className="border-b border-border-light px-3.5 py-2.5">
              <p className="truncate text-sm font-medium text-foreground">{displayName}</p>
              <p className="truncate text-xs text-foreground-muted">{user?.email}</p>
            </div>
            <div className="py-1">
              <button
                type="button"
                onClick={handleEmailReset}
                className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-foreground-secondary hover:bg-surface-muted"
              >
                <Mail size={15} />
                Reset password by email
              </button>
              <button
                type="button"
                onClick={handleGeneratePassword}
                className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-foreground-secondary hover:bg-surface-muted"
              >
                <KeyRound size={15} />
                Generate random password
              </button>
            </div>
          </div>
        </>
      )}

      {generatedPassword && (
        <GeneratedPasswordModal password={generatedPassword} onClose={() => setGeneratedPassword(null)} />
      )}
    </div>
  );
}

function Header({ onOpenSidebar, onToggleCollapse, collapsed }) {
  const { pathname } = useLocation();
  const pageLabel = getPageLabel(pathname);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-surface px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenSidebar}
          aria-label="Open menu"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-foreground-muted hover:bg-surface-muted lg:hidden"
        >
          <Menu size={18} />
        </button>
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden h-9 w-9 items-center justify-center rounded-lg text-foreground-muted hover:bg-surface-muted lg:inline-flex"
        >
          {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
        </button>
        <div className="hidden sm:block">
          <span className="text-sm font-semibold text-foreground">Zoiko Payroll</span>
          <span className="mx-2 text-border-strong">·</span>
          <span className="text-sm text-foreground-muted">{pageLabel}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <ProfileMenu />
      </div>
    </header>
  );
}

function ToastStack() {
  const { toasts, removeToast } = useToast();
  return (
    <div className="fixed bottom-5 right-5 z-[9999] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm shadow-lg transition-all duration-200 ${
            toast.type === "success"
              ? "border-success/30 bg-success-light text-success"
              : toast.type === "error"
              ? "border-error/30 bg-error-light text-error"
              : "border-info/30 bg-info-light text-info"
          }`}
        >
          <span>{toast.message}</span>
          <button
            type="button"
            onClick={() => removeToast(toast.id)}
            className="ml-3 rounded-lg p-1 text-current/70 hover:bg-black/5"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export default function SuperAdminShell({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1";
  });
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
    <ToastProvider>
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
            collapsed={collapsed && !sidebarOpen}
            onToggleCollapse={toggleCollapse}
            closeButtonRef={closeButtonRef}
          />
        </aside>

        <div className={`transition-[padding] duration-200 ${collapsed ? "lg:pl-20" : "lg:pl-[272px]"}`}>
          <Header onOpenSidebar={() => setSidebarOpen(true)} onToggleCollapse={toggleCollapse} collapsed={collapsed} />
          <main className="w-full p-4 sm:p-6 lg:p-8">{children}</main>
        </div>

        <ToastStack />
      </div>
    </ToastProvider>
  );
}
