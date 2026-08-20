import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { germanyComplianceConfig } from "../../config/jurisdictions/germanyComplianceConfig";

export default function DECompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="DE" countryName="Germany"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/germany/${encodeURIComponent(state)}` : "/super-admin/compliance/germany", { replace: true })
      }
      {...germanyComplianceConfig}
    />
  );
}
