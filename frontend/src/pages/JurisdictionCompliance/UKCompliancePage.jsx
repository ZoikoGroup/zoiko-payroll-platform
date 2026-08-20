import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { ukComplianceConfig } from "../../config/jurisdictions/ukComplianceConfig";

export default function UKCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="UK" countryName="United Kingdom"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/united-kingdom/${encodeURIComponent(state)}` : "/super-admin/compliance/united-kingdom", { replace: true })
      }
      {...ukComplianceConfig}
    />
  );
}
