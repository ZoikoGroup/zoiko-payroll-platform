import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// Puerto Rico — dual-jurisdiction (local Hacienda withholding + an
// independently-computed federal-equivalent layer), but architecturally a
// sibling of every other Caribbean country page in this codebase, not a
// US-dependent variant. Contribution Rates/Tax Slabs (Hacienda withholding
// brackets, Social Security, Medicare, FUTA-equivalent, DTRH unemployment,
// SINOT) are all fully editable through JurisdictionLayout's generic tabs —
// see engine/countries/puerto_rico.py's docstring for the exact
// component_key mapping.
export default function PRCompliancePage() {
  return <JurisdictionLayout country="PR" countryName="Puerto Rico" />;
}
