import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { southAfricaComplianceConfig, southAfricaExtraTabs } from "../../config/jurisdictions/southAfricaComplianceConfig";

const EXTRA_TABS = southAfricaExtraTabs();

export default function ZACompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="ZA" countryName="South Africa"
      initialState={state ? decodeURIComponent(state) : ""}
      onStateChange={(s) =>
        navigate(s ? `/super-admin/compliance/south-africa/${encodeURIComponent(s)}` : "/super-admin/compliance/south-africa")
      }
      {...southAfricaComplianceConfig}
      extraTabs={EXTRA_TABS}
    />
  );
}