import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { malaysiaComplianceConfig, malaysiaExtraTabs } from "../../config/jurisdictions/malaysiaComplianceConfig";

const EXTRA_TABS = malaysiaExtraTabs();

export default function MYCompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="MY" countryName="Malaysia"
      initialState={state ? decodeURIComponent(state) : ""}
      onStateChange={(s) =>
        navigate(s ? `/super-admin/compliance/malaysia/${encodeURIComponent(s)}` : "/super-admin/compliance/malaysia")
      }
      {...malaysiaComplianceConfig}
      extraTabs={EXTRA_TABS}
    />
  );
}
