import { Calculator, ClipboardList, FileCheck2, FileText, Gauge, Landmark, Lock, Settings2, ShieldCheck, ToggleRight } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";
import ReportTemplateLayout from "../../components/reportTemplates/ReportTemplateLayout";
import HKStatutorySummaryTab from "../../components/jurisdiction/hong_kong/HKStatutorySummaryTab";
import HKCalculationPreviewTab from "../../components/jurisdiction/hong_kong/HKCalculationPreviewTab";
import HKGovernanceTab from "../../components/jurisdiction/hong_kong/HKGovernanceTab";
import HKStatutoryConfigurationTab from "../../components/jurisdiction/hong_kong/HKStatutoryConfigurationTab";
import { HKIrdEmpfControlTab, HKReadinessCenterTab, HKRetentionTab } from "../../components/jurisdiction/hong_kong/HKControlTabs";

// Hong Kong (ZP-HK-ENG-001) — a thin wrapper over the shared
// JurisdictionLayout, same pattern as Singapore: the layout's own Overview /
// Versions / Organizations / Audit tabs, pack lifecycle and maker-checker
// Approve are reused unchanged (HK activation additionally needs G1 evidence
// and a pack-bound golden PASS, enforced server-side; hotfix is refused).
// The generic Tax Slabs tab is hidden: HK bands (earning classification,
// Salaries Tax tables, holiday calendar, leave scale) are not income-tax
// brackets and would read as misleading withholding bands. The generic
// Contribution Rates tab is hidden too (it renders fractions as "0.0500%" and
// edits without a source): HK values are administered in the governed
// Statutory Configuration tab, by domain, in statutory units.
function hkAutoSelectPack(packs) {
  const today = new Date().toISOString().slice(0, 10);
  const tax = packs.filter((p) => p.packType === "tax");
  return tax.find((p) => (!p.effectiveFrom || p.effectiveFrom <= today) && (!p.effectiveTo || p.effectiveTo >= today))
    || tax[0] || null;
}

const isTax = (pack) => pack.packType === "tax";

const hkComplianceConfig = {
  autoSelectPack: hkAutoSelectPack,
  extraTabs: [
    { key: "hk-summary", label: "Statutory Summary & Gates", icon: ClipboardList, after: "overview", isVisible: isTax,
      render: () => <HKStatutorySummaryTab /> },
    { key: "hk-config", label: "Statutory Configuration", icon: Settings2, after: "hk-summary", isVisible: isTax,
      render: () => <HKStatutoryConfigurationTab /> },
    { key: "hk-governance", label: "Activation & Governance", icon: ToggleRight, after: "hk-config", isVisible: isTax,
      render: () => <HKGovernanceTab /> },
    { key: "hk-evidence", label: "Source Evidence", icon: FileCheck2, after: "hk-governance", isVisible: isTax,
      render: () => <SourceEvidencePanel /> },
    { key: "hk-preview", label: "Calculation Preview", icon: Calculator, after: "hk-evidence", isVisible: isTax,
      render: () => <HKCalculationPreviewTab /> },
    { key: "hk-templates", label: "Report Templates", icon: FileText, after: "hk-preview", isVisible: isTax,
      render: () => <ReportTemplateLayout country="HK" countryName="Hong Kong" embedded /> },
    { key: "hk-golden", label: "Golden Vectors", icon: ShieldCheck, after: "hk-templates", isVisible: isTax,
      render: () => (
        <TestCertificationPanel jurisdiction="HK" label="Hong Kong (MPFA / IRD / Labour Department)"
          fixturesPath="backend/tests/fixtures/hk_golden/README.md" />
      ) },
    { key: "hk-ird-empf", label: "IRD & eMPF Control", icon: Landmark, after: "hk-golden", isVisible: isTax,
      render: () => <HKIrdEmpfControlTab /> },
    { key: "hk-retention", label: "Retention & Privacy", icon: Lock, after: "hk-ird-empf", isVisible: isTax,
      render: () => <HKRetentionTab /> },
    { key: "hk-readiness", label: "Production Readiness", icon: Gauge, after: "hk-retention", isVisible: isTax,
      render: () => <HKReadinessCenterTab /> },
  ],
  hiddenTabs: ["slabs", "rates"],
  countryLevelLabel: "Hong Kong SAR (territory-level)",
};

export default function HKCompliancePage() {
  return <JurisdictionLayout country="HK" countryName="Hong Kong" {...hkComplianceConfig} />;
}
