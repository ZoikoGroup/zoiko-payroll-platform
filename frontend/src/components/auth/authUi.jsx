import { AlertCircle, ArrowLeft, CheckCircle2, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";

// Shared building blocks for the sign-in screens (Login, Reset Password,
// set-new-password, the MFA step) so every form in AuthLayout looks the same.

// Text input. `withIcon` leaves room for a leading icon, `withTrailing` for a
// trailing button (show/hide password).
export function authInputClass({ withIcon = false, withTrailing = false } = {}) {
  return [
    "w-full rounded-lg border border-slate-200 bg-white py-2.5 text-[15px] text-slate-900",
    "placeholder:text-slate-400 outline-none transition-colors",
    "focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15",
    withIcon ? "pl-11" : "pl-4",
    withTrailing ? "pr-12" : "pr-4",
  ].join(" ");
}

export const AUTH_LABEL = "mb-2 block text-[14px] font-semibold text-slate-800";

export function AuthTitle({ title, subtitle }) {
  return (
    <div className="mb-6">
      <h2 className="text-[30px] font-extrabold leading-tight tracking-[-0.02em] text-slate-900">{title}</h2>
      {subtitle && <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{subtitle}</p>}
    </div>
  );
}

const ALERT_TONES = {
  error: { box: "border-red-200 bg-red-50 text-red-700", role: "alert", Icon: AlertCircle },
  warning: { box: "border-amber-200 bg-amber-50 text-amber-800", role: "status", Icon: AlertCircle },
  success: { box: "border-emerald-200 bg-emerald-50 text-emerald-800", role: "status", Icon: CheckCircle2 },
};

export function AuthAlert({ tone = "error", children }) {
  const { box, role, Icon } = ALERT_TONES[tone] || ALERT_TONES.error;
  return (
    <div role={role} className={`mb-4 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm ${box}`}>
      <Icon size={16} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

export function AuthPrimaryButton({ busy = false, busyLabel, children, className = "", ...props }) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className={`flex w-full items-center justify-center gap-2 rounded-lg bg-[#1260e6] py-3 text-[16px] font-semibold text-white shadow-[0_8px_20px_-8px_rgba(18,96,230,0.7)] transition-colors hover:bg-[#0e52c7] disabled:cursor-not-allowed disabled:bg-blue-300 disabled:shadow-none ${className}`}
    >
      {busy && <Loader2 size={18} className="animate-spin" />}
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

// Full-screen result panel (email sent, password updated, link invalid).
export function AuthResult({ tone = "success", title, children, action }) {
  const Icon = tone === "success" ? CheckCircle2 : AlertCircle;
  return (
    <div className="py-2 text-center">
      <span className={`mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full ${
        tone === "success" ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600"}`}>
        <Icon size={30} />
      </span>
      <h2 className="text-[26px] font-extrabold tracking-[-0.02em] text-slate-900">{title}</h2>
      <div className="mt-2 text-[15px] leading-relaxed text-slate-600">{children}</div>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function BackToSignIn() {
  return (
    <div className="mt-6 text-center">
      <Link to="/login" className="inline-flex items-center gap-1.5 text-[14px] font-medium text-slate-700 hover:text-slate-900">
        <ArrowLeft size={15} />
        Back to sign in
      </Link>
    </div>
  );
}
