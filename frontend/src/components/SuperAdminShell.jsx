import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Menu,
  X,
  LayoutDashboard,
  Building2,
  Users,
  Landmark,
  Settings,
  LogOut,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  Mail,
  KeyRound,
  Copy,
  Check,
  ShieldCheck,
  Wallet,
  FileBarChart,
  Sun,
  Moon,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useDarkMode } from "../context/DarkModeContext";
import { ToastProvider, useToast } from "../context/ToastContext";
import { apiFetch } from "../api/client";
import Modal from "./Modal";

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

function SidebarContent({ onNavigate, collapsed, onToggleCollapse, closeButtonRef }) {
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "Super Admin";

  return (
    <div className="flex h-full flex-col">
      <div className={`mb-5 flex items-center gap-3 ${collapsed ? "flex-col" : "justify-between"}`}>
        {collapsed ? (
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 text-sm font-extrabold text-[#FC7800]">
            Z
          </span>
        ) : (
          <div className="flex flex-col gap-1.5">
            <span className="text-[22px] font-extrabold tracking-tight text-white">
              <span>Zoiko</span>
              <span className="text-[#FC7800]">-Pay</span>
            </span>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-[#B2ACC8]">Super Admin</p>
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
              <p className="truncate text-xs text-[#B2ACC8]">Super Admin</p>
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
      className="flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200"
    >
      {copied ? <Check size={13} className="text-green-600" /> : <Copy size={13} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function GeneratedPasswordModal({ password, onClose }) {
  return (
    <Modal title="New password generated" onClose={onClose} maxWidth="max-w-md">
      <p className="text-sm text-slate-600 mb-4">
        Save this now — it won't be shown again. Use it to sign in, then change it to something memorable.
      </p>
      <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-3">
        <code className="truncate text-sm font-mono text-slate-800">{password}</code>
        <CopyButton text={password} />
      </div>
      <div className="mt-5 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600"
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
        className="flex items-center gap-2 rounded-full border border-slate-200 dark:border-[#38312D] py-1 pl-1 pr-2.5 text-sm hover:bg-slate-50 dark:hover:bg-white/5 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-500"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-orange-100 text-xs font-semibold text-orange-600">
          {getInitials(displayName)}
        </span>
        <span className="hidden text-slate-700 dark:text-[#F0EDE8] sm:inline">{displayName}</span>
        <ChevronDown size={14} className="text-slate-400 dark:text-[#756B64]" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-64 rounded-xl border border-slate-200 dark:border-[#38312D] bg-white dark:bg-[#221D1A] py-1 shadow-lg">
            <div className="border-b border-slate-100 dark:border-[#38312D] px-3.5 py-2.5">
              <p className="truncate text-sm font-medium text-slate-800 dark:text-[#F0EDE8]">{displayName}</p>
              <p className="truncate text-xs text-slate-500 dark:text-[#A69B93]">{user?.email}</p>
            </div>
            <div className="py-1">
              <button
                type="button"
                onClick={handleEmailReset}
                className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-slate-600 dark:text-[#A69B93] hover:bg-slate-50 dark:hover:bg-white/5"
              >
                <Mail size={15} />
                Reset password by email
              </button>
              <button
                type="button"
                onClick={handleGeneratePassword}
                className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-slate-600 dark:text-[#A69B93] hover:bg-slate-50 dark:hover:bg-white/5"
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

function ThemeToggle() {
  const { isDark, toggle } = useDarkMode();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/10"
    >
      {isDark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

function Header({ onOpenSidebar, onToggleCollapse, collapsed }) {
  const { pathname } = useLocation();
  const pageLabel = getPageLabel(pathname);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200 dark:border-[#38312D] bg-white dark:bg-[#221D1A] px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenSidebar}
          aria-label="Open menu"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/10 lg:hidden"
        >
          <Menu size={18} />
        </button>
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden h-9 w-9 items-center justify-center rounded-lg text-slate-500 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/10 lg:inline-flex"
        >
          {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
        </button>
        <div className="hidden sm:block">
          <span className="text-sm font-semibold text-slate-800 dark:text-[#F0EDE8]">Zoiko-Pay</span>
          <span className="mx-2 text-slate-300 dark:text-[#38312D]">·</span>
          <span className="text-sm text-slate-500 dark:text-[#A69B93]">{pageLabel}</span>
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
              ? "border-green-200 bg-green-50 text-green-700"
              : toast.type === "error"
              ? "border-red-200 bg-red-50 text-red-700"
              : "border-blue-200 bg-blue-50 text-blue-700"
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
      <div className="min-h-screen bg-slate-50 dark:bg-[#1A1816]">
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
