import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { italyComplianceConfig } from "../../config/jurisdictions/italyComplianceConfig";

export default function ITCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="IT" countryName="Italy"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/italy/${encodeURIComponent(state)}` : "/super-admin/compliance/italy")
      }
      {...italyComplianceConfig}
    />
  );
}
