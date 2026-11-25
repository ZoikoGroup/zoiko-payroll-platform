import { Navigate, useSearchParams } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import { germanyComplianceConfig, germanyExtraTabs } from "../../config/jurisdictions/germanyComplianceConfig";
import { GERMANY_PAGE, GERMANY_TAB_ALIASES } from "./components/germany/deShared";

// Germany country compliance page — the shared pack layout every other
// country uses (left-column pack list, standard pack header and actions,
// Overview | Contributions | Tax Slabs | Policy | Readiness | Organizations |
// Versions | Audit, "More" for the rest). See germanyComplianceConfig.jsx for
// where every earlier Germany section now lives; each one is reused unchanged.
//
// Links to the earlier layout (?section=<key>, from bookmarks or other pages)
// are rewritten to ?tab=<the tab that now holds that section>.
export default function DECompliancePage() {
  const [searchParams] = useSearchParams();
  const section = searchParams.get("section");
  if (section) {
    const tab = GERMANY_TAB_ALIASES[section] || section;
    return <Navigate replace to={tab === "overview" ? GERMANY_PAGE : `${GERMANY_PAGE}?tab=${encodeURIComponent(tab)}`} />;
  }
  return (
    <JurisdictionLayout
      country="DE" countryName="Germany"
      extraTabs={germanyExtraTabs}
      {...germanyComplianceConfig}
    />
  );
}
