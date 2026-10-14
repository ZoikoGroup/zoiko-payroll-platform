import { useMemo, useState } from "react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { useLoad } from "../../components/jurisdiction/netherlands/nlShared";
import { netherlandsComplianceConfig, netherlandsExtraTabs } from "../../config/jurisdictions/netherlandsComplianceConfig";
import { listNlOrganizations } from "../../service/superAdminService";

// Netherlands Compliance workspace. Organisation-scoped tabs act only on the
// organisation chosen here — never a default one.
export default function NLCompliancePage() {
  const [orgs, orgError] = useLoad(() => listNlOrganizations(), []);
  const [orgId, setOrgId] = useState(null);
  const extraTabs = useMemo(() => netherlandsExtraTabs(orgId), [orgId]);
  return (
    <div>
      <div className="mb-4 flex items-center gap-3 rounded-xl border border-border bg-surface p-4">
        <span className="text-sm font-semibold text-foreground">Organisation</span>
        <select
          className="max-w-md flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground"
          value={orgId ?? ""}
          onChange={(e) => setOrgId(e.target.value ? Number(e.target.value) : null)}
          aria-label="Select organisation"
        >
          <option value="">— Select an organisation with Netherlands payroll —</option>
          {(orgs || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        {orgError && <span role="alert" className="text-[12px] text-error">{orgError}</span>}
      </div>
      <JurisdictionLayout
        country="NL"
        countryName="Netherlands"
        extraTabs={extraTabs}
        {...netherlandsComplianceConfig}
      />
    </div>
  );
}
