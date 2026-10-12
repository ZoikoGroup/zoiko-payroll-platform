import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// Jamaica — country-level only. PAYE bands (Tax Slabs) and the
// NIS/NHT/Education Tax/HEART rates (Contribution Rates) are fully
// editable through JurisdictionLayout's generic tabs — see
// engine/countries/jamaica.py's docstring for the exact component_key
// mapping (NHT/Education Tax/HEART are repurposed generic fields, not
// literal pension/UK-NI/payroll-tax rows).
export default function JMCompliancePage() {
  return <JurisdictionLayout country="JM" countryName="Jamaica" />;
}
