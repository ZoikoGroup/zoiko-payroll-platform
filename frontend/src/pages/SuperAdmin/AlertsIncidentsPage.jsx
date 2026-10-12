import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bell,
  RefreshCcw,
  PlayCircle,
  FileText,
  Activity,
  CreditCard,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAlerts } from "../../service/commandCenterService";

// Same token vocabulary as StatusPill usage elsewhere in the Command
// Center — high = rejected (red), medium = pending (amber), low = inactive
// (muted). Groups are rendered in this order (high first); anything a
// backend ever emits outside these three maps defensively to the muted
// state rather than crashing the page.
const SEVERITY_LABEL = {
  high: "High",
  medium: "Medium",
  low: "Low",
};
const SEVERITY_PILL = {
  high: "rejected",
  medium: "pending",
  low: "inactive",
};

const CATEGORY_META = {
  payroll_run: { label: "Payroll Runs", icon: PlayCircle },
  filing: { label: "Filings", icon: FileText },
  platform: { label: "Platform", icon: Activity },
  billing: { label: "Billing", icon: CreditCard },
};

function AlertRow({ alert }) {
  const meta = CATEGORY_META[alert.category] || { label: alert.category, icon: Activity };
  const Icon = meta.icon;
  const protectedRun = alert.category === "billing" && alert.message.includes("(protected)");
  return (
    <div className="flex items-center gap-3 border-t border-border-light px-4 py-3">
      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${protectedRun ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400" : "bg-surface-muted text-foreground-muted"}`}>
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <p className={`truncate text-sm font-medium ${protectedRun ? "text-emerald-700 dark:text-emerald-400" : "text-foreground"}`}>{alert.message}</p>
        <p className="text-xs text-foreground-muted">{meta.label}</p>
      </div>
      <div className="shrink-0">
        <StatusPill status={SEVERITY_PILL[alert.severity] || "inactive"} label={SEVERITY_LABEL[alert.severity] || alert.severity} />
      </div>
      <Link
        to={alert.link}
        className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary transition hover:bg-surface-muted"
      >
        Open →
      </Link>
    </div>
  );
}

export default function AlertsIncidentsPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAlerts();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const alerts = data?.alerts || [];
  const bySeverity = alerts.reduce((acc, alert) => {
    (acc[alert.severity] = acc[alert.severity] || []).push(alert);
    return acc;
  }, {});
  const groups = ["high", "medium", "low"].filter((s) => (bySeverity[s] || []).length > 0);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Bell size={22} className="text-primary" /> Alerts &amp; Incidents
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Unified triage across Payroll Runs, Filings, Platform, and Billing — one feed over signals each
            page already computes. Every alert links back to its source page; this never replaces them.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-4 mb-6">
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm min-w-[180px]">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-error/10 text-error">
            <ShieldAlert size={20} />
          </span>
          <div>
            <p className="text-2xl font-bold text-foreground leading-none">{data?.high_severity_count ?? "—"}</p>
            <p className="mt-1 text-xs text-foreground-muted">High-severity open</p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm min-w-[180px]">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
            <ShieldCheck size={20} />
          </span>
          <div>
            <p className="text-2xl font-bold text-foreground leading-none">{data?.total ?? "—"}</p>
            <p className="mt-1 text-xs text-foreground-muted">Total alerts across all severities</p>
          </div>
        </div>
      </div>

      {!loading && groups.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-16 text-center shadow-sm">
          <ShieldCheck size={32} className="text-border-strong" />
          <p className="text-sm font-medium text-foreground">No alerts right now.</p>
          <p className="text-xs text-foreground-disabled">
            Nothing is at risk in Payroll Runs, Filings, Platform, or Billing. The count in the sidebar updates automatically.
          </p>
        </div>
      )}

      {groups.map((severity) => (
        <div key={severity} className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto mb-4">
          <div className="px-4 py-3 border-b border-border-light flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground-secondary">
              {SEVERITY_LABEL[severity]} severity
              <span className="ml-2 text-xs font-normal text-foreground-muted">({bySeverity[severity].length} open)</span>
            </h2>
            <StatusPill status={SEVERITY_PILL[severity] || "inactive"} label={SEVERITY_LABEL[severity] || severity} />
          </div>
          {bySeverity[severity].map((alert, idx) => (
            <AlertRow key={`${severity}-${idx}`} alert={alert} />
          ))}
        </div>
      ))}
      {!loading && groups.length > 0 && (
        <p className="text-xs text-foreground-muted">
          Alerts are derived from each source page's own query logic — resolving one here is the same as resolving it
          on its source page.
        </p>
      )}
    </div>
  );
}