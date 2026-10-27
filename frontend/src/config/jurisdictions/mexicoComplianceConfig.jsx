import { BookOpen, Building2, Calculator, ClipboardCheck, FileCheck2, FileCode2, HeartPulse, Home, Landmark, ListChecks, MapPin, Scale, ShieldCheck, Sun, Wallet } from "lucide-react";
import MXIsrTariffsTab from "../../components/jurisdiction/mexico/MXIsrTariffsTab";
import MXSubsidyUmaTab from "../../components/jurisdiction/mexico/MXSubsidyUmaTab";
import MXMinimumWageTab from "../../components/jurisdiction/mexico/MXMinimumWageTab";
import MXImssCeavTab from "../../components/jurisdiction/mexico/MXImssCeavTab";
import MXInfonavitTab from "../../components/jurisdiction/mexico/MXInfonavitTab";
import MXBenefitsWorkweekTab from "../../components/jurisdiction/mexico/MXBenefitsWorkweekTab";
import MXStatutoryRulesTab from "../../components/jurisdiction/mexico/MXStatutoryRulesTab";
import MXEarningClassificationTab from "../../components/jurisdiction/mexico/MXEarningClassificationTab";
import MXCfdiCatalogTab from "../../components/jurisdiction/mexico/MXCfdiCatalogTab";
import MXReadinessGatesTab from "../../components/jurisdiction/mexico/MXReadinessGatesTab";
import MXCfdiLifecycleTab from "../../components/jurisdiction/mexico/MXCfdiLifecycleTab";
import MXAuthoritiesTab from "../../components/jurisdiction/mexico/MXAuthoritiesTab";
import MXEmployerProfileTab from "../../components/jurisdiction/mexico/MXEmployerProfileTab";
import MXStateAccordionWorkspace from "../../components/jurisdiction/mexico/state/MXStateAccordionWorkspace";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import TestCertificationPanel from "../../components/jurisdiction/TestCertificationPanel";

// Mexico (ZP-MX-ENG-001) Super Admin workspace — JurisdictionLayout extra
// tabs, chained by `after`. Statutory content is read-only (governed pack
// lifecycle only), so the generic Rates / Slabs editors are hidden, as for
// Australia. TaxabilityMatrixTab is NOT used (it only knows CA/US programs);
// Mexico's multi-axis earning classification is its own tab (MX-005).
// Employer (Phase 3) is read-only: the organisation authors its own employer facts.
const always = () => true;

export function mexicoExtraTabs(orgId, state) {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  return [
    tab("mx-employer", "Employer", Building2, "overview", () => <MXEmployerProfileTab orgId={orgId} />),
    tab("mx-isr", "ISR tariffs", Calculator, "mx-employer", () => <MXIsrTariffsTab />),
    tab("mx-uma", "Subsidy & UMA", Wallet, "mx-isr", () => <MXSubsidyUmaTab />),
    tab("mx-minwage", "Minimum wages", Scale, "mx-uma", () => <MXMinimumWageTab />),
    tab("mx-imss", "IMSS & CEAV", HeartPulse, "mx-minwage", () => <MXImssCeavTab />),
    tab("mx-infonavit", "INFONAVIT", Home, "mx-imss", () => <MXInfonavitTab />),
    tab("mx-benefits", "Benefits & workweek", Sun, "mx-infonavit", () => <MXBenefitsWorkweekTab />),
    tab("mx-rules", "Statutory rules", BookOpen, "mx-benefits", () => <MXStatutoryRulesTab />),
    tab("mx-earnings", "Earning classification", ListChecks, "mx-rules", () => <MXEarningClassificationTab orgId={orgId} />),
    tab("mx-cfdi", "CFDI catalogs", FileCode2, "mx-earnings", () => <MXCfdiCatalogTab />),
    tab("mx-isn", "State ISN", MapPin, "mx-cfdi", () => <MXStateAccordionWorkspace initialSelectedState={state} />),
    tab("mx-sources", "Sources", FileCheck2, "mx-isn", () => <SourceEvidencePanel />),
    tab("mx-tests", "Tests", ShieldCheck, "mx-sources", () => (
      <TestCertificationPanel jurisdiction="MX" label="Mexico (SAT / IMSS)" fixturesPath="backend/tests/fixtures/mx_golden/README.md" />
    )),
    tab("mx-readiness", "Readiness G1–G8", ClipboardCheck, "mx-tests", () => <MXReadinessGatesTab />),
    tab("mx-cfdi-lifecycle", "CFDI lifecycle", FileCode2, "mx-readiness", () => <MXCfdiLifecycleTab />),
    tab("mx-authorities", "Authorities", Landmark, "mx-cfdi-lifecycle", () => <MXAuthoritiesTab />),
  ];
}

export const mexicoComplianceConfig = {
  countryLevelLabel: "Mexico — federal pack",
  hiddenTabs: ["rates", "slabs"],
  // Completion W5-2: no Mexico hotfix (four-eyes only); the backend refuses it too.
  hideHotfixActivate: true,
};
