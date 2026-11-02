import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { japanComplianceConfig, japanExtraTabs } from "../../config/jurisdictions/japanComplianceConfig";

const EXTRA_TABS = japanExtraTabs();

export default function JPCompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="JP" countryName="Japan"
      initialState={state ? decodeURIComponent(state) : ""}
      onStateChange={(s) =>
        navigate(s ? `/super-admin/compliance/japan/${encodeURIComponent(s)}` : "/super-admin/compliance/japan")
      }
      {...japanComplianceConfig}
      extraTabs={EXTRA_TABS}
    />
  );
}
