import { useEffect, useState } from "react";
import Modal from "../Modal";
import { getPackImpactPreview } from "../../service/superAdminService";

// Super Admin UI Part 11 (§19, 2026-09-09) — "before publishing this
// pack, who does it actually affect?" A tax-pack org only counts as
// genuinely affected if it's opted into canonical tracking (an org
// that's NOT opted in reads its own cached copy and is completely
// unaffected by this pack's own status change) — the backend already
// makes this distinction, this just displays it honestly rather than
// implying every jurisdiction-matching org is impacted.
export default function ImpactPreviewModal({ pack, onClose }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getPackImpactPreview(pack.id).then(setPreview).catch((err) => setError(err.message || "Failed to load impact preview."));
  }, [pack.id]);

  return (
    <Modal title={`Impact Preview — ${pack.packId} v${pack.version}`} onClose={onClose} maxWidth="max-w-2xl">
      {error && <p className="text-sm text-error">{error}</p>}
      {!preview && !error && <p className="text-sm text-foreground-muted">Loading…</p>}
      {preview && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg border border-border p-3">
              <p className="text-2xl font-bold text-foreground">{preview.totalOrganizationsGenuinelyAffected}</p>
              <p className="text-xs text-foreground-muted mt-1">of {preview.totalOrganizationsEligible} eligible orgs genuinely affected</p>
            </div>
            <div className="rounded-lg border border-border p-3">
              <p className="text-2xl font-bold text-foreground">{preview.totalActiveEmployeesAffected}</p>
              <p className="text-xs text-foreground-muted mt-1">active employees</p>
            </div>
            <div className="rounded-lg border border-border p-3">
              <p className="text-2xl font-bold text-foreground">{preview.totalUnfinalizedRunsAffected}</p>
              <p className="text-xs text-foreground-muted mt-1">unfinalized (Draft/Review) runs</p>
            </div>
          </div>

          {preview.organizations.length === 0 ? (
            <p className="text-sm text-foreground-disabled">No organization currently matches this pack's jurisdiction.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead className="bg-surface-muted text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left">Organization</th>
                    <th className="px-3 py-2 text-left">Canonical Tracking</th>
                    <th className="px-3 py-2 text-right">Active Employees</th>
                    <th className="px-3 py-2 text-right">Unfinalized Runs</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.organizations.map((org) => (
                    <tr key={org.id} className="border-t border-border">
                      <td className="px-3 py-2">{org.organizationName} <span className="text-foreground-disabled">({org.organizationCode})</span></td>
                      <td className="px-3 py-2">
                        {org.optedIntoCanonicalTracking ? (
                          <span className="text-success font-semibold">Opted in</span>
                        ) : (
                          <span className="text-foreground-disabled">Not opted in — unaffected</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">{org.activeEmployeeCount}</td>
                      <td className="px-3 py-2 text-right">{org.unfinalizedRunCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
