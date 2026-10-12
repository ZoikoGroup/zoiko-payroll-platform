import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { australiaComplianceConfig } from "../../config/jurisdictions/australiaComplianceConfig";

export default function AUCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="AU" countryName="Australia"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        // Push (not replace) — see INCompliancePage.jsx's matching comment.
        navigate(state ? `/super-admin/compliance/australia/${encodeURIComponent(state)}` : "/super-admin/compliance/australia")
      }
      {...australiaComplianceConfig}
    />
  );
}
