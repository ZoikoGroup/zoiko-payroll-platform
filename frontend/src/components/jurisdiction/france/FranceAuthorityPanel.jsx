import { LayoutDashboard, Building2, MapPin, Users, Layers, Percent, Send } from "lucide-react";
import FranceOrgPicker from "./FranceOrgPicker";
import FranceOverviewDashboard from "./FranceOverviewDashboard";
import FranceEmployerProfilePanel from "./FranceEmployerProfilePanel";
import FranceEstablishmentsPanel from "./FranceEstablishmentsPanel";
import FranceEffectifPanel from "./FranceEffectifPanel";
import FranceEstablishmentRatePacksPanel from "./FranceEstablishmentRatePacksPanel";
import FrancePASRatesPanel from "./FrancePASRatesPanel";
import FranceDsnDiagnosticsPanel from "./FranceDsnDiagnosticsPanel";

// France's "Employer & Authority Configuration" view — the organization-
// scoped payroll_fr_* workspace (FR §11 panels A–H). Not pack-versioned, so
// it lives outside the pack tabs. The organization and section are owned by
// FRCompliancePage (kept in the URL), so one selection drives every section
// and survives switching views.
const SECTIONS = [
  { key: "overview", label: "Overview & Readiness", icon: LayoutDashboard },
  { key: "employer-profile", label: "Employer Profile", icon: Building2 },
  { key: "establishments", label: "Establishments", icon: MapPin },
  { key: "rate-packs", label: "Employer Rates", icon: Layers },
  { key: "effectif", label: "Effectif", icon: Users },
  { key: "pas-rates", label: "PAS Rates", icon: Percent },
  { key: "dsn", label: "DSN", icon: Send },
];

export default function FranceAuthorityPanel({ organizationId, onOrganizationIdChange, section = "overview", onSectionChange }) {
  const active = SECTIONS.some((s) => s.key === section) ? section : "overview";

  return (
    <div className="space-y-4">
      <FranceOrgPicker organizationId={organizationId} onOrganizationIdChange={onOrganizationIdChange} />

      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => onSectionChange?.(s.key)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
              active === s.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"
            }`}
          >
            <s.icon size={13} />
            {s.label}
          </button>
        ))}
      </div>

      {active === "overview" && <FranceOverviewDashboard organizationId={organizationId} onNavigate={onSectionChange} />}
      {active === "employer-profile" && <FranceEmployerProfilePanel organizationId={organizationId} />}
      {active === "establishments" && <FranceEstablishmentsPanel organizationId={organizationId} />}
      {active === "rate-packs" && <FranceEstablishmentRatePacksPanel organizationId={organizationId} />}
      {active === "effectif" && <FranceEffectifPanel organizationId={organizationId} />}
      {active === "pas-rates" && <FrancePASRatesPanel organizationId={organizationId} />}
      {active === "dsn" && <FranceDsnDiagnosticsPanel organizationId={organizationId} />}
    </div>
  );
}
