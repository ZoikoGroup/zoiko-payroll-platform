import { useEffect, useState, useCallback } from "react";
import { getTaxConfigurationAudit } from "../../../../service/superAdminService";
import useActivePackForScope from "./useActivePackForScope";
import ScopePicker from "./ScopePicker";

// Audit, promoted to its own top-level nav item — same pack-scoped
// getTaxConfigurationAudit call and the same before→after diff rendering
// JurisdictionLayout's own Audit tab already uses, just with its own
// Federal/state scope picker.
export default function USAuditSection({ initialScope = "" }) {
  const [scope, setScope] = useState(initialScope);
  const { pack, loading: packLoading } = useActivePackForScope(scope);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!pack) { setAudit([]); return; }
    setLoading(true);
    try {
      setAudit((await getTaxConfigurationAudit({ jurisdictionPackId: pack.id })) || []);
    } finally {
      setLoading(false);
    }
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <ScopePicker scope={scope} onChange={setScope} />
      {packLoading || loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : !pack ? (
        <p className="rounded-xl border border-dashed border-border bg-surface-muted py-8 text-center text-xs text-foreground-disabled">
          No {scope || "Federal"} tax pack configured yet.
        </p>
      ) : (
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="mb-3 text-xs text-foreground-muted">
            Pack: <span className="font-semibold text-foreground">{pack.packId}</span> v{pack.version}
          </p>
          <div className="space-y-2">
            {audit.length === 0 ? (
              <p className="py-6 text-center text-xs text-foreground-disabled">No audit history yet.</p>
            ) : audit.map((a) => {
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
        </div>
      )}
    </div>
  );
}
