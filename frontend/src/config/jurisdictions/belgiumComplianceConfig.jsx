import {
  CalendarDays, Clock, FileCheck2, Gauge, HeartPulse, ListChecks, Palmtree, Scale, ScrollText, Settings2,
} from "lucide-react";
import BEPackRowsTab from "../../components/jurisdiction/belgium/BEPackRowsTab";
import { BEContributionRatesTab, BETaxSlabsTab } from "../../components/jurisdiction/belgium/BEPackTables";
import BEEarningClassTab from "../../components/jurisdiction/belgium/BEEarningClassTab";
import BEJointCommitteesTab from "../../components/jurisdiction/belgium/BEJointCommitteesTab";
import BEOverviewDashboard from "../../components/jurisdiction/belgium/BEOverviewDashboard";
import BEReleaseReadinessTab from "../../components/jurisdiction/belgium/BEReleaseReadinessTab";
import BESourcesTab from "../../components/jurisdiction/belgium/BESourcesTab";
import { TAB_GROUPS } from "../../components/jurisdiction/belgium/beShared";

// Super Admin Belgium page (ZP-BE-ENG-001 Phase 3B; spec §14 "Content
// control"), laid out like every other country page (Puerto Rico is the
// reference): Overview | Contribution Rates | Tax Slabs | Policy & Rounding |
// Release Readiness | Organizations | Versions | Audit, with the remaining data
// tabs in the "More" menu.
//
// The generic Contribution Rates / Tax Slabs editors stay hidden: Belgian
// statutory rows change only through the governed signing console (the backend
// refuses the generic editor for BE too). Belgium's own Contribution Rates /
// Tax Slabs tabs render the SAME shared tables (PackRowTables.jsx) from the
// configuration API, editing through the governed editor. Rows, labels, kinds,
// vocabularies and reference notes come from the API. No payroll is computed here.

const always = () => true;

// Tab keys of the earlier layout, merged into the tabs that now hold them.
export const BELGIUM_TAB_ALIASES = {
  "be-withholding": "be-slabs",
  "be-onss-employee": "be-rates",
  "be-onss-employer": "be-rates",
  "be-activation": "be-release",
  "be-signing": "be-release",
  "be-decisions": "be-release",
  // The generic key other pages link to (report templates' "Release readiness").
  "release-readiness": "be-release",
};

export function belgiumExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const more = (key, label, icon, render) => ({ ...tab(key, label, icon, null, render), overflow: true });
  const rows = (groups, title, description) => {
    const render = ({ pack }) => <BEPackRowsTab pack={pack} groups={groups} title={title} description={description} />;
    render.displayName = `BERowsTab(${groups.join("+")})`;
    return render;
  };
  return [
    tab("be-rates", "Contribution Rates", ScrollText, "overview", ({ pack }) => <BEContributionRatesTab pack={pack} />),
    tab("be-slabs", "Tax Slabs", ScrollText, "be-rates", ({ pack }) => <BETaxSlabsTab pack={pack} />),
    tab("be-policy", "Policy & Rounding", Settings2, "be-slabs",
      rows(TAB_GROUPS.policy, "Scope, policy and rounding",
        "Supported scope and the rounding rules (signed pack rows only; unsigned rounding blocks the calculation).")),
    tab("be-release", "Release Readiness", Gauge, "be-policy", ({ pack }) => <BEReleaseReadinessTab pack={pack} />),
    // ── "More" menu ──
    more("be-holiday-pay", "Holiday pay", Palmtree,
      rows(TAB_GROUPS.holidayPay, "Annual holiday pay",
        "White-collar (employer-paid) and manual-worker (holiday fund) regimes never share one formula.")),
    more("be-wages-time", "Wages & working time", Clock,
      rows(TAB_GROUPS.wagesTime, "Wages, indexation and working time",
        "The sector scale is consulted first; the interprofessional minimum is a fallback comparator only.")),
    more("be-absence", "Absence", HeartPulse, rows(TAB_GROUPS.absence, "Absence and guaranteed salary")),
    more("be-public-holidays", "Public holidays", CalendarDays,
      rows(TAB_GROUPS.publicHolidays, "Public holidays",
        "Statutory holidays are signed rows dated inside the pack window; employer substitute days are a separate mechanism.")),
    more("be-earning", "Earning classification", ListChecks, ({ pack }) => <BEEarningClassTab pack={pack} />),
    more("be-joint-committees", "Joint Committees", Scale, () => <BEJointCommitteesTab />),
    more("be-sources", "Sources", FileCheck2, ({ pack }) => <BESourcesTab pack={pack} />),
  ];
}

export const belgiumComplianceConfig = {
  autoSelectPack: (packs) => {
    const today = new Date().toISOString().slice(0, 10);
    const tax = packs.filter((pack) => pack.packType === "tax");
    const inWindow = (pack) => (!pack.effectiveFrom || pack.effectiveFrom <= today) && (!pack.effectiveTo || pack.effectiveTo >= today);
    // Belgium ships Draft until signed: show the Draft pack rather than nothing.
    return tax.find((p) => p.status === "Active" && inWindow(p)) || tax.find(inWindow) || tax[0] || null;
  },
  overviewTabOverride: {
    isActive: () => true,
    render: ({ pack, rates, slabs, onNavigateTab }) => (
      <BEOverviewDashboard pack={pack} refreshKey={`${rates.length}-${slabs.length}`} onNavigateTab={onNavigateTab} />
    ),
  },
  hiddenTabs: ["rates", "slabs"],
  adaptiveTabs: true,
  // Below 1760px: pack chips above the panel and no tab icons, so the eight
  // core tabs stay visible from 1280px (only the data tabs go into More).
  compactUntilWide: true,
  // Hotfix activation self-approves, and Belgium refuses self-approval
  // (four-eyes; service._SELF_APPROVAL_REFUSED_COUNTRIES) — same opt-out as Mexico.
  hideHotfixActivate: true,
  tabAliases: BELGIUM_TAB_ALIASES,
};
