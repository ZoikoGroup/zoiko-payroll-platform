import { AlertTriangle, Info, Lock } from "lucide-react";

// Shared status banner for compliance / report-template pages — the same
// border + tint as the locked-pack notice (PackRowTables.LockedPackNotice),
// with a title line, a message and optional actions / details underneath.
const TONES = {
  error: { box: "border-error/40 bg-error/5", text: "text-error", Icon: Lock },
  warning: { box: "border-warning/40 bg-warning/10", text: "text-warning", Icon: AlertTriangle },
  info: { box: "border-border bg-surface-muted", text: "text-foreground-secondary", Icon: Info },
};

export default function Notice({ tone = "info", title, children, actions = null, testId }) {
  const t = TONES[tone] || TONES.info;
  return (
    <div role={tone === "info" ? "status" : "alert"} data-testid={testId}
      className={`rounded-lg border px-3 py-2.5 text-xs ${t.box}`}>
      <div className="flex flex-wrap items-start gap-2">
        <t.Icon size={14} aria-hidden="true" className={`mt-0.5 shrink-0 ${t.text}`} />
        <div className="min-w-0 flex-1">
          {title && <p className={`font-semibold ${t.text}`}>{title}</p>}
          {children && <div className="mt-0.5 break-words text-foreground-secondary">{children}</div>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
