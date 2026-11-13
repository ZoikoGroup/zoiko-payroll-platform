import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { belgiumComplianceConfig, belgiumExtraTabs } from "../../config/jurisdictions/belgiumComplianceConfig";

const EXTRA_TABS = belgiumExtraTabs();

export default function BECompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="BE" countryName="Belgium"
      initialState={state ? decodeURIComponent(state) : ""}
      onStateChange={(s) =>
        navigate(s ? `/super-admin/compliance/belgium/${encodeURIComponent(s)}` : "/super-admin/compliance/belgium")
      }
      {...belgiumComplianceConfig}
      extraTabs={EXTRA_TABS}
    />
  );
}
