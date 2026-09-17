import { useCallback, useEffect, useState } from "react";
import { ShieldAlert, RefreshCcw } from "lucide-react";
import { useToast } from "../../context/ToastContext";
import { getSecurityAuditLog } from "../../service/commandCenterService";

const SOURCE_LABELS = { compliance: "Compliance", billing: "Billing", assist: "Assist" };

export default function SecurityAuditPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState({ entries: [], page: 1, page_size: 50, returned: 0 });
  const [loading, setLoading] = useState(true);

  const [source, setSource] = useState("");
  const [actorId, setActorId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSecurityAuditLog({
        source: source || undefined,
        actor_id: actorId || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        page,
      });
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, [source, actorId, startDate, endDate, page]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [source, actorId, startDate, endDate]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <ShieldAlert size={22} className="text-primary" /> Security & Audit
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Merged, append-only audit trail across compliance, billing, and assist.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Sources</option>
          <option value="compliance">Compliance</option>
          <option value="billing">Billing</option>
          <option value="assist">Assist</option>
        </select>
        <input
          type="number"
          placeholder="Actor ID"
          value={actorId}
          onChange={(e) => setActorId(e.target.value)}
          className="w-32 rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
        />
        <input
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
        />
        <input
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
        />
      </div>

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Entity</th>
              <th className="px-4 py-3">Actor</th>
            </tr>
          </thead>
          <tbody>
            {data.entries.map((e, i) => (
              <tr key={i} className="border-t border-border-light align-top">
                <td className="px-4 py-3 text-foreground-muted whitespace-nowrap">{e.timestamp ? new Date(e.timestamp).toLocaleString() : "—"}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full bg-slate-100 dark:bg-white/10 px-2 py-0.5 text-xs font-semibold text-foreground-secondary">
                    {SOURCE_LABELS[e.source] || e.source}
                  </span>
                </td>
                <td className="px-4 py-3 font-medium text-foreground">{e.action}</td>
                <td className="px-4 py-3 text-foreground-secondary">{e.entity_type} {e.entity_id != null ? `#${e.entity_id}` : ""}</td>
                <td className="px-4 py-3 text-foreground-muted">{e.actor_id ?? "system"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && data.entries.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <ShieldAlert size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No audit events match these filters.</p>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between mt-3 text-sm text-foreground-muted">
        <span>Page {data.page} · {data.returned} shown</span>
        <div className="flex gap-2">
          <button disabled={page === 1} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button>
          <button disabled={data.returned < data.page_size} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button>
        </div>
      </div>
    </div>
  );
}
