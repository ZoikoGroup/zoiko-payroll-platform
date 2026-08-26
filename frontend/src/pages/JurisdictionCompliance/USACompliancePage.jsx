import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SuiEmployerRatesPanel from "../../components/jurisdiction/SuiEmployerRatesPanel";
import ReciprocityRulesPanel from "../../components/jurisdiction/ReciprocityRulesPanel";
import LocalityRatesPanel from "../../components/jurisdiction/LocalityRatesPanel";
import SourceEvidencePanel from "../../components/jurisdiction/SourceEvidencePanel";
import { usaComplianceConfig } from "../../config/jurisdictions/usaComplianceConfig";

// SUI Employer Rates and Reciprocity Agreements are page-level, US-only
// sections rather than JurisdictionLayout extraTabs, because their data
// (EmployerTaxProfile, ReciprocityRule) is org/jurisdiction-pair-scoped,
// not attached to any single JurisdictionPack version the way Contribution
// Rates/Tax Slabs are — see each panel's own file for the full reasoning.
// This keeps JurisdictionLayout.jsx itself, and every other country's
// page, completely untouched.
//
// Source Evidence (SourceArtifact) is genuinely platform-wide, not US-only
// — it's surfaced here for now only because this is where the work to
// build it happened; if/when India/UK compliance work needs it too, it
// belongs at a more global level than this page, not duplicated per country.
const SECTIONS = [
  { key: "taxPacks", label: "Tax Packs" },
  { key: "sui", label: "SUI Employer Rates" },
  { key: "reciprocity", label: "Reciprocity & Sourcing" },
  { key: "locality", label: "Locality Rates" },
  { key: "sourceEvidence", label: "Source Evidence" },
];

export default function USACompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  const [section, setSection] = useState("taxPacks");

  return (
    <div>
      <div className="mb-5 flex items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {SECTIONS.map((s) => (
          <button
            key={s.key} onClick={() => setSection(s.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${section === s.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {section === "taxPacks" && (
        <JurisdictionLayout
          country="US" countryName="United States"
          initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
          onStateChange={(state) =>
            navigate(state ? `/super-admin/compliance/united-states/${encodeURIComponent(state)}` : "/super-admin/compliance/united-states", { replace: true })
          }
          {...usaComplianceConfig}
        />
      )}
      {section === "sui" && <SuiEmployerRatesPanel />}
      {section === "reciprocity" && <ReciprocityRulesPanel />}
      {section === "locality" && <LocalityRatesPanel />}
      {section === "sourceEvidence" && <SourceEvidencePanel />}
    </div>
  );
}
