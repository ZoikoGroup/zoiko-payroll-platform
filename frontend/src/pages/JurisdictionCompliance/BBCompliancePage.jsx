import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";

// Barbados — country-level only (no state/province division for payroll
// purposes). Phase 1 has no country-specific extraTabs yet: the PAYE
// bands (Tax Slabs tab) and the NIS/Resilience & Regeneration rates
// (Contribution Rates tab) are fully editable through JurisdictionLayout's
// own generic tabs, same as every other country's base rates — see
// engine/countries/barbados.py's docstring for exactly which
// component_key each row must use.
export default function BBCompliancePage() {
  return <JurisdictionLayout country="BB" countryName="Barbados" />;
}
