import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { switzerlandComplianceConfig } from "../../config/jurisdictions/switzerlandComplianceConfig";

export default function CHCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="CH" countryName="Switzerland"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/switzerland/${encodeURIComponent(state)}` : "/super-admin/compliance/switzerland")
      }
      {...switzerlandComplianceConfig}
    />
  );
}