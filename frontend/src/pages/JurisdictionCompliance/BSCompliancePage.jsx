import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// The Bahamas — country-level only, no income tax. NIB rate/ceiling is
// fully editable through JurisdictionLayout's generic Contribution Rates
// tab — see engine/countries/bahamas.py's docstring. No Tax Slabs
// content (BS-005: never a fake 0% tax band).
export default function BSCompliancePage() {
  return <JurisdictionLayout country="BS" countryName="Bahamas" />;
}
