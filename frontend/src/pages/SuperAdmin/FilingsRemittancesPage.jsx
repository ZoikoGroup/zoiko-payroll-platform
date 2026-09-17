import { useCallback, useEffect, useState } from "react";
import { FileText, RefreshCcw, Info } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listFilingsRemittances } from "../../service/commandCenterService";

const STATUS_PILL_MAP = {
  DRAFT: "inactive",
  VALIDATED: "pending",
  BLOCKED_EXTERNAL: "rejected",
  QUEUED: "pending",
  TRANSMITTED: "approved",
  ACKNOWLEDGED: "active",
  REJECTED: "rejected",
};

const JURISDICTION_LABELS = { germany: "Germany" };

export default function FilingsRemittancesPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState({ jurisdictions: {}, known_gaps: [] });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listFilingsRemittances();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const jurisdictionEntries = Object.entries(data.jurisdictions || {});

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FileText size={22} className="text-primary" /> Filings & Remittances
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Cross-organization statutory filing status, by jurisdiction.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {data.known_gaps?.length > 0 && (
        <div className="mb-6 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
          <Info size={16} className="mt-0.5 shrink-0" />
          <ul className="list-disc pl-4 space-y-1">
            {data.known_gaps.map((gap, i) => <li key={i}>{gap}</li>)}
          </ul>
        </div>
      )}

      {jurisdictionEntries.map(([key, section]) => (
        <div key={key} className="mb-6">
          <h2 className="text-sm font-semibold text-foreground-secondary mb-3">
            {JURISDICTION_LABELS[key] || key} ({section.total})
          </h2>
          <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
            <table className="w-full text-sm min-w-[900px]">
              <thead className="bg-background text-left text-xs text-foreground-muted">
                <tr>
                  <th className="px-4 py-3">Organization</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Period</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Blocked Reason</th>
                  <th className="px-4 py-3">Updated</th>
                </tr>
              </thead>
              <tbody>
                {section.filings.map((f) => (
                  <tr key={f.transmission_id} className="border-t border-border-light">
                    <td className="px-4 py-3 font-medium text-foreground">{f.organization_name}</td>
                    <td className="px-4 py-3 text-foreground-secondary">{f.transmission_type}</td>
                    <td className="px-4 py-3 text-foreground-muted">{f.period_start} – {f.period_end}</td>
                    <td className="px-4 py-3"><StatusPill status={STATUS_PILL_MAP[f.status] || "inactive"} label={f.status} /></td>
                    <td className="px-4 py-3 text-foreground-muted">{f.blocked_reason || "—"}</td>
                    <td className="px-4 py-3 text-foreground-muted">{f.updated_at ? new Date(f.updated_at).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {section.filings.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
                <p className="text-sm text-foreground-disabled">No filings for this jurisdiction.</p>
              </div>
            )}
          </div>
        </div>
      ))}

      {jurisdictionEntries.length === 0 && !loading && (
        <p className="text-sm text-foreground-disabled">No jurisdictions with filing data yet.</p>
      )}
    </div>
  );
}
