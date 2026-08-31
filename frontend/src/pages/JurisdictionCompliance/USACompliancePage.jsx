import { useState, useEffect } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
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

// Builds the URL for a given (state, section) pair — the single source of
// truth `goToScope`/`selectSection` both push through, and what the sync
// effect below reads back out via useParams/useSearchParams. Keeping this
// one function is what guarantees the URL and the on-screen section/state
// never drift apart.
function pathForScope(scope, section) {
  const base = scope ? `/super-admin/compliance/united-states/${encodeURIComponent(scope)}` : "/super-admin/compliance/united-states";
  return `${base}?section=${section}`;
}

export default function USACompliancePage() {
  const { jurisdiction } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialState = jurisdiction ? decodeURIComponent(jurisdiction) : "";
  const sectionFromUrl = searchParams.get("section");
  const [section, setSection] = useState(sectionFromUrl || (initialState ? "stateDistrict" : "overview"));
  // Remembers whichever scope (Federal = "", or a state name) was last
  // viewed via Overview/Federal/State-District, so Organizations/Versions/
  // Audit default to something sensible instead of always starting at
  // Federal — pure UI convenience, not a new data concept.
  const [activeScope, setActiveScope] = useState(initialState);

  // Keeps on-screen state in sync when the URL changes WITHOUT going
  // through goToScope/selectSection below — specifically, clicking the
  // browser/Back-button and landing on a previously-pushed URL. Without
  // this, the component stays mounted (same route) and React Router just
  // hands it new params — nothing else would ever re-read them.
  useEffect(() => {
    setSection(sectionFromUrl || (initialState ? "stateDistrict" : "overview"));
    setActiveScope(initialState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jurisdiction, sectionFromUrl]);

  function goToScope(scope) {
    const nextSection = scope ? "stateDistrict" : "federal";
    setActiveScope(scope);
    setSection(nextSection);
    // Push (not replace) — each state/section change is its own history
    // entry, so Back walks through Federal/State-District/a specific
    // state one step at a time instead of collapsing them all into one
    // overwritten entry (the bug this whole change fixes).
    navigate(pathForScope(scope, nextSection));
  }

  function selectSection(key) {
    const nextScope = key === "federal" ? "" : activeScope;
    setSection(key);
    if (key === "federal") setActiveScope("");
    navigate(pathForScope(nextScope, key));
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
