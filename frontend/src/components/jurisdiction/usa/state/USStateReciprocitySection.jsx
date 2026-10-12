import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { getReciprocityRules } from "../../../../service/superAdminService";
import { toUsJurisdictionCode } from "./usStateAbbreviations";

// Client-filtered view of the platform-wide reciprocity rules for just this
// state (either side of the resident/work pair) — getReciprocityRules has
// no server-side filter (confirmed against ReciprocityRulesPanel.jsx,
// untouched), so filtering happens here. Read-only; adding/editing an
// agreement still happens on the full "Reciprocity & Sourcing" tab (linked
// below) since a rule isn't owned by a single state.
export default function USStateReciprocitySection({ stateName }) {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    getReciprocityRules().then(setRules).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const code = toUsJurisdictionCode(stateName);
  const filtered = code
    ? rules.filter((r) => r.residentJurisdiction === code || r.workJurisdiction === code)
    : [];

  return (
    <div>
      <div className="mb-3 flex items-start justify-between gap-3 flex-wrap">
        <p className="text-xs text-foreground-muted">
          Directional resident/work state agreements involving {stateName}.
        </p>
        <Link to="/super-admin/compliance/united-states?section=reciprocity" className="shrink-0 text-xs font-semibold text-primary hover:underline">
          Manage all agreements →
        </Link>
      </div>
      {loading ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : !code ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">
          "{stateName}" doesn't match a known state code — check reciprocity agreements on the full tab.
        </p>
      ) : filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">No reciprocity agreements involve {stateName} yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="px-3 py-2.5">Resident</th>
                <th className="px-3 py-2.5">Work</th>
                <th className="px-3 py-2.5">Type</th>
                <th className="px-3 py-2.5">Certificate</th>
                <th className="px-3 py-2.5">Required</th>
                <th className="px-3 py-2.5">Effective</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-border-light last:border-0">
                  <td className="px-3 py-2.5 font-medium text-foreground">{r.residentJurisdiction}</td>
                  <td className="px-3 py-2.5 font-medium text-foreground">{r.workJurisdiction}</td>
                  <td className="px-3 py-2.5">{r.agreementType}</td>
                  <td className="px-3 py-2.5 font-mono">{r.employeeCertificate || "—"}</td>
                  <td className="px-3 py-2.5">{r.certificateRequired ? "Yes" : "No"}</td>
                  <td className="px-3 py-2.5 text-foreground-muted">{r.effectiveFrom} → {r.effectiveTo || "open"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
