import { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, CheckCircle2, Clock, Database, HelpCircle, RefreshCcw, XCircle,
} from "lucide-react";
import { getServiceHealth } from "../../service/commandCenterService";
import { formatDateTime, parseUtc } from "../../utils/time";

const STATE_STYLE = {
  healthy: { icon: CheckCircle2, color: "text-success", bg: "bg-success-light", label: "Healthy" },
  stale: { icon: Clock, color: "text-warning", bg: "bg-warning-light", label: "Missed schedule" },
  error: { icon: XCircle, color: "text-error", bg: "bg-error-light", label: "Error" },
  unknown: { icon: HelpCircle, color: "text-foreground-muted", bg: "bg-surface-muted", label: "Not run yet" },
};

const OVERALL = {
  healthy: { text: "All systems healthy", cls: "border-success/40 bg-success-light text-success", icon: CheckCircle2 },
  degraded: { text: "Some jobs need attention", cls: "border-warning/40 bg-warning-light text-warning", icon: AlertTriangle },
  error: { text: "Service problem detected", cls: "border-error/40 bg-error-light text-error", icon: XCircle },
};

function every(seconds) {
  if (!seconds) return "";
  if (seconds < 3600) return `every ${Math.round(seconds / 60)} min`;
  const h = Math.round(seconds / 3600);
  return h === 24 ? "daily" : `every ${h} h`;
}

function ago(value) {
  const d = parseUtc(value);
  if (!d) return "—";
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function Badge({ state }) {
  const style = STATE_STYLE[state] || STATE_STYLE.unknown;
  const Icon = style.icon;
  return (
    <span className={`flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${style.bg} ${style.color}`}>
      <Icon size={13} /> {style.label}
    </span>
  );
}

function SummaryTile({ label, value, tone }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
      <p className="text-xs text-foreground-muted">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

export default function ServiceHealthPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getServiceHealth());
    } catch (err) {
      setError(err?.message || "Service health could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(); // eslint-disable-line react-hooks/set-state-in-effect
    const id = setInterval(load, 60000); // refresh every minute
    return () => clearInterval(id);
  }, [load]);

  const overall = data ? OVERALL[data.overall] || OVERALL.degraded : null;
  const OverallIcon = overall?.icon;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <Activity size={22} className="text-primary" /> Service Health
          </h1>
          <p className="mt-0.5 text-sm text-foreground-muted">
            Live signals from this server: database and scheduled jobs. A job that has not reported is never shown as healthy.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-white/5"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-error/40 bg-error-light px-4 py-3 text-sm text-error">{error}</div>
      )}

      {!data && loading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-xl border border-border bg-surface" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className={`mb-4 flex items-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold ${overall.cls}`}>
            <OverallIcon size={16} /> {overall.text}
          </div>

          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryTile label="Healthy jobs" value={data.summary?.healthy ?? 0} tone="text-success" />
            <SummaryTile label="Missed schedule" value={data.summary?.stale ?? 0} tone={data.summary?.stale ? "text-warning" : "text-foreground-muted"} />
            <SummaryTile label="Errors" value={data.summary?.error ?? 0} tone={data.summary?.error ? "text-error" : "text-foreground-muted"} />
            <SummaryTile label="Not run yet" value={data.summary?.unknown ?? 0} tone="text-foreground-muted" />
          </div>

          <div className="mb-6 rounded-xl border border-border bg-surface p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Database size={15} className="text-primary" /> Database
              </h3>
              <Badge state={data.database?.status} />
            </div>
            <p className="mt-2 text-sm text-foreground-muted">
              {data.database?.status === "healthy"
                ? `Responding · round trip ${data.database.latency_ms} ms`
                : `Not responding${data.database?.error ? ` (${data.database.error})` : ""}.`}
            </p>
          </div>

          <h2 className="mb-3 text-sm font-semibold text-foreground">Scheduled jobs</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.scheduled_jobs?.map((job) => (
              <div key={job.job} className="flex flex-col rounded-xl border border-border bg-surface p-5 shadow-sm">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold text-foreground">{job.label || job.job}</h3>
                  <Badge state={job.state} />
                </div>
                <p className="mb-3 text-xs text-foreground-muted">{job.description} <span className="whitespace-nowrap">· runs {every(job.interval_seconds)}</span></p>
                <dl className="mt-auto space-y-1 text-xs">
                  <div className="flex justify-between gap-2">
                    <dt className="text-foreground-muted">Last run</dt>
                    <dd className="text-foreground" title={formatDateTime(job.last_run_at)}>{job.last_run_at ? ago(job.last_run_at) : "—"}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-foreground-muted">Last success</dt>
                    <dd className="text-foreground" title={formatDateTime(job.last_success_at)}>{job.last_success_at ? ago(job.last_success_at) : "—"}</dd>
                  </div>
                </dl>
                {job.state === "error" && job.error && (
                  <p className="mt-3 break-words rounded-lg bg-error-light px-2.5 py-1.5 text-xs text-error">{job.error}</p>
                )}
                {(job.state === "unknown" || job.state === "stale") && job.detail && (
                  <p className="mt-3 text-xs text-foreground-muted">{job.detail}</p>
                )}
              </div>
            ))}
          </div>

          <p className="mt-4 text-xs text-foreground-disabled">
            Checked {formatDateTime(data.checked_at)} · refreshes every minute
          </p>
        </>
      )}
    </div>
  );
}
