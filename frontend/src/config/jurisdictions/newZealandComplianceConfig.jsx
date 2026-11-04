import { Banknote, Calculator, CalendarDays, FileCheck2, FileText, Gauge, HeartHandshake, ListChecks, Scale, ShieldCheck, Table2 } from "lucide-react";
import NZOverviewDashboard from "../../components/jurisdiction/new_zealand/NZOverviewDashboard";
import NZPackRowsTab from "../../components/jurisdiction/new_zealand/NZPackRowsTab";
import NZAuthorityTablesTab from "../../components/jurisdiction/new_zealand/NZAuthorityTablesTab";
import NZEarningClassTab from "../../components/jurisdiction/new_zealand/NZEarningClassTab";
import NZSigningStatusTab from "../../components/jurisdiction/new_zealand/NZSigningStatusTab";
import { GROUPS } from "../../components/jurisdiction/new_zealand/nzContent";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";

// Super Admin New Zealand page (ZP-NZ-ENG-001 P7b, decision Option 1). The
// generic Contribution Rates / Tax Slabs editors are hidden: NZ statutory rows
// change only through the governed signing console (the backend refuses the
// generic editor for NZ too). Keys match engine/countries/new_zealand_content.py.

const always = () => true;

export function newZealandExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const group = (name) => {
    const render = ({ pack, rates, slabs, onReload }) => (
      <NZPackRowsTab {...GROUPS[name]} pack={pack} rates={rates} slabs={slabs} onReload={onReload} />
    );
    render.displayName = `NZGroupTab(${name})`;
    return render;
  };
  return [
    tab("nz-paye", "PAYE & ACC", Calculator, "overview", group("paye")),
    tab("nz-kiwisaver", "KiwiSaver & ESCT", Banknote, "nz-paye", group("kiwisaver")),
    tab("nz-deductions", "Student loan & child support", Scale, "nz-kiwisaver", group("deductions")),
    tab("nz-min-wage", "Minimum wage", ShieldCheck, "nz-deductions", group("minimumWage")),
    tab("nz-holidays", "Holidays Act", CalendarDays, "nz-min-wage", group("holidays")),
    tab("nz-filing", "Filing & remittance", FileText, "nz-holidays", group("filing")),
    tab("nz-policy", "Corrections & extra pay", HeartHandshake, "nz-filing", group("policy")),
    tab("nz-earning", "Earning classification", ListChecks, "nz-policy",
      ({ pack, slabs, onReload }) => <NZEarningClassTab pack={pack} slabs={slabs} onReload={onReload} />),
    tab("nz-authority", "Authority tables", Table2, "nz-earning",
      ({ pack, slabs, onReload }) => <NZAuthorityTablesTab pack={pack} slabs={slabs} onReload={onReload} />),
    tab("nz-signing", "Signing status", Gauge, "nz-authority", ({ pack }) => <NZSigningStatusTab pack={pack} />),
    tab("sources", "Sources", FileCheck2, "nz-signing", () => <SourceEvidencePanel />),
  ];
}

export const newZealandComplianceConfig = {
  autoSelectPack: (packs) => {
    const today = new Date().toISOString().slice(0, 10);
    const tax = packs.filter((pack) => pack.packType === "tax");
    const inWindow = (pack) => (!pack.effectiveFrom || pack.effectiveFrom <= today) && (!pack.effectiveTo || pack.effectiveTo >= today);
    // New Zealand ships Draft until signed: show the Draft pack rather than nothing.
    return tax.find((p) => p.status === "Active" && inWindow(p)) || tax.find(inWindow) || tax[0] || null;
  },
  overviewTabOverride: {
    isActive: (pack) => pack?.packType === "tax",
    render: (props) => <NZOverviewDashboard {...props} />,
  },
  hiddenTabs: ["rates", "slabs"],
  countryLevelLabel: "New Zealand (country-level)",
};
