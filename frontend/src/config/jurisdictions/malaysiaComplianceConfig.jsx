import { BadgeCheck, Banknote, BriefcaseBusiness, CalendarDays, FileCheck2, FileSpreadsheet, Gauge, Landmark, ListChecks, Map, Receipt, Settings2, Table2, Users } from "lucide-react";
import MYOverviewDashboard from "../../components/jurisdiction/malaysia/MYOverviewDashboard";
import { MYEarningClassTab, MYParametersTab, MYTablesTab, MYTerritoryTab } from "../../components/jurisdiction/malaysia/MYPackTabs";
import MYSigningStatusTab from "../../components/jurisdiction/malaysia/MYSigningStatusTab";
import MYReadinessTab from "../../components/jurisdiction/malaysia/MYReadinessTab";
import MYWorkbookTab from "../../components/jurisdiction/malaysia/MYWorkbookTab";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";

// Super Admin Malaysia page (ZP-MY-ENG-001 Phase 8a; statutory content
// console). The generic Contribution Rates / Tax Slabs editors are hidden:
// Malaysia statutory rows change only through the governed signing console or
// the statutory workbook (the backend refuses the generic editor for MY too).

const always = () => true;

export function malaysiaExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const group = (name) => {
    const render = ({ pack }) => <MYParametersTab pack={pack} group={name} />;
    render.displayName = `MYGroupTab(${name})`;
    return render;
  };
  return [
    tab("my-pcb", "PCB / MTD", Receipt, "overview", group("pcb")),
    tab("my-epf", "EPF", Landmark, "my-pcb", group("epf")),
    tab("my-perkeso", "PERKESO & EIS", Users, "my-epf", group("perkeso")),
    tab("my-hrd", "HRD levy", BriefcaseBusiness, "my-perkeso", group("hrd")),
    tab("my-wages", "Minimum wage", Banknote, "my-hrd", group("wages")),
    tab("my-territory", "Labour by territory", Map, "my-wages", ({ pack }) => <MYTerritoryTab pack={pack} />),
    tab("my-tables", "Schedules & holidays", Table2, "my-territory", ({ pack }) => <MYTablesTab pack={pack} />),
    tab("my-earning", "Earning classification", ListChecks, "my-tables", ({ pack }) => <MYEarningClassTab pack={pack} />),
    tab("my-events", "Events & forms", CalendarDays, "my-earning", group("events")),
    tab("my-policy", "Scope & operations", Settings2, "my-events", group("policy")),
    tab("my-workbook", "Import & verify", FileSpreadsheet, "my-policy", ({ pack }) => <MYWorkbookTab pack={pack} />),
    tab("my-signing", "Signing status", Gauge, "my-workbook", ({ pack }) => <MYSigningStatusTab pack={pack} />),
    tab("my-readiness", "Release gates", BadgeCheck, "my-signing", ({ pack }) => <MYReadinessTab pack={pack} />),
    tab("sources", "Sources", FileCheck2, "my-readiness", () => <SourceEvidencePanel />),
  ];
}

export const malaysiaComplianceConfig = {
  autoSelectPack: (packs) => {
    const today = new Date().toISOString().slice(0, 10);
    const tax = packs.filter((pack) => pack.packType === "tax");
    const inWindow = (pack) => (!pack.effectiveFrom || pack.effectiveFrom <= today) && (!pack.effectiveTo || pack.effectiveTo >= today);
    // Malaysia ships Draft until signed: show the Draft pack rather than nothing.
    return tax.find((p) => p.status === "Active" && inWindow(p)) || tax.find(inWindow) || tax[0] || null;
  },
  overviewTabOverride: {
    isActive: (pack) => pack?.packType === "tax",
    render: (props) => <MYOverviewDashboard {...props} />,
  },
  hiddenTabs: ["rates", "slabs"],
  countryLevelLabel: "Malaysia (country-level)",
};
