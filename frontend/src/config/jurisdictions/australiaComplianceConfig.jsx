import { Calculator, GraduationCap, HeartPulse, PiggyBank, Landmark, MapPin, ListChecks, FileCheck2, ShieldCheck } from "lucide-react";
import AUPaygTab from "../../components/jurisdiction/australia/AUPaygTab";
import AUStslTab from "../../components/jurisdiction/australia/AUStslTab";
import AUMedicareTab from "../../components/jurisdiction/australia/AUMedicareTab";
import AUSuperTab from "../../components/jurisdiction/australia/AUSuperTab";
import AUSpecialPaymentsTab from "../../components/jurisdiction/australia/AUSpecialPaymentsTab";
import AUStateAccordionWorkspace from "../../components/jurisdiction/australia/state/AUStateAccordionWorkspace";
import TaxabilityMatrixTab from "../../components/jurisdiction/TaxabilityMatrixTab";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";

// Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), Phase 6 —
// §20's own Super Admin tab list: "Overview | PAYG | STSL | Medicare |
// Super | Special Payments | State Payroll Tax | Taxability | Sources |
// Tests | Audit." The generic "Tax Slabs" tab is hidden in favor of the
// PAYG/STSL coefficient-band editors (AU_PAYG_COEFFICIENT/
// AU_STSL_COEFFICIENT rows have no clean UI in the generic SlabFormModal
// — see AUCoefficientRowFormModal's own comment); the generic
// "Contribution Rates" tab is likewise hidden in favor of the grouped
// Medicare/Super/Special Payments views (same underlying ContributionRate
// CRUD, just filtered per tab — see each tab's own file).
//
// "State Payroll Tax" is its own 8-jurisdiction accordion
// (components/jurisdiction/australia/state/AUStateAccordionWorkspace.jsx,
// cloned from USA's own state accordion), entirely independent of the
// FEDERAL pack PAYG/STSL/Medicare/Super/Special Payments all read —
// each of the 8 states is its own JurisdictionPack.
export const australiaComplianceConfig = {
  extraTabs: [
    {
      key: "payg", label: "PAYG", icon: Calculator, after: "overview",
      isVisible: () => true,
      render: (props) => <AUPaygTab {...props} />,
    },
    {
      key: "stsl", label: "STSL", icon: GraduationCap, after: "payg",
      isVisible: () => true,
      render: (props) => <AUStslTab {...props} />,
    },
    {
      key: "medicare", label: "Medicare", icon: HeartPulse, after: "stsl",
      isVisible: () => true,
      render: (props) => <AUMedicareTab {...props} />,
    },
    {
      key: "super", label: "Super", icon: PiggyBank, after: "medicare",
      isVisible: () => true,
      render: (props) => <AUSuperTab {...props} />,
    },
    {
      key: "specialPayments", label: "Special Payments", icon: Landmark, after: "super",
      isVisible: () => true,
      render: (props) => <AUSpecialPaymentsTab {...props} />,
    },
    {
      key: "statePayrollTax", label: "State Payroll Tax", icon: MapPin, after: "specialPayments",
      isVisible: () => true,
      render: () => <AUStateAccordionWorkspace />,
    },
    {
      key: "taxability", label: "Taxability", icon: ListChecks, after: "statePayrollTax",
      isVisible: () => true,
      render: () => <TaxabilityMatrixTab country="AU" />,
    },
    {
      key: "sources", label: "Sources", icon: FileCheck2, after: "taxability",
      isVisible: () => true,
      render: () => <SourceEvidencePanel />,
    },
    {
      key: "tests", label: "Tests", icon: ShieldCheck, after: "sources",
      isVisible: () => true,
      render: () => (
        <TestCertificationPanel
          jurisdiction="AU" label="Australia (ATO)"
          fixturesPath="backend/tests/fixtures/au_golden/README.md"
        />
      ),
    },
  ],
  hiddenTabs: ["rates", "slabs"],
  slabsTabOverride: undefined,
};
