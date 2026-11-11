import { Banknote, Calculator, Clock, FileCheck2, Gauge, Landmark, ListChecks, ShieldCheck } from "lucide-react";
import JPOverviewDashboard from "../../components/jurisdiction/japan/JPOverviewDashboard";
import JPPackRowsTab from "../../components/jurisdiction/japan/JPPackRowsTab";
import JPReadinessTab from "../../components/jurisdiction/japan/JPReadinessTab";
import EarningClassMatrix from "../../components/jurisdiction/EarningClassMatrix";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";

// Super Admin Japan page (ZP-JP-ENG-001). Read-only views of the canonical
// JP-PAYROLL pack; keys match engine/countries/japan_content.py.

const always = () => true;

const GROUPS = {
  withholding: {
    title: "National withholding (NTA)",
    description: "PRIMARY column: computer method or table per the signed method row; SECONDARY: tables. Bonuses use the bonus-rate table selected by prior-month pay.",
    keys: ["jp_withholding_method", "jp_wht_rounding", "jp_wht_cmp_basic_deduction", "jp_wht_cmp_dependant_deduction",
      "jp_wht_bonus_special_multiple", "jp_wht_remittance_due_day", "jp_wht_due_non_business_day_rule",
      "jp_statutory_reports_due", "jp_correction_policy"],
    tables: [
      { ruleType: "JP_WHT_MONTHLY", label: "Monthly withholding table", gate: "G1" },
      { ruleType: "JP_WHT_CMP_EID", label: "Computer method — employment-income deduction", gate: "G1" },
      { ruleType: "JP_WHT_CMP_RATE", label: "Computer method — tax rates", gate: "G1" },
      { ruleType: "JP_WHT_BONUS", label: "Bonus-rate table", gate: "G1" },
    ],
  },
  socialInsurance: {
    title: "Social insurance",
    description: "Pension on the pension SMR, health / care / child support on the health SMR. Health rates are insurer- and prefecture-specific; bonuses use the standard bonus amount with its caps.",
    keys: ["jp_epi_total", "jp_epi_split_rule", "jp_kyokai_health_total_min", "jp_kyokai_health_total_max",
      "jp_health_split_rule", "jp_kyokai_care_total", "jp_care_split_rule", "jp_care_min_age", "jp_care_max_age",
      "jp_kyokai_child_support_total", "jp_child_support_split_rule", "jp_si_employee_share_rounding",
      "jp_sba_rounding", "jp_sba_rounding_unit", "jp_epi_sba_monthly_cap", "jp_health_sba_annual_cap",
      "jp_bonus_report_days", "jp_smr_determination_months", "jp_smr_report_month", "jp_smr_application_months",
      "jp_smr_adhoc_revision_from_month", "jp_smr_min_payment_base_days", "jp_smr_adhoc_grade_gap",
      "jp_si_remittance_due"],
    tables: [
      { ruleType: "JP_HEALTH_RATE", label: "Health-insurance rates (insurer / prefecture)", gate: "G3" },
      { ruleType: "JP_SMR_GRADE", label: "SMR grade tables (health / pension)", gate: "G3" },
    ],
  },
  employmentInsurance: {
    title: "Employment insurance",
    description: "FY rates by industry class. A class whose split the specification does not state stays empty and blocks.",
    keys: ["jp_ei_general", "jp_ei_agriculture_sake_total", "jp_ei_agriculture_sake", "jp_ei_construction_total",
      "jp_ei_construction", "jp_ei_employee_share_rounding"],
    tables: [],
  },
  residentTax: {
    title: "Resident tax",
    description: "Never calculated: special collection uses the municipality's notice, twelve monthly amounts from June to May.",
    keys: ["jp_resident_tax_collection_months"],
    tables: [],
  },
  labour: {
    title: "Working time, premiums and minimum wage",
    description: "Hours come from approved attendance; the premium floor and the prefectural minimum wage block a payslip — pay is never topped up.",
    keys: ["jp_supported_pay_frequencies", "jp_statutory_hours_per_day", "jp_statutory_hours_per_week",
      "jp_overtime_premium_pct", "jp_overtime_60h_threshold_hours", "jp_overtime_over_60h_premium_pct",
      "jp_statutory_holiday_premium_pct", "jp_night_premium_pct", "jp_night_window",
      "jp_premium_combination_rule", "jp_holiday_substitute_rule"],
    tables: [
      { ruleType: "JP_MIN_WAGE", label: "Prefectural minimum wages", gate: "G4" },
      { ruleType: "JP_HOLIDAY", label: "Statutory holidays", gate: "G4" },
    ],
  },
};

export function japanExtraTabs() {
  const tab = (key, label, icon, after, render) => ({ key, label, icon, after, isVisible: always, render });
  const group = (name) => ({ rates, slabs }) => <JPPackRowsTab {...GROUPS[name]} rates={rates} slabs={slabs} />;
  return [
    tab("jp-withholding", "Withholding", Calculator, "overview", group("withholding")),
    tab("jp-social-insurance", "Social insurance", ShieldCheck, "jp-withholding", group("socialInsurance")),
    tab("jp-employment-insurance", "Employment insurance", Banknote, "jp-social-insurance", group("employmentInsurance")),
    tab("jp-resident-tax", "Resident tax", Landmark, "jp-employment-insurance", group("residentTax")),
    tab("jp-labour", "Labour", Clock, "jp-resident-tax", group("labour")),
    tab("jp-earning", "Earning classification", ListChecks, "jp-labour", ({ slabs }) => (
      <EarningClassMatrix
        slabs={slabs}
        ruleType="JP_EARNING_CLASS"
        title="Earning classification (WHT / SI / EI / overtime base / minimum wage)"
        description="Each obligation has its own base (JP-018). REVIEW blocks a live calculation until the component is classified with signed evidence."
        obligations={["WHT", "SI", "EI", "OT_BASE", "MIN_WAGE"]}
        componentOrder={["SALARY", "OVERTIME", "ALLOWANCE", "COMMUTING_ALLOWANCE", "BONUS", "OTHER_EARNINGS"]}
      />
    )),
    tab("jp-readiness", "Readiness", Gauge, "jp-earning", () => <JPReadinessTab />),
    tab("sources", "Sources", FileCheck2, "jp-readiness", () => <SourceEvidencePanel />),
  ];
}

export const japanComplianceConfig = {
  autoSelectPack: (packs) => {
    const today = new Date().toISOString().slice(0, 10);
    const tax = packs.filter((pack) => pack.packType === "tax");
    const inWindow = (pack) => (!pack.effectiveFrom || pack.effectiveFrom <= today) && (!pack.effectiveTo || pack.effectiveTo >= today);
    // Japan ships Draft until G1: show the Draft pack rather than nothing.
    return tax.find((p) => p.status === "Active" && inWindow(p)) || tax.find(inWindow) || tax[0] || null;
  },
  overviewTabOverride: {
    isActive: (pack) => pack?.packType === "tax",
    render: (props) => <JPOverviewDashboard {...props} />,
  },
  countryLevelLabel: "Japan (country-level)",
};
