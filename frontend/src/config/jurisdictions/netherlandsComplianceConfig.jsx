import { Banknote, Building2, Calculator, ClipboardCheck, FileSpreadsheet, FileText, Landmark, Layers, ListChecks, Plane } from "lucide-react";
import NLEmployerProfileTab from "../../components/jurisdiction/netherlands/NLEmployerProfileTab";
import NLTaxTablesTab from "../../components/jurisdiction/netherlands/NLTaxTablesTab";
import NLPackRowsTab from "../../components/jurisdiction/netherlands/NLPackRowsTab";
import NLPremiumsTab from "../../components/jurisdiction/netherlands/NLPremiumsTab";
import NLEarningClassificationTab from "../../components/jurisdiction/netherlands/NLEarningClassificationTab";
import NLExpatRulesTab from "../../components/jurisdiction/netherlands/NLExpatRulesTab";
import NLCaoPensionCatalogTab from "../../components/jurisdiction/netherlands/NLCaoPensionCatalogTab";
import NLVcrInspectorTab from "../../components/jurisdiction/netherlands/NLVcrInspectorTab";
import NLLoonaangifteTab from "../../components/jurisdiction/netherlands/NLLoonaangifteTab";
import NLReadinessGatesTab from "../../components/jurisdiction/netherlands/NLReadinessGatesTab";

// Netherlands (ZP-NL-ENG-001) Super Admin workspace — JurisdictionLayout
// extra tabs. The selected organisation comes from the page's picker (there
// is no default organisation). The base Rates / Slabs tabs stay visible: they
// are the governed editor for the NL pack's statutory rows.
const always = () => true;

export function netherlandsExtraTabs(orgId) {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  return [
    tab("nl-employer", "Employer", Building2, "overview", () => <NLEmployerProfileTab orgId={orgId} />),
    tab("nl-tax-tables", "Wage-tax tables", FileSpreadsheet, "nl-employer", ({ pack }) => <NLTaxTablesTab pack={pack} />),
    tab("nl-pack-rows", "Statutory rows", Layers, "nl-tax-tables", () => <NLPackRowsTab />),
    tab("nl-premiums", "Premium decisions", Calculator, "nl-pack-rows", () => <NLPremiumsTab orgId={orgId} />),
    tab("nl-earnings", "Earning classification", ListChecks, "nl-premiums", () => <NLEarningClassificationTab orgId={orgId} />),
    tab("nl-expat", "Expat (30%)", Plane, "nl-earnings", () => <NLExpatRulesTab orgId={orgId} />),
    tab("nl-cao-pension", "CAO & pension", Landmark, "nl-expat", () => <NLCaoPensionCatalogTab orgId={orgId} />),
    tab("nl-vcr", "VCR inspector", Banknote, "nl-cao-pension", () => <NLVcrInspectorTab orgId={orgId} />),
    tab("nl-loonaangifte", "Loonaangifte", FileText, "nl-vcr", () => <NLLoonaangifteTab orgId={orgId} />),
    tab("nl-readiness", "Readiness G1–G8", ClipboardCheck, "nl-loonaangifte", () => <NLReadinessGatesTab />),
  ];
}

export const netherlandsComplianceConfig = {
  countryLevelLabel: "Netherlands — national pack",
};
