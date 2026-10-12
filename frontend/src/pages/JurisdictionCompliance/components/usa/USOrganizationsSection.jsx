import { useEffect, useState, useCallback } from "react";
import {
  getCompliancePolicyOrganizations, getCompliancePolicyEligibleOrganizations, assignCompliancePolicy,
} from "../../../../service/superAdminService";
import OrgsTab from "../../../../components/jurisdiction/OrgsTab";
import AssignOrgsModal from "../../../../components/jurisdiction/AssignOrgsModal";
import { useToast } from "../../../../context/ToastContext";
import useActivePackForScope from "./useActivePackForScope";
import ScopePicker from "./ScopePicker";

// Organizations, promoted to its own top-level nav item per the USA
// compliance UI/UX refactor — but pack-scoped exactly as it already is
// inside JurisdictionLayout (confirmed with the user: there is no backend
// concept of "all US organizations across every state pack at once").
// Reuses the same OrgsTab/AssignOrgsModal components and the same
// getCompliancePolicyOrganizations/getCompliancePolicyEligibleOrganizations/
// assignCompliancePolicy calls JurisdictionLayout's own Organizations tab
// already makes — just with its own scope picker (Federal or a
// configured state) instead of requiring you to first navigate into
// Federal/State-District and select a pack there.
export default function USOrganizationsSection({ initialScope = "" }) {
  const { addToast } = useToast() || {};
  const [scope, setScope] = useState(initialScope);
  const { pack, loading: packLoading } = useActivePackForScope(scope);
  const [orgs, setOrgs] = useState([]);
  const [eligibleOrgs, setEligibleOrgs] = useState([]);
  const [showAssign, setShowAssign] = useState(false);
  const [assignIds, setAssignIds] = useState(new Set());
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!pack) { setOrgs([]); setEligibleOrgs([]); return; }
    setLoading(true);
    try {
      const [assigned, eligible] = await Promise.all([
        getCompliancePolicyOrganizations(pack.id),
        getCompliancePolicyEligibleOrganizations(pack.id),
      ]);
      setOrgs(assigned || []);
      setEligibleOrgs(eligible || []);
    } finally {
      setLoading(false);
    }
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  async function handleAssign() {
    try {
      await assignCompliancePolicy(pack.id, Array.from(assignIds));
      addToast?.("Organizations assigned.", "success");
      setShowAssign(false);
      setAssignIds(new Set());
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to assign organizations.", "error");
    }
  }

  return (
    <div>
      <ScopePicker scope={scope} onChange={setScope} />
      {packLoading || loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : !pack ? (
        <p className="rounded-xl border border-dashed border-border bg-surface-muted py-8 text-center text-xs text-foreground-disabled">
          No {scope || "Federal"} tax pack configured yet — create one under {scope ? "State / District" : "Federal"} first.
        </p>
      ) : (
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="mb-3 text-xs text-foreground-muted">
            Pack: <span className="font-semibold text-foreground">{pack.packId}</span> v{pack.version}
          </p>
          <OrgsTab orgs={orgs} onAssign={() => setShowAssign(true)} />
        </div>
      )}
      {showAssign && (
        <AssignOrgsModal
          eligibleOrgs={eligibleOrgs}
          assignedIds={new Set(orgs.map((o) => o.id))}
          selected={assignIds}
          setSelected={setAssignIds}
          onClose={() => { setShowAssign(false); setAssignIds(new Set()); }}
          onSave={handleAssign}
        />
      )}
    </div>
  );
}
