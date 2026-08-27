import { Percent, Layers } from "lucide-react";
import USTaxComponentsTab from "../../components/jurisdiction/usa/USTaxComponentsTab";
import USIncomeTaxBracketsTab from "../../components/jurisdiction/usa/USIncomeTaxBracketsTab";
import USANewPackModal from "../../components/jurisdiction/usa/USANewPackModal";

// USA UI/UX refactor: the generic Contribution Rates / Tax Slabs tables
// (JurisdictionLayout's base "rates"/"slabs" tabs) are hidden in favor of
// one grouped "Tax Components" view — same data, same
// upsertCanonicalContributionRate/upsertCanonicalTaxSlab CRUD, same
// RateFormModal/SlabFormModal, just organized by component key and filing
// status instead of a flat table. Works identically for the Federal pack
// and any state pack (California/New York today) — no country/state
// branching lives here, only in USTaxComponentsTab's grouping logic.
//
// There is still no backend concept of county/city-level tax attached to
// a JurisdictionPack, so nothing is invented here to represent one — the
// dedicated Locality Rates panel (see USACompliancePage.jsx) already
// covers that, entirely separately from the pack/rate/slab system.
//
// Organizations/Versions/Audit are also hidden here: the USA refactor
// promotes them to their own top-level nav items (USOrganizationsSection/
// USVersionsSection/USAuditSection, each with its own Federal/state scope
// picker) so they're reachable without first drilling into a specific
// pack. Leaving them visible here too would just duplicate that same data
// behind a second, redundant tab bar inside Federal/State-District.
export const usaComplianceConfig = {
  extraTabs: [
    {
      key: "components",
      label: "Tax Components",
      icon: Percent,
      after: "overview",
      isVisible: () => true,
      render: (props) => <USTaxComponentsTab {...props} />,
    },
    // Its own tab beside "Tax Components" rather than a section inside it
    // (per Venu's request) — same slabs/onDeleteSlab/onReload props
    // JurisdictionLayout's extraTabs.render() already passes, zero new
    // fetching. Labeled generically ("Income Tax Brackets" — not "Federal
    // Income Tax") since this same tab renders for both the Federal pack
    // and any state pack (e.g. California); JurisdictionLayout's tab
    // labels are static, not pack-aware, so a single label must be correct
    // in both contexts.
    {
      key: "incomeTax",
      label: "Income Tax Brackets",
      icon: Layers,
      after: "components",
      isVisible: () => true,
      render: (props) => <USIncomeTaxBracketsTab {...props} />,
    },
  ],
  hiddenTabs: ["rates", "slabs", "organizations", "versions", "audit"],
  slabsTabOverride: undefined,
  // Drops the India/UK-oriented "Tax Regime" field (never populated on any
  // real US pack) and uses a wider, multi-column layout instead of one
  // tall column — see USANewPackModal.jsx. JurisdictionLayout defaults to
  // the generic NewPackModal for every other country.
  newPackFormComponent: USANewPackModal,
};
