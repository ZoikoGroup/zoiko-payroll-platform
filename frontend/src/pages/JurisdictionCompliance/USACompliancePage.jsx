import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { usaComplianceConfig } from "../../config/jurisdictions/usaComplianceConfig";

export default function USACompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="US" countryName="United States"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/united-states/${encodeURIComponent(state)}` : "/super-admin/compliance/united-states", { replace: true })
      }
      {...usaComplianceConfig}
    />
  );
}
