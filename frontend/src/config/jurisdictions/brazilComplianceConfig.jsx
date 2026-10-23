import { Banknote, Building2, Calculator, ClipboardCheck, FileSpreadsheet, FileText, Landmark, Layers, ListChecks, ShieldCheck, Sparkles } from "lucide-react";
import BRStatutorySectionTab from "../../components/jurisdiction/brazil/BRStatutorySectionTab";
import BRRubricCatalogueTab from "../../components/jurisdiction/brazil/BRRubricCatalogueTab";
import BRFpasTableTab from "../../components/jurisdiction/brazil/BRFpasTableTab";
import BRReadinessGatesTab from "../../components/jurisdiction/brazil/BRReadinessGatesTab";
import BRGoldenVectorsTab from "../../components/jurisdiction/brazil/BRGoldenVectorsTab";
import BREmployerProfileTab from "../../components/jurisdiction/brazil/BREmployerProfileTab";

// Brazil (CLT), ZP-BR-ENG-001 — Super Admin workspace, mirroring the
// Netherlands netherlandsComplianceConfig.jsx. The selected organisation comes
// from the page's own picker (there is no default organisation). The base
// Rates / Slabs tabs stay visible: they are the governed editor for the BR
// pack's statutory rows, so every statutory tab below is read-only.
const always = () => true;

export function brazilExtraTabs(orgId) {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  return [
    tab("br-inss", "INSS bands", FileSpreadsheet, "overview", () => (
      <BRStatutorySectionTab ruleType="BR_INSS_BAND" title="INSS employee contribution bands (segurado empregado)" />
    )),
    tab("br-irrf", "IRRF table", Calculator, "br-inss", () => (
      <BRStatutorySectionTab ruleType="BR_IRRF_TABLE" title="IRRF monthly table (rates and parcela a deduzir)" />
    )),
    tab("br-irrf-reduction", "IRRF reduction", Calculator, "br-irrf", () => (
      <BRStatutorySectionTab ruleType="BR_IRRF_REDUCTION" title="IRRF 2026 monthly reduction (Law 15.270/2025)" />
    )),
    tab("br-min-wage", "Minimum wage", Banknote, "br-irrf-reduction", () => (
      <BRStatutorySectionTab ruleType="BR_MIN_WAGE" title="Statutory minimum wage (salário mínimo)" />
    )),
    tab("br-salario-familia", "Salário-família", ListChecks, "br-min-wage", () => (
      <BRStatutorySectionTab ruleType="BR_SAL_FAMILIA" title="Salário-família quota and income ceiling" />
    )),
    tab("br-fgts", "FGTS", Landmark, "br-salario-familia", () => (
      <BRStatutorySectionTab ruleType="BR_FGTS_RATE" title="FGTS deposit rate" />
    )),
    tab("br-cpp", "CPP", Layers, "br-fgts", () => (
      <BRStatutorySectionTab ruleType="BR_CPP_RATE" title="CPP — employer social contribution (patronal)" />
    )),
    tab("br-rat-fap", "RAT / FAP", ShieldCheck, "br-cpp", () => (
      <BRStatutorySectionTab ruleType="BR_RAT_FAP" title="RAT grades and the FAP range (accident-risk contribution)" />
    )),
    tab("br-vt", "Vale-transporte", Banknote, "br-rat-fap", () => (
      <BRStatutorySectionTab ruleType="BR_VT_RATE" title="Vale-transporte — maximum employee deduction" />
    )),
    tab("br-labor", "Labour premiums", Calculator, "br-vt", () => (
      <BRStatutorySectionTab ruleType="BR_LABOR" title="Overtime, night premium and DSR (CLT)" />
    )),
    tab("br-rubrics", "Rubric catalogue", FileText, "br-labor", () => <BRRubricCatalogueTab orgId={orgId} />),
    tab("br-fpas", "FPAS / Tabela 04", ClipboardCheck, "br-rubrics", () => <BRFpasTableTab />),
    tab("br-employer", "Employer (read-only)", Building2, "br-fpas", () => <BREmployerProfileTab orgId={orgId} />),
    tab("br-readiness", "Readiness G1–G8", ShieldCheck, "br-employer", () => <BRReadinessGatesTab />),
    tab("br-golden", "Golden vectors", Sparkles, "br-readiness", () => <BRGoldenVectorsTab />),
  ];
}

export const brazilComplianceConfig = {
  countryLevelLabel: "Brazil (CLT) — national pack",
};
