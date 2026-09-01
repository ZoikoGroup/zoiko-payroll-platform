import JurisdictionLayout from "../../../../components/jurisdiction/JurisdictionLayout";
import { usaComplianceConfig } from "../../../../config/jurisdictions/usaComplianceConfig";
import USStateAccordionWorkspace from "../../../../components/jurisdiction/usa/state/USStateAccordionWorkspace";

// Thin wrapper. "Federal" is just JurisdictionLayout locked to the
// country-level pack (initialState="") — untouched by the State/District
// accordion refactor below. "State / District" used to be a second
// sidebar+JurisdictionLayout pair (two nested list+detail panels); it now
// renders USStateAccordionWorkspace, a dedicated unified-list surface where
// each state expands inline instead. See valiant-pondering-gizmo.md.
export default function USTaxPackWorkspace({ mode, initialSelectedState = "", onActiveScopeChange }) {
  if (mode === "state") {
    return (
      <USStateAccordionWorkspace
        initialSelectedState={initialSelectedState}
        onActiveScopeChange={onActiveScopeChange}
      />
    );
  }

  if (mode === "federal") {
    return (
      <JurisdictionLayout
        key="federal"
        country="US"
        countryName="United States"
        initialState=""
        onStateChange={() => {}}
        {...usaComplianceConfig}
      />
    );
  }

  return null;
}
