import { useCallback, useEffect, useState } from "react";
import { Plug, RefreshCcw } from "lucide-react";
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

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Plug size={22} className="text-primary" /> Integrations
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">External integration status.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {data.integrations.length === 0 ? (
        <div className="bg-surface border border-border rounded-xl shadow-sm flex flex-col items-center justify-center gap-2 px-4 py-16 text-center">
          <Plug size={28} className="text-border-strong" />
          <p className="text-sm text-foreground-disabled">{data.message}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.integrations.map((it, i) => (
            <div key={i} className="bg-surface border border-border rounded-xl shadow-sm p-5">
              <p className="text-sm font-semibold text-foreground">{it.name}</p>
              <p className="text-xs text-foreground-muted mt-1">{it.status}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
