import { AlertTriangle, CheckCircle2, Inbox, Lock, Smartphone } from "lucide-react";
import { display } from "./format";

// Shared look for the Employer Statutory page — same tokens as the other
// tenant payroll pages (bg-surface / border-border / text-foreground*,
// rounded-[18px] cards, primary buttons).
export const cardCls = "bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] dark:shadow-none";
export const inputCls = "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground placeholder:text-foreground-disabled focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-60 dark:bg-surface-muted";
export const labelCls = "mb-1 block text-[12px] font-semibold text-foreground-secondary";
export const btnPrimary = "inline-flex items-center gap-1.5 rounded-[12px] bg-primary px-4 py-2 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary = "inline-flex items-center gap-1.5 rounded-[12px] border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground transition-all duration-200 hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50";
export const btnDanger = "inline-flex items-center gap-1.5 rounded-[12px] border border-error/30 px-3 py-1.5 text-[12px] font-semibold text-error transition-all duration-200 hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-50";
export const thCls = "px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-foreground-muted whitespace-nowrap";
export const tdCls = "px-3 py-2 text-[12px] text-foreground align-top";

export function SectionHeader({ title, description, children }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-[15px] font-bold text-foreground">{title}</h3>
        {description && <p className="mt-0.5 max-w-3xl text-[12px] text-foreground-muted">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Field({ id, label, required, hint, className = "", children }) {
  return (
    <div className={className}>
      <label className={labelCls} htmlFor={id}>
        {label}{required && <span className="text-error"> *</span>}
      </label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-foreground-muted">{hint}</p>}
    </div>
  );
}

export function Messages({ error, notice }) {
  if (!error && !notice) return null;
  return (
    <div className="space-y-2">
      {error && (
        <p role="alert" className="flex items-start gap-2 rounded-[12px] border border-error/20 bg-error/5 px-3 py-2 text-[12px] font-medium text-error dark:bg-error/10">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" /> <span>{error}</span>
        </p>
      )}
      {notice && (
        <p role="status" className="flex items-start gap-2 rounded-[12px] border border-success/20 bg-success/5 px-3 py-2 text-[12px] font-medium text-success dark:bg-success/10">
          <CheckCircle2 size={14} className="mt-0.5 shrink-0" aria-hidden="true" /> <span>{notice}</span>
        </p>
      )}
    </div>
  );
}

export function LoadingState({ text = "Loading…" }) {
  return <p className="py-8 text-center text-[12px] text-foreground-muted" role="status">{text}</p>;
}

export function EmptyState({ title, text, children }) {
  return (
    <div className="rounded-[14px] border border-dashed border-border bg-surface-muted/50 px-4 py-10 text-center dark:bg-surface-muted/30">
      <Inbox size={20} className="mx-auto mb-2 text-foreground-muted" aria-hidden="true" />
      <p className="text-[13px] font-semibold text-foreground">{title}</p>
      {text && <p className="mx-auto mt-1 max-w-md text-[12px] text-foreground-muted">{text}</p>}
      {children && <div className="mt-3 flex justify-center">{children}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  const forbidden = /permission/i.test(message || "");
  return (
    <div role="alert" className="rounded-[14px] border border-error/20 bg-error/5 px-4 py-8 text-center dark:bg-error/10">
      {forbidden
        ? <Lock size={20} className="mx-auto mb-2 text-error" aria-hidden="true" />
        : <AlertTriangle size={20} className="mx-auto mb-2 text-error" aria-hidden="true" />}
      <p className="mx-auto max-w-lg text-[13px] font-medium text-error">{message}</p>
      {onRetry && !forbidden && (
        <button type="button" onClick={onRetry} className={`${btnSecondary} mt-3`}>Try again</button>
      )}
    </div>
  );
}

// Explains why write controls are disabled on small screens.
export function MobileWriteNotice({ show }) {
  if (!show) return null;
  return (
    <p className="flex items-start gap-2 rounded-[12px] border border-warning/20 bg-warning/5 px-3 py-2 text-[12px] text-foreground-muted dark:bg-warning/10">
      <Smartphone size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
      <span>Changes are disabled on small screens. You can review everything here — open this page on a tablet or desktop to make changes.</span>
    </p>
  );
}

const TONES = {
  good: "bg-success/10 text-success dark:bg-success/20",
  warn: "bg-warning/10 text-warning dark:bg-warning/20",
  bad: "bg-error/10 text-error dark:bg-error/20",
  info: "bg-info/10 text-info dark:bg-info/20",
  muted: "bg-foreground-muted/10 text-foreground-muted dark:bg-foreground-muted/20",
};

const STATUS_TONE = {
  ACTIVE: "good", APPROVED: "good", PUBLISHED: "good", PAID: "good", FILED: "good", LIVE: "good", READY: "good",
  DRAFT: "warn", VERIFIED: "info", IN_PROGRESS: "info", IN_REVIEW: "info", NOT_STARTED: "muted",
  OVERDUE: "bad", BLOCKED: "bad", REJECTED: "bad", NOT_READY: "warn", LIVE_CHECKS_FAILING: "bad",
  SUPERSEDED: "muted", INACTIVE: "muted", CLOSED: "muted",
};

export function StatusBadge({ status, tone }) {
  const key = String(status || "").toUpperCase().replace(/\s+/g, "_");
  const cls = TONES[tone || STATUS_TONE[key] || "muted"];
  const text = String(status || "—").replace(/_/g, " ");
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${cls}`}>{text}</span>;
}

// Simple responsive table. columns: [{ key, label, render?(row) }]
export function DataTable({ columns, rows, rowKey = (r) => r.id, label }) {
  return (
    <div className="overflow-x-auto rounded-[14px] border border-border">
      <table className="w-full" aria-label={label}>
        <thead className="bg-surface-muted/60 dark:bg-surface-muted/30">
          <tr>{columns.map((c) => <th key={c.key} className={thCls} scope="col">{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-t border-border">
              {columns.map((c) => (
                <td key={c.key} className={tdCls}>{c.render ? c.render(row) : display(row[c.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FormActions({ busy, disabled, submitLabel, onCancel }) {
  return (
    <div className="col-span-full flex flex-wrap justify-end gap-2 pt-1">
      {onCancel && <button type="button" className={btnSecondary} onClick={onCancel} disabled={busy}>Cancel</button>}
      <button type="submit" className={btnPrimary} disabled={busy || disabled}>{busy ? "Saving…" : submitLabel}</button>
    </div>
  );
}
