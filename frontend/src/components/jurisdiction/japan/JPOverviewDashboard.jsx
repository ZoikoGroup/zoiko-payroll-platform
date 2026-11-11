import { useMemo } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { getJpStatutorySummary } from "../../../service/superAdminService";
import { card, isPending, useLoad } from "./jpFormat";

// Japan pack overview (ZP-JP-ENG-001). Counts come from the selected pack's
// canonical rows; the owner decisions come from the Japan statutory summary.

const TABLES = [
  ["JP_WHT_MONTHLY", "NTA monthly table", "G1"], ["JP_WHT_CMP_EID", "Computer method: income deduction", "G1"],
  ["JP_WHT_CMP_RATE", "Computer method: rates", "G1"], ["JP_WHT_BONUS", "NTA bonus-rate table", "G1"],
  ["JP_SMR_GRADE", "SMR grades (health / pension)", "G3"], ["JP_HEALTH_RATE", "Kyokai prefectural health rates", "G3"],
  ["JP_MIN_WAGE", "Prefectural minimum wages", "G4"], ["JP_HOLIDAY", "Statutory holidays", "G4"],
];

export default function JPOverviewDashboard({ pack, rates, slabs, onReload }) {
  const [summary] = useLoad(() => getJpStatutorySummary());
  const stats = useMemo(() => {
    if (!pack) return null;
    const all = [...(rates || []), ...(slabs || [])];
    return {
      pending: all.filter(isPending).length,
      notConfigured: (rates || []).filter((r) => r.flatAmount == null && r.textValue == null
        && r.employeeRatePct == null && r.employerRatePct == null).length,
      tables: TABLES.map(([ruleType, label, gate]) => ({
        ruleType, label, gate, count: (slabs || []).filter((r) => r.ruleType === ruleType).length,
      })),
    };
  }, [pack, rates, slabs]);

  if (!stats) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-muted p-8 text-center">
        <AlertTriangle size={32} className="mx-auto text-foreground-disabled" />
        <p className="mt-3 text-sm text-foreground-muted">Select a Japan tax pack to see its configuration.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="jp-overview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Japan statutory configuration</h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Pack <span className="font-mono text-foreground">{pack.version}</span> · {pack.status} · {pack.effectiveFrom || "—"} to {pack.effectiveTo || "—"}
          </p>
        </div>
        {onReload && (
          <button type="button" onClick={onReload}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
            <RefreshCw size={13} /> Refresh
          </button>
        )}
      </div>
      <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary">
        Japan remains PLANNED. {stats.pending} row{stats.pending === 1 ? "" : "s"} marked PENDING G1 and {stats.notConfigured} parameter
        {stats.notConfigured === 1 ? "" : "s"} not configured. Japan payroll stays blocked until every release gate is evidenced and signed.
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Authority tables</h3>
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {stats.tables.map((t) => (
            <li key={t.ruleType} className="flex justify-between rounded-lg border border-border px-3 py-2 text-[12px]">
              <span>{t.label} <span className="text-foreground-muted">({t.gate})</span></span>
              <span className={t.count ? "font-mono text-foreground" : "font-semibold text-warning"}>{t.count ? `${t.count} rows` : "Empty"}</span>
            </li>
          ))}
        </ul>
      </div>
      {summary?.decisions && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
          <ul className="space-y-1 text-[12px]">
            {summary.decisions.map((d) => (
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
