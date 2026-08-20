import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { canadaComplianceConfig } from "../../config/jurisdictions/canadaComplianceConfig";

export default function CACompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="CA" countryName="Canada"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/canada/${encodeURIComponent(state)}` : "/super-admin/compliance/canada", { replace: true })
      }
      {...canadaComplianceConfig}
    />
  );
}
