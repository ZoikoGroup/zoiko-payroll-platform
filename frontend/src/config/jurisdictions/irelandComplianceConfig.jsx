import { Calculator, GraduationCap, HeartPulse, PiggyBank, Landmark, Clock, FileCheck2, ShieldCheck } from "lucide-react";
import IEPayeTab from "../../components/jurisdiction/ireland/IEPayeTab";
import IEUscTab from "../../components/jurisdiction/ireland/IEUscTab";
import IEPrsiTab from "../../components/jurisdiction/ireland/IEPrsiTab";
import IEMyFutureFundTab from "../../components/jurisdiction/ireland/IEMyFutureFundTab";
import IELptTab from "../../components/jurisdiction/ireland/IELptTab";
import IELabourTab from "../../components/jurisdiction/ireland/IELabourTab";
import IEEmergencyTab from "../../components/jurisdiction/ireland/IEEmergencyTab";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";

// Ireland 2026 statutory build (ZP-IE-ENG-001) — the same tab-by-statutory-
// concept shape australiaComplianceConfig.jsx uses for Australia, for the
// same reason: the generic "Contribution Rates" and "Tax Slabs" tabs present
// every row in one undifferentiated list, which makes a 41-key statutory
// surface unauditable. Each Irish tax head gets its own tab, filtering the
// SAME underlying ContributionRate CRUD by component key (see
// ieComponentConfig.js) — no Ireland-only table, no bespoke CRUD.
//
// "PAYE | USC | PRSI | MyFutureFund | LPT | Labour | Emergency" replaces the
// generic rates/slabs tabs, then the shared Taxability/Sources/Tests tabs
// follow.
//
// Ireland is a COUNTRY-LEVEL jurisdiction: there is no province/state
// dimension, so every Ireland pack has jurisdiction_state = NULL and the
// layout's "Country-level (no state)" label is the correct one with no
// override. The four provinces that registrationRegions.js previously
// offered as selectable states are not a statutory dimension and were
// removed.
export const irelandComplianceConfig = {
  extraTabs: [
    {
      key: "paye", label: "PAYE", icon: Calculator, after: "overview",
      isVisible: () => true,
      render: (props) => <IEPayeTab {...props} />,
    },
    {
      key: "usc", label: "USC", icon: GraduationCap, after: "paye",
      isVisible: () => true,
      render: (props) => <IEUscTab {...props} />,
    },
    {
      key: "prsi", label: "PRSI", icon: HeartPulse, after: "usc",
      isVisible: () => true,
      render: (props) => <IEPrsiTab {...props} />,
    },
    {
      key: "myfuturefund", label: "MyFutureFund", icon: PiggyBank, after: "prsi",
      isVisible: () => true,
      render: (props) => <IEMyFutureFundTab {...props} />,
    },
    {
      key: "lpt", label: "LPT", icon: Landmark, after: "myfuturefund",
      isVisible: () => true,
      render: (props) => <IELptTab {...props} />,
    },
    {
      // IE-035/IE-036 — the NMW check is a block, not a warning, so it needs
      // its own visible surface rather than being buried in a rate list.
      key: "labour", label: "Labour Conditions", icon: ShieldCheck, after: "lpt",
      isVisible: () => true,
      render: (props) => <IELabourTab {...props} />,
    },
    {
      // IE-008/IE-031 — the Emergency basis is a distinct assessment regime
      // with its own weekly cutoff progression, not a fallback rate row.
      key: "emergency", label: "Emergency PAYE", icon: Clock, after: "labour",
      isVisible: () => true,
      render: (props) => <IEEmergencyTab {...props} />,
    },
    {
      key: "sources", label: "Sources", icon: FileCheck2, after: "emergency",
      isVisible: () => true,
      render: () => <SourceEvidencePanel />,
    },
    {
      key: "tests", label: "Tests", icon: ShieldCheck, after: "sources",
      isVisible: () => true,
      render: () => (
        <TestCertificationPanel
          jurisdiction="IE" label="Ireland (Revenue)"
          fixturesPath="backend/tests/fixtures/ie_golden/README.md"
        />
      ),
    },
  ],
  // Same reasoning as Australia: the generic single-list rates/slabs tabs are
  // replaced by the per-statutory-head tabs above.
  hiddenTabs: ["rates", "slabs"],
  slabsTabOverride: undefined,
};
