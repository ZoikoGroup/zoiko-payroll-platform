import { useState } from "react";
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
  Mail,
  KeyRound,
  Copy,
  Check,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { ToastProvider, useToast } from "../context/ToastContext";
import { apiFetch } from "../api/client";
import Modal from "./Modal";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/super-admin/dashboard", icon: LayoutDashboard },
  { label: "Organizations", href: "/super-admin/organizations", icon: Building2 },
  { label: "Users", href: "/super-admin/users", icon: Users },
  { label: "Statutory Rates", href: "/super-admin/statutory-rates", icon: Landmark },
  { label: "Settings", href: "/super-admin/settings", icon: Settings },
];

function isActive(href, pathname) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function SidebarContent({ onNavigate }) {
  const { pathname } = useLocation();

  return (
    <div className="flex h-full flex-col">
      <div className="mb-8 flex items-center justify-between gap-3">
        <span className="text-[22px] font-extrabold tracking-tight text-white">
          <span>Zoiko</span>
          <span className="text-[#FC7800]">-Pay</span>
        </span>
        <button
          type="button"
          onClick={onNavigate}
          className="inline-flex h-9 w-9 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-white transition hover:border-white/20 hover:bg-white/10 lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <p className="mb-4 text-[10px] uppercase tracking-[0.32em] text-[#8A82B7]">Super Admin</p>
      <div className="space-y-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.href}
            to={item.href}
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

      <div className="mt-auto border-t border-white/10 pt-5">
        <p className="text-[9px] tracking-[0.28em] text-[#7A7396]">POWERED BY</p>
        <p className="text-[14px] font-extrabold text-white">
          <span>Zoiko</span>
          <span className="text-[#FC7800]">-Pay</span>
        </p>
      </div>
    </div>
  );
}

function initialsFor(name) {
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
  const { user, logout } = useAuth();
  const { addToast } = useToast();
  const navigate = useNavigate();

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
        className="flex items-center gap-2 rounded-full border border-slate-200 py-1 pl-1 pr-2.5 text-sm hover:bg-slate-50 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-500"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-orange-100 text-xs font-semibold text-orange-600">
          {initialsFor(displayName)}
        </span>
        <span className="hidden text-slate-700 sm:inline">{displayName}</span>
        <ChevronDown size={14} className="text-slate-400" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-64 rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
            <div className="border-b border-slate-100 px-3.5 py-2.5">
              <p className="truncate text-sm font-medium text-slate-800">{displayName}</p>
              <p className="truncate text-xs text-slate-500">{user?.email}</p>
            </div>
            <div className="border-b border-slate-100 py-1">
              <button
                type="button"
                onClick={handleEmailReset}
                className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-slate-600 hover:bg-slate-50"
              >
                <Mail size={15} />
                Reset password by email
              </button>
              <button
                type="button"
                onClick={handleGeneratePassword}
                className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-slate-600 hover:bg-slate-50"
              >
                <KeyRound size={15} />
                Generate random password
              </button>
            </div>
            <button
              type="button"
              onClick={() => {
                logout();
                navigate("/login", { replace: true });
              }}
              className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm text-slate-600 hover:bg-slate-50"
            >
              <LogOut size={15} />
              Logout
            </button>
          </div>
        </>
      )}

      {generatedPassword && (
        <GeneratedPasswordModal password={generatedPassword} onClose={() => setGeneratedPassword(null)} />
      )}
    </div>
  );
}

function Header({ onOpenSidebar }) {
  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenSidebar}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 lg:hidden"
        >
          <Menu size={18} />
        </button>
        <div className="hidden sm:block">
          <span className="text-sm font-semibold text-slate-800">Zoiko-Pay</span>
          <span className="mx-2 text-slate-300">·</span>
          <span className="text-sm text-slate-500">Super Admin Console</span>
        </div>
      </div>
      <ProfileMenu />
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

  return (
    <ToastProvider>
      <div className="min-h-screen bg-slate-50">
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
          <SidebarContent onNavigate={() => setSidebarOpen(false)} />
        </aside>

        <div className="lg:pl-72">
          <Header onOpenSidebar={() => setSidebarOpen(true)} />
          <main className="w-full p-4 sm:p-6 lg:p-8">{children}</main>
        </div>

        <ToastStack />
      </div>
    </ToastProvider>
  );
}
