import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, Link2, Plug, RefreshCcw } from "lucide-react";
import { listIntegrations } from "../../service/commandCenterService";
import { formatDateTime } from "../../utils/time";

const CATEGORY_ORDER = ["Payments", "Messaging", "Identity", "Security", "Infrastructure", "Monitoring", "AI"];

function Status({ it }) {
  if (it.configured) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap rounded-full bg-success-light px-2.5 py-1 text-xs font-semibold text-success">
        <CheckCircle2 size={13} /> {it.status}
      </span>
    );
  }
  const required = !it.optional;
  return (
    <span className={`flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${
      required ? "bg-warning-light text-warning" : "bg-surface-muted text-foreground-muted"}`}>
      {required ? <AlertTriangle size={13} /> : <CircleDashed size={13} />} {it.status}
    </span>
  );
}

export default function IntegrationsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await listIntegrations());
    } catch (err) {
      setError(err?.message || "Integrations could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react-hooks/set-state-in-effect

  const groups = useMemo(() => {
    const by = {};
    for (const it of data?.integrations || []) (by[it.category || "Other"] ||= []).push(it);
    return Object.entries(by).sort(([a], [b]) => {
      const ia = CATEGORY_ORDER.indexOf(a); const ib = CATEGORY_ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [data]);

  const missing = data?.summary?.missingRequired || [];

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <Plug size={22} className="text-primary" /> Integrations
          </h1>
          <p className="mt-0.5 text-sm text-foreground-muted">
            External services this deployment uses. Status reflects configuration; no secrets are shown.
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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-surface" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-border bg-surface p-4 shadow-sm">
              <p className="text-xs text-foreground-muted">Configured</p>
              <p className="mt-1 text-2xl font-bold text-foreground">
                {data.summary?.configured ?? 0}<span className="text-base font-medium text-foreground-muted"> / {data.summary?.total ?? 0}</span>
              </p>
            </div>
            <div className={`rounded-xl border p-4 shadow-sm sm:col-span-2 ${
              missing.length ? "border-warning/40 bg-warning-light" : "border-success/40 bg-success-light"}`}>
              <p className={`text-sm font-semibold ${missing.length ? "text-warning" : "text-success"}`}>
                {missing.length ? "Required integrations missing" : "All required integrations configured"}
              </p>
              {missing.length > 0 && <p className="mt-1 text-xs text-foreground-secondary">{missing.join(", ")}</p>}
            </div>
          </div>

          <div className="space-y-6">
            {groups.map(([category, items]) => (
              <section key={category}>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-foreground-muted">{category}</h2>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {items.map((it) => (
                    <div key={it.slug} className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 shadow-sm">
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
                          <Link2 size={14} className="shrink-0 text-border-strong" /> {it.name}
                          {it.optional && <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-medium text-foreground-muted">optional</span>}
                        </p>
                        <p className="mt-1.5 text-xs text-foreground-muted">{it.description}</p>
                      </div>
                      <div className="flex"><Status it={it} /></div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <p className="mt-4 text-xs text-foreground-disabled">
            {data.message}{data.checked_at ? ` · checked ${formatDateTime(data.checked_at)}` : ""}
          </p>
        </>
      )}
    </div>
  );
}
