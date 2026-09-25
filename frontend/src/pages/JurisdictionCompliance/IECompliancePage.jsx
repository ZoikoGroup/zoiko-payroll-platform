import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

export default function IECompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="IE" countryName="Ireland"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/ireland/${encodeURIComponent(state)}` : "/super-admin/compliance/ireland", { replace: true })
      }
      countryLevelLabel="Country-level (Revenue district)"
    />
  );
}
