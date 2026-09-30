import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { swedenComplianceConfig } from "../../config/jurisdictions/swedenComplianceConfig";

export default function SECompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="SE" countryName="Sweden"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/sweden/${encodeURIComponent(state)}` : "/super-admin/compliance/sweden")
      }
      {...swedenComplianceConfig}
    />
  );
}
