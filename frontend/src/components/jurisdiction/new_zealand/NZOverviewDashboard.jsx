import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { getNzDecisions, getNzSigningStatus } from "../../../service/superAdminService";
import { card } from "../japan/jpFormat";
import { ErrorNote } from "./nzShared";
import NZSeedDraftPanel from "./NZSeedDraftPanel";

// New Zealand pack overview (ZP-NZ-ENG-001, decision Option 1): what still
// blocks activation, straight from the backend's signing status — pending
// rows, values not configured, empty authority tables, who edited this
// version (none of them may approve it) — and the owner decisions D-1..D-7.

export default function NZOverviewDashboard({ pack, onReload }) {
  const [status, setStatus] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    if (!pack) return;
    getNzSigningStatus(pack.id)
      .then((data) => { setStatus(data); setError(null); })
      .catch((e) => setError(e.message || "Could not load the signing status."));
    getNzDecisions().then((rows) => setDecisions(rows || [])).catch(() => setDecisions([]));
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  if (!pack) return <NZSeedDraftPanel />;

  const pendingSlabs = status ? Object.values(status.pendingSlabsByRuleType || {}).reduce((a, b) => a + b, 0) : 0;
  const ready = status && !status.activationRefusal;

  return (
    <div className="space-y-6" data-testid="nz-overview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">New Zealand statutory configuration</h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Pack <span className="font-mono text-foreground">{pack.packId} v{pack.version}</span> · {pack.status} ·{" "}
            {pack.effectiveFrom || "—"} to {pack.effectiveTo || "open"}
          </p>
        </div>
        <button type="button" onClick={() => { load(); onReload?.(); }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <ErrorNote message={error} />
      {status && (
        <div className={`rounded-xl border p-3 text-[12px] ${ready ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10"}`}
          data-testid="nz-activation-state">
          {ready ? (
            <span className="inline-flex items-center gap-1.5 text-success">
              <CheckCircle2 size={14} /> Every row is signed and every authority table filled. A Super Admin who made
              none of the edits may approve, then activate.
            </span>
          ) : (
            <span className="text-foreground-secondary">
              <strong>Activation is refused:</strong> {status.activationRefusal}
            </span>
          )}
        </div>
      )}
      {status && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className={card}>
            <p className="text-[11px] uppercase text-foreground-muted">Parameters pending</p>
            <p className="mt-1 text-2xl font-bold text-foreground">{status.pendingRates.length}</p>
            <p className="text-[11px] text-foreground-muted">{status.emptyValues.length} with no value yet</p>
          </div>
          <div className={card}>
            <p className="text-[11px] uppercase text-foreground-muted">Table rows pending</p>
            <p className="mt-1 text-2xl font-bold text-foreground">{pendingSlabs}</p>
            <p className="text-[11px] text-foreground-muted">bands, tax codes, earning classes, authority rows</p>
          </div>
          <div className={card}>
            <p className="text-[11px] uppercase text-foreground-muted">Editors of this version</p>
            <p className="mt-1 text-2xl font-bold text-foreground">{status.editors.length}</p>
            <p className="text-[11px] text-foreground-muted">none of them may approve it</p>
          </div>
        </div>
      )}
      {status && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Authority tables</h3>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {status.authorityTables.map((t) => (
              <li key={t.ruleType} className="flex justify-between rounded-lg border border-border px-3 py-2 text-[12px]">
                <span>
                  {t.table.replaceAll("_", " ")} <span className="text-foreground-muted">({t.gate}{t.employerContent ? ", employer" : ""})</span>
                </span>
                <span className={t.rows ? "font-mono text-foreground" : "font-semibold text-warning"}>{t.rows ? `${t.rows} rows` : "Empty"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {decisions.length > 0 && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
          <ul className="space-y-1 text-[12px]">
            {decisions.map((d) => (
              <li key={d.key} className="flex justify-between gap-3">
                <span>{d.key} — {d.label}</span>
                <span className={d.state === "RECORDED" ? "text-success" : "text-warning"}>{d.state}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
