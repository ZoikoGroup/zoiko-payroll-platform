import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  LayoutDashboard, Building2, Users, Layers, Percent, Send,
} from "lucide-react";
import FROverviewDashboard from "./components/france/FROverviewDashboard";
import FranceEmployerProfileTab from "./components/france/FranceEmployerProfileTab";
import FranceEffectifTab from "./components/france/FranceEffectifTab";
import FranceEstablishmentRatePacksTab from "./components/france/FranceEstablishmentRatePacksTab";
import FrancePASRatesTab from "./components/france/FrancePASRatesTab";
import FranceDsnTab from "./components/france/FranceDsnTab";
import { listOrganizationsForPicker } from "../../service/superAdminService";

// France country compliance workspace (ZP-FR-ENG-001) — the primary landing
// page for Compliance -> France.
//
// France does NOT use the pack-based JurisdictionLayout every other country
// here uses, for the same structural reason Germany already documented in
// DECompliancePage.jsx: France's mandatory contributions and PAS are the
// engine's content-as-data rate_map resolved from authority-held artifacts
// (DGFiP personalized PAS rates, URSSAF AT/MP establishment rate packs,
// governed effectif) rather than Land-style stat/tax packs. There is no
// jurisdiction-level "Compliance Pack" to author — so this workspace is
// organized around the five authority surfaces + DSN diagnostics instead.
//
// Everything below is organization-scoped (the France authority data model
// is per-employer: SIREN identity, SIRET rate packs, PAS rates, effectif),
// so an Organization picker is surfaced once at the top and drives every
// section.
const SECTIONS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "employer-profile", label: "Employer Profile", icon: Building2 },
  { key: "effectif", label: "Effectif", icon: Users },
  { key: "rate-packs", label: "Establishment Rate Packs", icon: Layers },
  { key: "pas-rates", label: "PAS Rates", icon: Percent },
  { key: "dsn", label: "DSN & Outbox", icon: Send },
];

export default function FRCompliancePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sectionFromUrl = searchParams.get("section");
  const [section, setSection] = useState(sectionFromUrl || "overview");
  const [organizations, setOrganizations] = useState([]);
  const [organizationId, setOrganizationId] = useState(null);

  useEffect(() => {
    setSection(sectionFromUrl || "overview");
  }, [sectionFromUrl]);

  useEffect(() => {
    listOrganizationsForPicker()
      .then((orgs) => {
        setOrganizations(orgs || []);
        if (orgs?.length) setOrganizationId((current) => current || orgs[0].id);
      })
      .catch(() => setOrganizations([]));
  }, []);

  function selectSection(key) {
    setSection(key);
    setSearchParams(key === "overview" ? {} : { section: key });
  }

  return (
    <div>
      <div className="mb-2">
        <h1 className="text-lg font-bold text-foreground">France Payroll Compliance</h1>
        <p className="text-xs text-foreground-muted">
          Manage France's statutory payroll configuration — the SIREN employer profile (IDCC / URSSAF / filing due-date class),
          governed effectif thresholds, URSSAF estate rate packs (AT/MP, FNAL, CFP), DGFiP PAS rates, the DSN transport
          diagnostics, and the launch-gate H readiness dry-run.
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

      {section === "overview" && (
        <FROverviewDashboard
          organizationId={organizationId}
          organizations={organizations}
          onOrganizationChange={setOrganizationId}
        />
      )}
      {section === "employer-profile" && <FranceEmployerProfileTab organizationId={organizationId} />}
      {section === "effectif" && <FranceEffectifTab organizationId={organizationId} />}
      {section === "rate-packs" && <FranceEstablishmentRatePacksTab organizationId={organizationId} />}
      {section === "pas-rates" && <FrancePASRatesTab organizationId={organizationId} />}
      {section === "dsn" && <FranceDsnTab organizationId={organizationId} />}
    </div>
  );
}