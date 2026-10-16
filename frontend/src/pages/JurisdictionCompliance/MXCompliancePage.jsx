import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { useLoad } from "../../components/jurisdiction/mexico/mxShared";
import { mexicoComplianceConfig, mexicoExtraTabs } from "../../config/jurisdictions/mexicoComplianceConfig";
import { listMxOrganizations } from "../../service/superAdminService";

// Mexico Compliance workspace (ZP-MX-ENG-001). Two scopes: the
// organisation picker (Netherlands pattern — no default organisation) and
// the state route /super-admin/compliance/mexico/:jurisdiction for the
// state ISN packs (Australia pattern).
export default function MXCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  const state = jurisdiction ? decodeURIComponent(jurisdiction) : "";
  const [orgs, orgError] = useLoad(() => listMxOrganizations(), []);
  const [orgId, setOrgId] = useState(null);
  const extraTabs = useMemo(() => mexicoExtraTabs(orgId, state), [orgId, state]);
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
          <option value="">— Platform catalogue (no organisation) —</option>
          {(orgs || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        {orgError && <span role="alert" className="text-[12px] text-error">{orgError}</span>}
      </div>
      <JurisdictionLayout
        country="MX"
        countryName="Mexico"
        initialState={state}
        onStateChange={(next) =>
          navigate(next ? `/super-admin/compliance/mexico/${encodeURIComponent(next)}` : "/super-admin/compliance/mexico")
        }
        extraTabs={extraTabs}
        {...mexicoComplianceConfig}
      />
    </div>
  );
}
