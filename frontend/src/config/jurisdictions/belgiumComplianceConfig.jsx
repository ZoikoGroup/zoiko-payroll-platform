import {
  BadgeCheck, Building2, CalendarDays, Clock, FileCheck2, Gauge, HeartPulse, Landmark, ListChecks,
  Palmtree, Scale, Settings2, Users,
} from "lucide-react";
import BEPackRowsTab from "../../components/jurisdiction/belgium/BEPackRowsTab";
import BEEarningClassTab from "../../components/jurisdiction/belgium/BEEarningClassTab";
import BEJointCommitteesTab from "../../components/jurisdiction/belgium/BEJointCommitteesTab";
import BEOverviewDashboard from "../../components/jurisdiction/belgium/BEOverviewDashboard";
import BEOwnerDecisionsTab from "../../components/jurisdiction/belgium/BEOwnerDecisionsTab";
import BESigningStatusTab from "../../components/jurisdiction/belgium/BESigningStatusTab";
import BESourcesTab from "../../components/jurisdiction/belgium/BESourcesTab";
import { TAB_GROUPS } from "../../components/jurisdiction/belgium/beShared";

// Super Admin Belgium page (ZP-BE-ENG-001 Phase 3B; spec §14 "Content
// control"). The generic Contribution Rates / Tax Slabs editors are hidden:
// Belgian statutory rows change only through the governed signing console (the
// backend refuses the generic editor for BE too). Rows, labels, kinds,
// vocabularies and reference notes come from the configuration API. The shared
// Organizations (assign) tab stays; assigning a non-Active Belgian pack is
// refused by the backend and its message is shown. No payroll is computed here.

const always = () => true;

export function belgiumExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const rows = (groups, title, description) => {
    const render = ({ pack }) => <BEPackRowsTab pack={pack} groups={groups} title={title} description={description} />;
    render.displayName = `BERowsTab(${groups.join("+")})`;
    return render;
  };
  return [
    tab("be-policy", "Policy & rounding", Settings2, "overview",
      rows(TAB_GROUPS.policy, "Scope, policy and rounding",
        "Supported scope and the rounding rules (signed pack rows only; unsigned rounding blocks the calculation).")),
    tab("be-withholding", "Withholding", Landmark, "be-policy",
      rows(TAB_GROUPS.withholding, "Professional withholding (Annex III)",
        "Regular and exceptional remuneration are separate strategies; nothing is derived from the annual income-tax brackets.")),
    tab("be-onss-employee", "ONSS employee", Users, "be-withholding", rows(TAB_GROUPS.onssEmployee, "ONSS/RSZ employee")),
    tab("be-onss-employer", "ONSS employer & reductions", Building2, "be-onss-employee",
      rows(TAB_GROUPS.onssEmployer, "ONSS/RSZ employer and reductions",
        "Every employer contribution is resolved by employer category and worker code; the console never shows an all-in employer rate.")),
    tab("be-holiday-pay", "Holiday pay", Palmtree, "be-onss-employer",
      rows(TAB_GROUPS.holidayPay, "Annual holiday pay",
        "White-collar (employer-paid) and manual-worker (holiday fund) regimes never share one formula.")),
    tab("be-wages-time", "Wages & working time", Clock, "be-holiday-pay",
      rows(TAB_GROUPS.wagesTime, "Wages, indexation and working time",
        "The sector scale is consulted first; the interprofessional minimum is a fallback comparator only.")),
    tab("be-absence", "Absence", HeartPulse, "be-wages-time", rows(TAB_GROUPS.absence, "Absence and guaranteed salary")),
    tab("be-public-holidays", "Public holidays", CalendarDays, "be-absence",
      rows(TAB_GROUPS.publicHolidays, "Public holidays",
        "Statutory holidays are signed rows dated inside the pack window; employer substitute days are a separate mechanism.")),
    tab("be-earning", "Earning classification", ListChecks, "be-public-holidays", ({ pack }) => <BEEarningClassTab pack={pack} />),
    tab("be-joint-committees", "Joint Committees", Scale, "be-earning", () => <BEJointCommitteesTab />),
    tab("be-signing", "Signing status", Gauge, "be-joint-committees", ({ pack }) => <BESigningStatusTab pack={pack} />),
    tab("be-decisions", "Owner decisions", BadgeCheck, "be-signing", () => <BEOwnerDecisionsTab />),
    tab("be-sources", "Sources", FileCheck2, "be-decisions", ({ pack }) => <BESourcesTab pack={pack} />),
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
    render: (props) => <BEOverviewDashboard {...props} />,
  },
  hiddenTabs: ["rates", "slabs"],
  countryLevelLabel: "Belgium (country-level)",
};

