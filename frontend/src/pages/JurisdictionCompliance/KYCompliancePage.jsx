import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// Cayman Islands — country-level only, no income tax. Mandatory pension
// rate/cap is fully editable through JurisdictionLayout's generic
// Contribution Rates tab — see engine/countries/cayman_islands.py's
// docstring for the exact component_key mapping. There is deliberately
// no Tax Slabs content for KY (KY-002: never a fake 0% tax band).
export default function KYCompliancePage() {
  return <JurisdictionLayout country="KY" countryName="Cayman Islands" />;
}
