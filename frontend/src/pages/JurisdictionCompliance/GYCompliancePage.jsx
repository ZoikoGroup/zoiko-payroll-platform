import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// Guyana — country-level only. PAYE bands (period-denominated — see
// engine/countries/guyana.py's docstring) and NIS rates are fully
// editable through JurisdictionLayout's generic tabs.
export default function GYCompliancePage() {
  return <JurisdictionLayout country="GY" countryName="Guyana" />;
}
