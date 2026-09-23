import { useCallback, useEffect, useState } from "react";
import { Plug, RefreshCcw, CheckCircle2, CircleDashed, Link2 } from "lucide-react";
import { useToast } from "../../context/ToastContext";
import { listIntegrations } from "../../service/commandCenterService";

export default function IntegrationsPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState({ integrations: [], message: "" });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listIntegrations();
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
            <Plug size={22} className="text-primary" /> Integrations
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">External services this deployment is connected to.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {data.integrations.map((it, i) => (
          <div
            key={`${it.slug || i}`}
            className="bg-surface border border-border rounded-xl shadow-sm p-5 flex items-start justify-between gap-4"
          >
            <div>
              <p className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Link2 size={14} className="text-border-strong" />
                {it.name}
              </p>
              <p className="text-xs text-foreground-muted mt-1.5">{it.description}</p>
            </div>
            {it.configured ? (
              <span className="flex items-center gap-1.5 rounded-full bg-success-light px-2.5 py-1 text-xs font-semibold text-success whitespace-nowrap">
                <CheckCircle2 size={13} /> {it.status || "Connected"}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-1 text-xs font-semibold text-foreground-muted whitespace-nowrap">
                <CircleDashed size={13} /> {it.status || "Not configured"}
              </span>
            )}
          </div>
        ))}
      </div>

      {data.message && (
        <p className="mt-4 text-xs text-foreground-disabled">{data.message}</p>
      )}
    </div>
  );
}