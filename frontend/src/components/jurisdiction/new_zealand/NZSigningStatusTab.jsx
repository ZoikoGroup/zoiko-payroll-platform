import { useCallback, useEffect, useState } from "react";
import { getNzSigningStatus } from "../../../service/superAdminService";
import { card } from "../japan/jpFormat";
import { GROUPS } from "./nzContent";
import { ErrorNote } from "./nzShared";

// Every item that still blocks activation of this pack version, grouped by
// the tab where it is edited and signed.

const groupOf = (key) => Object.entries(GROUPS).find(([, g]) => g.keys.includes(key))?.[1]?.title || "Other";

export default function NZSigningStatusTab({ pack }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    if (!pack) return;
    getNzSigningStatus(pack.id).then(setStatus).catch((e) => setError(e.message || "Could not load."));
  }, [pack]);
  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorNote message={error} />;
  if (!status) return <p className="text-[12px] text-foreground-muted">Loading…</p>;

  const byGroup = {};
  status.pendingRates.forEach((key) => { (byGroup[groupOf(key)] ||= []).push(key); });
  const empty = new Set(status.emptyValues);
  const emptyTables = status.authorityTables.filter((t) => !t.rows && !t.employerContent);

  return (
    <div className="space-y-4" data-testid="nz-signing-status">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Activation</h3>
        <p className="text-[12px] text-foreground-secondary">
          {status.activationRefusal || "Nothing blocks activation: approval by a Super Admin who made none of the edits, then Activate."}
        </p>
        {status.editors.length > 0 && (
          <p className="mt-1 text-[11px] text-foreground-muted">Editors of this version (user ids): {status.editors.join(", ")}</p>
        )}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Parameters still pending ({status.pendingRates.length})</h3>
        {status.pendingRates.length === 0 ? (
          <p className="text-[12px] text-success">All parameters signed.</p>
        ) : (
          Object.entries(byGroup).map(([group, keys]) => (
            <div key={group} className="mb-2">
              <p className="text-[12px] font-semibold text-foreground">{group}</p>
              <ul className="mt-1 flex flex-wrap gap-1">
                {keys.map((key) => (
                  <li key={key} className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${empty.has(key)
                    ? "border-error/40 bg-error/5 text-error" : "border-warning/40 bg-warning/10 text-warning"}`}
                    title={empty.has(key) ? "No value yet" : "Value present, not signed"}>
                    {key}
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Table rows still pending</h3>
        {Object.keys(status.pendingSlabsByRuleType).length === 0 ? (
          <p className="text-[12px] text-success">All table rows signed.</p>
        ) : (
          <ul className="space-y-1 text-[12px]">
            {Object.entries(status.pendingSlabsByRuleType).map(([ruleType, count]) => (
              <li key={ruleType} className="flex justify-between"><span className="font-mono">{ruleType}</span><span>{count}</span></li>
            ))}
          </ul>
        )}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Empty authority tables ({emptyTables.length})</h3>
        {emptyTables.length === 0 ? (
          <p className="text-[12px] text-success">Every required authority table has rows.</p>
        ) : (
          <ul className="space-y-1 text-[12px]">
            {emptyTables.map((t) => (
              <li key={t.ruleType} className="flex justify-between">
                <span>{t.table.replaceAll("_", " ")}</span><span className="text-warning">{t.gate}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
