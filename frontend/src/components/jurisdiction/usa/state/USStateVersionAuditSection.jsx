import { useEffect, useState, useCallback } from "react";
import { getCompliancePolicyVersions, getTaxConfigurationAudit } from "../../../../service/superAdminService";
import { STATUS_PILL_MAP } from "../../constants";
import StatusPill from "../../../StatusPill";

// Versions + Audit content for one pack, adapted from JurisdictionLayout's
// own inline Versions/Audit tab JSX (that file untouched) — same two API
// calls, same before→after diff rendering, combined into one section since
// the accordion's inner tab bar treats them as a single "Version / Audit"
// tab rather than two separate tabs.
export default function USStateVersionAuditSection({ pack }) {
  const [versions, setVersions] = useState([]);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!pack) return;
    setLoading(true);
    Promise.all([
      getCompliancePolicyVersions(pack.packId),
      getTaxConfigurationAudit({ jurisdictionPackId: pack.id }),
    ]).then(([v, a]) => { setVersions(v || []); setAudit(a || []); }).finally(() => setLoading(false));
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  if (!pack) {
    return <p className="py-6 text-center text-xs text-foreground-disabled">No pack selected yet.</p>;
  }
  if (loading) {
    return <p className="py-6 text-center text-xs text-foreground-disabled">Loading…</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">Versions</h4>
        <div className="space-y-2">
          {versions.map((v) => (
            <div
              key={v.id}
              className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-xs ${
                v.id === pack.id ? "border-primary bg-primary/5" : "border-border-light"
              }`}
            >
              <span className="font-medium text-foreground">v{v.version}</span>
              <span className="flex items-center gap-2 text-foreground-muted">
                {v.effectiveFrom} → {v.effectiveTo || "open"}
                <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
              </span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">Audit</h4>
        {audit.length === 0 ? (
          <p className="py-4 text-center text-xs text-foreground-disabled">No audit history yet.</p>
        ) : (
          <div className="space-y-2">
            {audit.map((a) => {
              const changedKeys = Object.keys({ ...(a.oldValue || {}), ...(a.newValue || {}) })
                .filter((k) => JSON.stringify(a.oldValue?.[k]) !== JSON.stringify(a.newValue?.[k]));
              return (
                <div key={a.id} className="rounded-lg border border-border-light p-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-foreground">
                      {a.action} — {a.entityType} {a.actorId ? <span className="text-foreground-disabled">· by user #{a.actorId}</span> : null}
                    </span>
                    <span className="text-foreground-disabled">{new Date(a.createdAt).toLocaleString()}</span>
                  </div>
                  {a.reason && <p className="mt-1 text-foreground-secondary">{a.reason}</p>}
                  {changedKeys.length > 0 && (
                    <div className="mt-1.5 space-y-0.5 border-t border-border-light pt-1.5">
                      {changedKeys.map((k) => (
                        <div key={k} className="flex items-center gap-1.5 font-mono text-[11px]">
                          <span className="text-foreground-disabled">{k}:</span>
                          <span className="text-error line-through">{a.oldValue?.[k] ?? "—"}</span>
                          <span className="text-foreground-disabled">→</span>
                          <span className="text-success">{a.newValue?.[k] ?? "—"}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
