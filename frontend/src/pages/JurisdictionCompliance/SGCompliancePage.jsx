import { ClipboardList, FileCheck2, FileText, Landmark, ShieldCheck, TableProperties } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";
import SGOverviewDashboard from "../../components/jurisdiction/singapore/SGOverviewDashboard";
import SGStatutoryComponentsTab from "../../components/jurisdiction/singapore/SGStatutoryComponentsTab";
import SGStatutorySummaryTab from "../../components/jurisdiction/singapore/SGStatutorySummaryTab";
import SGPwmSchedulesTab from "../../components/jurisdiction/singapore/SGPwmSchedulesTab";
import SGReportTemplatesTab from "../../components/jurisdiction/singapore/SGReportTemplatesTab";

// Singapore (ZP-SG-ENG-001) — country-level only, plugged into the shared
// JurisdictionLayout exactly like UK (overviewTabOverride + extraTabs +
// hiddenTabs) and Trinidad (slabsFilter). Reuses the layout's own
// Overview/Versions/Organizations/Audit tabs, pack lifecycle, maker-checker
// Approve and hotfix controls unchanged.
//
// The generic Contribution Rates / Tax Slabs tabs are hidden: CPF and SHG
// band rows (CPF_RATE_BAND / SHG_FUND_BAND) would render there as
// misleading "0% brackets", and every Singapore row — scalar or band — is
// presented by the Statutory Components tab instead. Source Evidence and
// Golden Vectors reuse the platform-wide panels the USA page already uses.
const sgComplianceConfig = {
  overviewTabOverride: {
    isActive: (pack) => Boolean(pack) && pack.packType === "tax",
    render: (props) => <SGOverviewDashboard {...props} />,
  },
  extraTabs: [
    {
      key: "sg-components", label: "Statutory Components", icon: Landmark, after: "overview",
      isVisible: (pack) => pack.packType === "tax",
      render: (props) => <SGStatutoryComponentsTab {...props} />,
    },
    {
      key: "sg-evidence", label: "Source Evidence", icon: FileCheck2, after: "sg-components",
      isVisible: (pack) => pack.packType === "tax",
      render: () => <SourceEvidencePanel />,
    },
    // Phase 5.6 — tenant-independent, read-only views from the backend
    // statutory-summary / pwm-schedules endpoints (no maths in React).
    {
      key: "sg-summary", label: "Statutory Summary", icon: ClipboardList, after: "overview",
      isVisible: (pack) => pack.packType === "tax",
      render: () => <SGStatutorySummaryTab />,
    },
    {
      key: "sg-pwm", label: "PWM Schedules", icon: TableProperties, after: "sg-evidence",
      isVisible: (pack) => pack.packType === "tax",
      render: () => <SGPwmSchedulesTab />,
    },
    {
      key: "sg-templates", label: "Report Templates", icon: FileText, after: "sg-pwm",
      isVisible: (pack) => pack.packType === "tax",
      render: () => <SGReportTemplatesTab />,
    },
    {
      key: "sg-golden", label: "Golden Vectors", icon: ShieldCheck, after: "sg-templates",
      isVisible: (pack) => pack.packType === "tax",
      render: () => (
        <TestCertificationPanel
          jurisdiction="SG" label="Singapore (CPF Board / IRAS / MOM)"
          fixturesPath="backend/tests/fixtures/sg_golden/README.md"
        />
      ),
    },
  ],
  hiddenTabs: ["rates", "slabs"],
  countryLevelLabel: "Singapore (country-level)",
  slabsFilter: (rows) => rows.filter((r) => r.ruleType !== "CPF_RATE_BAND" && r.ruleType !== "SHG_FUND_BAND"),
};

export default function SGCompliancePage() {
  return <JurisdictionLayout country="SG" countryName="Singapore" {...sgComplianceConfig} />;
}
