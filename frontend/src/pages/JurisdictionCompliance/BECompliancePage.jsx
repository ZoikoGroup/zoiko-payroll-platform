import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { SeedDraftPanel } from "../../components/jurisdiction/belgium/BEOverviewDashboard";
import { useLoad } from "../../components/jurisdiction/japan/jpFormat";
import { belgiumComplianceConfig, belgiumExtraTabs } from "../../config/jurisdictions/belgiumComplianceConfig";
import { listBePacks } from "../../service/superAdminService";

const EXTRA_TABS = belgiumExtraTabs();

// The Belgium tabs (Overview, signing, activation readiness...) render only once a pack is selected, so with NO
// Belgian pack at all the governed "create the Draft pack" action (POST seed-draft: catalogue rows, PENDING G1,
// reason, audited, create-only) is shown here, above the shared layout — never the generic hand-made pack form.
export default function BECompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  const [layoutKey, setLayoutKey] = useState(0);
  const [packs, error, loading, reload] = useLoad(() => listBePacks());
  const noPack = !loading && !error && Array.isArray(packs) && packs.length === 0;
  return (
    <>
      {noPack && (
        <div className="mx-auto mb-4 max-w-3xl" data-testid="be-no-pack">
          <SeedDraftPanel onDone={() => { reload(); setLayoutKey((k) => k + 1); }} />
        </div>
      )}
      <JurisdictionLayout
        key={layoutKey}
        country="BE" countryName="Belgium"
        initialState={state ? decodeURIComponent(state) : ""}
        onStateChange={(s) =>
          navigate(s ? `/super-admin/compliance/belgium/${encodeURIComponent(s)}` : "/super-admin/compliance/belgium")
        }
        {...belgiumComplianceConfig}
        extraTabs={EXTRA_TABS}
      />
    </>
  );
}
