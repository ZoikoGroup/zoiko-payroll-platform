import { useEffect, useState, useCallback } from "react";
import { getCompliancePolicyVersions } from "../../../../service/superAdminService";
import { STATUS_PILL_MAP } from "../../../../components/jurisdiction/constants";
import StatusPill from "../../../../components/StatusPill";
import useActivePackForScope from "./useActivePackForScope";
import ScopePicker from "./ScopePicker";

// Versions, promoted to its own top-level nav item — same pack-scoped
// behavior as JurisdictionLayout's own Versions tab (getCompliancePolicyVersions
// by packId), just with its own Federal/state scope picker instead of
// requiring a prior Federal/State-District pack selection. Editing a
// version still happens in Federal/State-District — this is a read view.
export default function USVersionsSection({ initialScope = "" }) {
  const [scope, setScope] = useState(initialScope);
  const { pack, loading: packLoading } = useActivePackForScope(scope);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!pack) { setVersions([]); return; }
    setLoading(true);
    try {
      setVersions((await getCompliancePolicyVersions(pack.packId)) || []);
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
            Pack: <span className="font-semibold text-foreground">{pack.packId}</span>
          </p>
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
      )}
    </div>
  );
}
