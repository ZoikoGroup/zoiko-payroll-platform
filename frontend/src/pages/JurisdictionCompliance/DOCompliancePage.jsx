import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// Dominican Republic — country-level only. ISR bands (Tax Slabs) and the
// SFS/pension/SRL/INFOTEP rates (Contribution Rates) are fully editable
// through JurisdictionLayout's generic tabs — see
// engine/countries/dominican_republic.py's docstring for the exact
// component_key mapping and each obligation's own independent ceiling.
export default function DOCompliancePage() {
  return <JurisdictionLayout country="DO" countryName="Dominican Republic" />;
}
