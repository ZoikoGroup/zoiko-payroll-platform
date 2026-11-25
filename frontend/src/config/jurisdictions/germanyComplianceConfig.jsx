import { BarChart3, FileSearch, Gauge, History, Landmark, Radio, RefreshCcw, ScrollText, Send, Settings2 } from "lucide-react";
import WorkerDataLocked from "../../components/WorkerDataLocked";
import DEContributionsTab from "../../pages/JurisdictionCompliance/components/germany/DEContributionsTab";
import DEOverviewTab from "../../pages/JurisdictionCompliance/components/germany/DEOverviewTab";
import DEPolicyTab from "../../pages/JurisdictionCompliance/components/germany/DEPolicyTab";
import DEReadinessTab from "../../pages/JurisdictionCompliance/components/germany/DEReadinessTab";
import DETaxSlabsTab from "../../pages/JurisdictionCompliance/components/germany/DETaxSlabsTab";
import GermanyDeuvTab from "../../pages/JurisdictionCompliance/components/germany/GermanyDeuvTab";
import { GERMANY_TAB_ALIASES } from "../../pages/JurisdictionCompliance/components/germany/deShared";
import {
  AuditTab, ElstamBatchesTab, ElsterTab, EmployerLeviesTab, SourceEvidenceTab,
} from "../../pages/JurisdictionCompliance/GermanyStatutoryRegistriesPage";

// Super Admin Germany page on the shared pack layout, like Puerto Rico,
// Bahamas, Barbados and Belgium: the DE packs in the left column, the standard
// pack header and actions, and Overview | Contributions | Tax Slabs | Policy |
// Readiness | Organizations | Versions | Audit, with the rest in "More".
//
// The generic Contribution Rates / Tax Slabs tabs are replaced by Germany's
// own: Contributions renders the SAME shared rates table (the pack's own rate
// rows with the standard edit icons, then the registry rows and the engine's
// fallback constants, read from the constants themselves), and Tax Slabs shows
// the section 32a tariff built into tax.py (Germany has no slab rows) with the
// not-BMF-certified warning, then the PAP panel. Every German registry editor
// is reused unchanged inside these tabs; nothing is removed. No value is typed
// in any of these files.

const always = () => true;

export const germanyExtraTabs = (() => {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const more = (key, label, icon, render) => ({ ...tab(key, label, icon, null, render), overflow: true });
  return [
    tab("de-rates", "Contributions", ScrollText, "overview", ({ pack, rates, onAddRate, onEditRate, onDeleteRate }) => (
      <DEContributionsTab key={pack.id} pack={pack} rates={rates}
        onAddRate={onAddRate} onEditRate={onEditRate} onDeleteRate={onDeleteRate} />
    )),
    tab("de-slabs", "Tax Slabs", ScrollText, "de-rates", () => <DETaxSlabsTab />),
    tab("de-policy", "Policy", Settings2, "de-slabs", ({ pack }) => <DEPolicyTab key={pack.id} pack={pack} />),
    tab("de-readiness", "Readiness", Gauge, "de-policy", ({ pack }) => <DEReadinessTab key={pack.id} pack={pack} />),
    // ── "More" menu ──
    more("de-deuv", "DEÜV", Radio, () => <GermanyDeuvTab />),
    more("de-elstam", "ELStAM", RefreshCcw, () => <ElstamBatchesTab />),
    more("de-elster", "ELSTER", Send, () => <ElsterTab />),
    // ZP-PRIV: the payroll summary aggregates one organization's payslips
    // (tenant route /api/payroll/germany/reports/summary); not shown here.
    more("de-payroll-summary", "Payroll Summary", BarChart3,
      () => <WorkerDataLocked variant="tenant" title="The payroll summary is the organization's own report" />),
    more("de-sources", "Source Evidence", FileSearch, () => <SourceEvidenceTab />),
    more("de-levies", "Employer levies (accident insurance)", Landmark, () => <EmployerLeviesTab />),
    more("de-registry-audit", "Registry audit / history", History, () => <AuditTab />),
  ];
})();

export const germanyComplianceConfig = {
  overviewTabOverride: {
    isActive: () => true,
    render: ({ pack, rates, slabs, onNavigateTab }) => (
      <DEOverviewTab key={pack.id} pack={pack} refreshKey={`${rates.length}-${slabs.length}`} onNavigateTab={onNavigateTab} />
    ),
  },
  hiddenTabs: ["rates", "slabs"],
  adaptiveTabs: true,
  tabAliases: GERMANY_TAB_ALIASES,
};
