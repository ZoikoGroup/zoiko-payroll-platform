// Shared bits for the security & privacy pages (ZP-PRIV D/E/F). Same token
// vocabulary as the Support Access pages.
import { STEP_UP_REQUIRED } from "../utils/stepUp";

export const card = "rounded-xl border border-border-light bg-surface p-5 shadow-sm";
export const btn = "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50";
export const primary = `${btn} bg-blue-600 text-white hover:bg-blue-700`;
export const subtle = `${btn} border border-border-light text-foreground hover:bg-surface-muted`;
export const danger = `${btn} bg-red-600 text-white hover:bg-red-700`;
export const input = "w-full rounded-lg border border-border-light bg-surface px-3 py-2 text-sm text-foreground";

export function Banner({ tone = "info", children }) {
  const tones = {
    info: "bg-blue-50 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200",
    error: "bg-red-50 text-red-800 dark:bg-red-900/30 dark:text-red-200",
    success: "bg-emerald-50 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200",
    warning: "bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200",
  };
  return <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg p-3 text-sm ${tones[tone]}`}>{children}</div>;
}

// Neutral fail-closed state for 403/404: never the raw server message.
export function NotAvailable({ what = "This view" }) {
  return (
    <div className={`${card} text-sm text-foreground-secondary`}>
      {what} is not available for your account.
    </div>
  );
}

export function Badge({ className = "", children }) {
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}

// Error text for an action that failed. 403/404 stay neutral; a cancelled
// step-up says so instead of echoing the server.
export function actionError(err, fallback = "That did not work.") {
  if (err?.errorCode === STEP_UP_REQUIRED) return "This action needs a fresh verification code. Try again and complete the prompt.";
  if (err?.status === 403) return "You do not have permission for this action.";
  if (err?.status === 404) return "That item is no longer available.";
  return err?.message || fallback;
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-2 border-b border-border-light">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          aria-selected={value === t.key}
          onClick={() => onChange(t.key)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${value === t.key ? "border-blue-600 font-semibold text-foreground" : "border-transparent text-foreground-secondary"}`}
        >
          {t.label}
          {t.count ? <span className="ml-1.5 rounded-full bg-blue-600 px-1.5 text-xs text-white">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export const RESULT_BADGE = {
  allow: "bg-emerald-100 text-emerald-800",
  deny: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-800",
};
