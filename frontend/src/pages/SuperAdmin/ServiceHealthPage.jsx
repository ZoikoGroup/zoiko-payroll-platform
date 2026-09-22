import { useCallback, useEffect, useState } from "react";
import { Activity, RefreshCcw, CheckCircle2, XCircle, HelpCircle, Database } from "lucide-react";
import { useToast } from "../../context/ToastContext";
import { getServiceHealth } from "../../service/commandCenterService";

const STATE_STYLE = {
  healthy: { icon: CheckCircle2, color: "text-success", bg: "bg-success-light", label: "Healthy" },
  error: { icon: XCircle, color: "text-error", bg: "bg-error-light", label: "Error" },
  unknown: { icon: HelpCircle, color: "text-foreground-muted", bg: "bg-surface-muted", label: "Unknown" },
};

function StateCard({ title, state, children }) {
  const style = STATE_STYLE[state] || STATE_STYLE.unknown;
  const Icon = style.icon;
  return (
    <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${style.bg} ${style.color}`}>
          <Icon size={13} /> {style.label}
        </span>
      </div>
      <div className="text-sm text-foreground-muted space-y-1">{children}</div>
    </div>
  );
}

export default function ServiceHealthPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getServiceHealth();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]); // eslint-disable-line react-hooks/set-state-in-effect

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Activity size={22} className="text-primary" /> Service Health
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Real signals only — an unreported job shows as Unknown, never Healthy.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <StateCard title="Database" state={data.database?.status}>
            <Database size={14} className="inline mr-1.5 -mt-0.5" />
            {data.database?.status === "healthy"
              ? `Latency ${data.database.latency_ms} ms`
              : data.database?.error || "No response."}
          </StateCard>

          {data.scheduled_jobs?.map((job) => (
            <StateCard key={job.job} title={job.job} state={job.state}>
              {job.state === "unknown" && <p>{job.detail}</p>}
              {job.state === "error" && (
                <>
                  <p>Last run: {new Date(job.last_run_at).toLocaleString()}</p>
                  <p className="text-error">{job.error}</p>
                </>
              )}
              {job.state === "healthy" && (
                <>
                  <p>Last run: {new Date(job.last_run_at).toLocaleString()}</p>
                  {job.last_success_at && <p>Last success: {new Date(job.last_success_at).toLocaleString()}</p>}
                </>
              )}
            </StateCard>
          ))}
        </div>
      )}

      {data?.checked_at && (
        <p className="mt-4 text-xs text-foreground-disabled">Checked at {new Date(data.checked_at).toLocaleString()}</p>
      )}
    </div>
  );
}
