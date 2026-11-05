import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { newZealandComplianceConfig, newZealandExtraTabs } from "../../config/jurisdictions/newZealandComplianceConfig";

const EXTRA_TABS = newZealandExtraTabs();

export default function NZCompliancePage() {
  const { state } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="NZ" countryName="New Zealand"
      initialState={state ? decodeURIComponent(state) : ""}
      onStateChange={(s) =>
        navigate(s ? `/super-admin/compliance/new-zealand/${encodeURIComponent(s)}` : "/super-admin/compliance/new-zealand")
      }
      {...newZealandComplianceConfig}
      extraTabs={EXTRA_TABS}
    />
  );
}
