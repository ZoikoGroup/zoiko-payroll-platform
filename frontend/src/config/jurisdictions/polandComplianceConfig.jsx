import { Banknote, Calculator, CalendarDays, FileCheck2, FileText, Gauge, HeartPulse, Landmark, ListChecks, PiggyBank, Settings2 } from "lucide-react";
import PLOverviewDashboard from "../../components/jurisdiction/poland/PLOverviewDashboard";
import PLPackRowsTab from "../../components/jurisdiction/poland/PLPackRowsTab";
import PLEarningClassTab from "../../components/jurisdiction/poland/PLEarningClassTab";
import PLSigningStatusTab from "../../components/jurisdiction/poland/PLSigningStatusTab";
import { GROUPS } from "../../components/jurisdiction/poland/plContent";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";

// Super Admin Poland page (ZP-PL-ENG-001 P7b; spec §12 statutory content
// console). The generic Contribution Rates / Tax Slabs editors are hidden:
// Poland statutory rows change only through the governed signing console
// (the backend refuses the generic editor for PL too). Keys match
// engine/countries/poland_content.py.

const always = () => true;

export function polandExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const group = (name) => {
    const render = ({ pack, rates, slabs, onReload }) => (
      <PLPackRowsTab {...GROUPS[name]} pack={pack} rates={rates} slabs={slabs} onReload={onReload} />
    );
    render.displayName = `PLGroupTab(${name})`;
    return render;
  };
  return [
    tab("pl-pit", "PIT & PIT-2", Calculator, "overview", group("pit")),
    tab("pl-zus", "ZUS & health", Landmark, "pl-pit", group("zus")),
    tab("pl-funds", "Employer funds", Banknote, "pl-zus", group("funds")),
    tab("pl-ppk", "PPK", PiggyBank, "pl-funds", group("ppk")),
    tab("pl-labour", "Wages, overtime & leave", CalendarDays, "pl-ppk", group("labour")),
    tab("pl-sickness", "Sickness", HeartPulse, "pl-labour", group("sickness")),
    tab("pl-filing", "Filing & operations", FileText, "pl-sickness", group("filing")),
    tab("pl-policy", "Scope & rounding", Settings2, "pl-filing", group("policy")),
    tab("pl-earning", "Earning classification", ListChecks, "pl-policy",
      ({ pack, slabs, onReload }) => <PLEarningClassTab pack={pack} slabs={slabs} onReload={onReload} />),
    tab("pl-signing", "Signing status", Gauge, "pl-earning", ({ pack }) => <PLSigningStatusTab pack={pack} />),
    tab("sources", "Sources", FileCheck2, "pl-signing", () => <SourceEvidencePanel />),
  ];
}

export const polandComplianceConfig = {
  autoSelectPack: (packs) => {
    const today = new Date().toISOString().slice(0, 10);
    const tax = packs.filter((pack) => pack.packType === "tax");
    const inWindow = (pack) => (!pack.effectiveFrom || pack.effectiveFrom <= today) && (!pack.effectiveTo || pack.effectiveTo >= today);
    // Poland ships Draft until signed: show the Draft pack rather than nothing.
    return tax.find((p) => p.status === "Active" && inWindow(p)) || tax.find(inWindow) || tax[0] || null;
  },
  overviewTabOverride: {
    isActive: (pack) => pack?.packType === "tax",
    render: (props) => <PLOverviewDashboard {...props} />,
  },
  hiddenTabs: ["rates", "slabs"],
  countryLevelLabel: "Poland (country-level)",
};
