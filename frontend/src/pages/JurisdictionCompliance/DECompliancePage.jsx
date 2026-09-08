import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  LayoutDashboard, FileCheck2, HeartPulse, Percent, ShieldCheck, Layers, Clock3, Gauge,
  Landmark, Church, RefreshCcw, FileSearch, History,
} from "lucide-react";
import DEOverviewDashboard from "./components/germany/DEOverviewDashboard";
import {
  PapTab, HealthFundsTab, ContributionCeilingsTab, PvConfigTab, EarningTaxabilityTab,
  OvertimePremiumCategoriesTab, OvertimeGrundlohnCapsTab, EmployerLeviesTab, ChurchTaxTab,
  ElstamBatchesTab, SourceEvidenceTab, AuditTab,
} from "./GermanyStatutoryRegistriesPage";

// Germany country compliance workspace — the primary landing page for
// Compliance -> Germany. Germany has no Land (federal state)-level tax
// packs in this codebase (church tax is an employee-level opt-in flag
// consumed directly by engine/countries/germany.py, not a jurisdiction/
// pack-level construct — see germanyComplianceConfig.jsx, kept for
// reference), so this page does NOT wrap the pack-based JurisdictionLayout
// component every other country here uses — the same reasoning that
// already led USACompliancePage.jsx to stop using it for its own
// non-pack-scoped sections (SUI, Reciprocity, Locality, Source Evidence).
//
// Every section below reuses the EXISTING Germany statutory registry tab
// components straight from GermanyStatutoryRegistriesPage.jsx (now named
// exports) — the same backend calls, the same maker-checker forms, the
// same state. There is exactly one implementation of each registry; this
// page only adds a country-level Overview and promotes every tab that
// page already had to its own top-level nav item, so all of it is
// discoverable from Compliance -> Germany without needing to know the
// /super-admin/compliance/germany/registries deep link (which still
// renders the identical GermanyStatutoryRegistriesPage component and
// remains a valid compatibility route).
const SECTIONS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "pap", label: "PAP / Releases", icon: FileCheck2 },
  { key: "health-funds", label: "Health Funds", icon: HeartPulse },
  { key: "ceilings", label: "Contribution Ceilings", icon: Percent },
  { key: "pv", label: "PV Configuration", icon: ShieldCheck },
  { key: "earning-taxability", label: "Earning Taxability", icon: Layers },
  { key: "overtime-premium-categories", label: "Overtime Premium Categories", icon: Clock3 },
  { key: "overtime-grundlohn-caps", label: "Overtime Grundlohn Caps", icon: Gauge },
  { key: "employer-levies", label: "Employer Levies (Accident Insurance)", icon: Landmark },
  { key: "church-tax", label: "Church Tax", icon: Church },
  { key: "elstam-batches", label: "ELStAM Change-List Batches", icon: RefreshCcw },
  { key: "source-evidence", label: "Source Evidence", icon: FileSearch },
  { key: "audit", label: "Audit / History", icon: History },
];

export default function DECompliancePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sectionFromUrl = searchParams.get("section");
  const [section, setSection] = useState(sectionFromUrl || "overview");

  // Keeps on-screen state in sync when the URL changes without going
  // through selectSection below — e.g. the browser Back/Forward buttons.
  useEffect(() => {
    setSection(sectionFromUrl || "overview");
  }, [sectionFromUrl]);

  function selectSection(key) {
    setSection(key);
    // Push (not replace) — each section change is its own history entry.
    setSearchParams(key === "overview" ? {} : { section: key });
  }

  return (
    <div>
      <div className="mb-2">
        <h1 className="text-lg font-bold text-foreground">Germany Payroll Compliance</h1>
        <p className="text-xs text-foreground-muted">
          Manage Germany's statutory payroll configuration — PAP, health funds, contribution ceilings, PV
          configuration, church tax, overtime treatment, employer levies, ELStAM change-list batches, and the
          source evidence backing each of them.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-1 rounded-lg border border-border bg-surface-muted p-1">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => selectSection(s.key)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
              section === s.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"
            }`}
          >
            <s.icon size={13} />
            {s.label}
          </button>
        ))}
      </div>

      {section === "overview" && <DEOverviewDashboard onSelectSection={selectSection} />}
      {section === "pap" && <PapTab />}
      {section === "health-funds" && <HealthFundsTab />}
      {section === "ceilings" && <ContributionCeilingsTab />}
      {section === "pv" && <PvConfigTab />}
      {section === "earning-taxability" && <EarningTaxabilityTab />}
      {section === "overtime-premium-categories" && <OvertimePremiumCategoriesTab />}
      {section === "overtime-grundlohn-caps" && <OvertimeGrundlohnCapsTab />}
      {section === "employer-levies" && <EmployerLeviesTab />}
      {section === "church-tax" && <ChurchTaxTab />}
      {section === "elstam-batches" && <ElstamBatchesTab />}
      {section === "source-evidence" && <SourceEvidenceTab />}
      {section === "audit" && <AuditTab />}
    </div>
  );
}
