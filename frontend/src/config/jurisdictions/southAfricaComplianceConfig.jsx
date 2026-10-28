import { Banknote, Calculator, FileCheck2, Gauge, Landmark, ListChecks, ShieldCheck } from "lucide-react";
import ZAOverviewDashboard from "../../components/jurisdiction/southAfrica/ZAOverviewDashboard";
import ZAPayeTab from "../../components/jurisdiction/southAfrica/ZAPayeTab";
import ZAContributionsTab from "../../components/jurisdiction/southAfrica/ZAContributionsTab";
import ZAEtiTab from "../../components/jurisdiction/southAfrica/ZAEtiTab";
import ZALabourTab from "../../components/jurisdiction/southAfrica/ZALabourTab";
import ZAReadinessTab from "../../components/jurisdiction/southAfrica/ZAReadinessTab";
import EarningClassMatrix from "../../components/jurisdiction/EarningClassMatrix";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";

const always = () => true;

export function southAfricaExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  return [
    tab("za-paye", "PAYE", Calculator, "overview", ({ rates, slabs }) => (
      <ZAPayeTab rates={rates} slabs={slabs} />
    )),
    tab("za-contributions", "UIF, SDL & retirement", Banknote, "za-paye", ({ rates }) => (
      <ZAContributionsTab rates={rates} />
    )),
    tab("za-eti", "ETI", Landmark, "za-contributions", ({ rates, slabs }) => (
      <ZAEtiTab rates={rates} slabs={slabs} />
    )),
    tab("za-earning", "Earning classification", ListChecks, "za-eti", ({ slabs }) => (
      <EarningClassMatrix
        slabs={slabs}
        ruleType="ZA_EARNING_CLASS"
        title="Earning classification (PAYE / UIF / SDL / ETI / COIDA)"
        description="Each obligation has its own remuneration base. REVIEW blocks a live calculation until the component is classified with signed evidence."
        obligations={["PAYE", "UIF", "SDL", "ETI", "COIDA"]}
      />
    )),
    tab("za-labour", "Labour & filing", ShieldCheck, "za-earning", ({ rates }) => (
      <ZALabourTab rates={rates} />
    )),
    tab("za-readiness", "Readiness", Gauge, "za-labour", () => <ZAReadinessTab />),
    tab("sources", "Sources", FileCheck2, "za-readiness", () => <SourceEvidencePanel />),
    tab("tests", "Tests", ShieldCheck, "sources", () => (
      <TestCertificationPanel
        jurisdiction="ZA"
        label="South Africa (SARS)"
        fixturesPath="backend/tests/fixtures/za_golden/README.md"
      />
    )),
  ];
}

export const southAfricaComplianceConfig = {
  autoSelectPack: (packs) => {
    const today = new Date().toISOString().slice(0, 10);
    const active = packs.filter((pack) => pack.packType === "tax" && pack.status === "Active");
    return active.find((pack) => (
      (!pack.effectiveFrom || pack.effectiveFrom <= today)
      && (!pack.effectiveTo || pack.effectiveTo >= today)
    )) || active[0] || null;
  },
  overviewTabOverride: {
    isActive: (pack) => pack?.packType === "tax",
    render: (props) => <ZAOverviewDashboard {...props} />,
  },
  countryLevelLabel: "South Africa (country-level)",
};
