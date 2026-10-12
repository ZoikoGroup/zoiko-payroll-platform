import { useEffect, useState } from "react";
import { listFranceOrganizations } from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass } from "../constants";

// The one France organization picker. Lists ONLY France organizations (the
// France authority endpoints reject any other org), and distinguishes
// loading / failed / genuinely-empty instead of showing every failure as
// "No organizations". The selection itself is owned by FRCompliancePage
// (kept in the URL) so it survives switching views and sections.
export default function FranceOrgPicker({ organizationId, onOrganizationIdChange, hint }) {
  const [state, setState] = useState({ loading: true, organizations: [], error: null });

  useEffect(() => {
    let cancelled = false;
    listFranceOrganizations()
      .then((orgs) => { if (!cancelled) setState({ loading: false, organizations: orgs || [], error: null }); })
      .catch((err) => { if (!cancelled) setState({ loading: false, organizations: [], error: describeLoadError(err) }); });
    return () => { cancelled = true; };
  }, []);

  const { loading, organizations, error } = state;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface-muted px-3 py-2.5">
      <label className="text-xs font-semibold text-foreground-muted">France organization</label>
      <select
        value={organizationId ?? ""}
        disabled={loading || !!error || organizations.length === 0}
        onChange={(e) => onOrganizationIdChange(e.target.value === "" ? null : Number(e.target.value))}
        className={inputClass + " w-auto min-w-[220px]"}
      >
        <option value="">
          {loading ? "Loading…" : error ? "Could not load organizations" : organizations.length ? "Select…" : "No France organizations"}
        </option>
        {organizations.map((org) => (
          <option key={org.id} value={org.id}>
            {org.organizationName || org.name || `Org #${org.id}`}
          </option>
        ))}
      </select>
      <span className="text-[11px] text-foreground-disabled">
        {error
          ? loadErrorText(error)
          : !loading && organizations.length === 0
            ? "No organization has France as its country yet."
            : hint || "France authority data is per-employer — select the org you're configuring."}
      </span>
    </div>
  );
}
