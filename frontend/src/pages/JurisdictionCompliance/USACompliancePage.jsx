import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Landmark, MapPin, Building2, Percent, ArrowLeftRight,
  FileCheck2, Users, History, ScrollText,
} from "lucide-react";
import SuiEmployerRatesPanel from "../../components/jurisdiction/SuiEmployerRatesPanel";
import ReciprocityRulesPanel from "../../components/jurisdiction/ReciprocityRulesPanel";
import LocalityRatesPanel from "../../components/jurisdiction/LocalityRatesPanel";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import USOverviewDashboard from "./components/usa/USOverviewDashboard";
import USTaxPackWorkspace from "./components/usa/USTaxPackWorkspace";
import USOrganizationsSection from "./components/usa/USOrganizationsSection";
import USVersionsSection from "./components/usa/USVersionsSection";
import USAuditSection from "./components/usa/USAuditSection";

// USA Compliance — reorganized into a jurisdiction-specific workspace
// (Overview / Federal / State-District / Local / SUI / Reciprocity /
// Source Evidence / Organizations / Versions / Audit), per the frontend-
// only UI/UX refactor. Every section below reuses EXISTING API functions,
// hooks, and components (JurisdictionLayout, OrgsTab, AssignOrgsModal, the
// 4 already-built standalone panels) — no backend change, no new endpoint.
//
// SUI/Reciprocity/Locality/Source Evidence stay exactly as they were
// (page-level, not JurisdictionLayout extraTabs) for the same reasons as
// before: their data isn't attached to any single JurisdictionPack version.
// Organizations/Versions/Audit are pack-scoped (same as JurisdictionLayout's
// own tabs) — promoted to top-level nav items with their own scope picker
// (see ScopePicker.jsx) instead of requiring you to first select a pack
// under Federal/State-District.
const SECTIONS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "federal", label: "Federal", icon: Landmark },
  { key: "stateDistrict", label: "State / District", icon: MapPin },
  { key: "local", label: "Local", icon: Building2 },
  { key: "sui", label: "SUI Employer Rates", icon: Percent },
  { key: "reciprocity", label: "Reciprocity & Sourcing", icon: ArrowLeftRight },
  { key: "sourceEvidence", label: "Source Evidence", icon: FileCheck2 },
  { key: "organizations", label: "Organizations", icon: Users },
  { key: "versions", label: "Versions", icon: History },
  { key: "audit", label: "Audit", icon: ScrollText },
];

export default function USACompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  const initialState = jurisdiction ? decodeURIComponent(jurisdiction) : "";
  const [section, setSection] = useState(initialState ? "stateDistrict" : "overview");
  // Remembers whichever scope (Federal = "", or a state name) was last
  // viewed via Overview/Federal/State-District, so Organizations/Versions/
  // Audit default to something sensible instead of always starting at
  // Federal — pure UI convenience, not a new data concept.
  const [activeScope, setActiveScope] = useState(initialState);

  function goToScope(scope) {
    setActiveScope(scope);
    setSection(scope ? "stateDistrict" : "federal");
    navigate(
      scope ? `/super-admin/compliance/united-states/${encodeURIComponent(scope)}` : "/super-admin/compliance/united-states",
      { replace: true }
    );
  }

  function selectSection(key) {
    setSection(key);
    if (key === "federal") setActiveScope("");
  }

  return (
    <div>
      <div className="mb-2">
        <h1 className="text-lg font-bold text-foreground">USA Payroll Compliance</h1>
        <p className="text-xs text-foreground-muted">Manage federal, state, and available jurisdiction-level payroll configuration.</p>
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

      {section === "overview" && (
        <USOverviewDashboard onSelectFederal={() => goToScope("")} onSelectState={goToScope} />
      )}
      {section === "federal" && <USTaxPackWorkspace mode="federal" />}
      {section === "stateDistrict" && (
        <USTaxPackWorkspace mode="state" initialSelectedState={activeScope} onActiveScopeChange={setActiveScope} />
      )}
      {section === "local" && <LocalityRatesPanel />}
      {section === "sui" && <SuiEmployerRatesPanel />}
      {section === "reciprocity" && <ReciprocityRulesPanel />}
      {section === "sourceEvidence" && <SourceEvidencePanel />}
      {section === "organizations" && <USOrganizationsSection initialScope={activeScope} />}
      {section === "versions" && <USVersionsSection initialScope={activeScope} />}
      {section === "audit" && <USAuditSection initialScope={activeScope} />}
    </div>
  );
}
