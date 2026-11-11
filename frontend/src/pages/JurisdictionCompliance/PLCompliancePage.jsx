import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { polandComplianceConfig, polandExtraTabs } from "../../config/jurisdictions/polandComplianceConfig";

const EXTRA_TABS = polandExtraTabs();

export default function PLCompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="PL" countryName="Poland"
      initialState={state ? decodeURIComponent(state) : ""}
      onStateChange={(s) =>
        navigate(s ? `/super-admin/compliance/poland/${encodeURIComponent(s)}` : "/super-admin/compliance/poland")
      }
      {...polandComplianceConfig}
      extraTabs={EXTRA_TABS}
    />
  );
}
