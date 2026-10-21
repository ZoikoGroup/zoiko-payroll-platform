import { LayoutDashboard, Building2, MapPin, Users, Layers, Percent, Send } from "lucide-react";
import WorkerDataLocked from "../../WorkerDataLocked";
import FranceOrgPicker from "./FranceOrgPicker";

// France's "Employer & Authority Configuration" view (FR §11 panels A–H).
//
// ZP-PRIV: every section here is an organization's own data — the SIREN
// employer identity, SIRET establishments, AT/MP rate packs, governed
// effectif, readiness/go-live and DSN filings are tenant-run (decision 3),
// and PAS rates are per-employee worker data. The Super Admin routes behind
// them are retired, so these sections no longer call the API at all; they
// explain where the work now happens. The organization picker stays so the
// Support Access link can be pre-filled with the selected organization.
const SECTIONS = [
  {
    key: "overview", label: "Overview & Readiness", icon: LayoutDashboard, variant: "tenant",
    note: "France readiness and go-live are run by the organization from its own workspace (Payroll → Employer statutory → France).",
  },
  {
    key: "employer-profile", label: "Employer Profile", icon: Building2, variant: "tenant",
    note: "The SIREN employer identity is maintained by the organization's admins.",
  },
  {
    key: "establishments", label: "Establishments", icon: MapPin, variant: "tenant",
    note: "The SIRET establishment registry is maintained by the organization's admins.",
  },
  {
    key: "rate-packs", label: "Employer Rates", icon: Layers, variant: "tenant",
    note: "URSSAF AT/MP establishment rate packs are recorded by the organization from its notices.",
  },
  {
    key: "effectif", label: "Effectif", icon: Users, variant: "tenant",
    note: "The governed effectif (exact headcount) and its corrections are recorded by the organization.",
  },
  { key: "pas-rates", label: "PAS Rates", icon: Percent, variant: "support" },
  {
    key: "dsn", label: "DSN", icon: Send, variant: "tenant",
    note: "DSN submissions and the outbox are the organization's filings, opened from its payroll workspace.",
  },
];

export default function FranceAuthorityPanel({ organizationId, onOrganizationIdChange, section = "overview", onSectionChange }) {
  const active = SECTIONS.find((s) => s.key === section) || SECTIONS[0];

  return (
    <div className="space-y-4">
      <FranceOrgPicker
        organizationId={organizationId}
        onOrganizationIdChange={onOrganizationIdChange}
        render={(selectedOrg) => (
          <>
            <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
              {SECTIONS.map((s) => (
                <button
                  key={s.key}
                  onClick={() => onSectionChange?.(s.key)}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                    active.key === s.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"
                  }`}
                >
                  <s.icon size={13} />
                  {s.label}
                </button>
              ))}
            </div>
            <WorkerDataLocked
              variant={active.variant}
              organizationCode={selectedOrg?.organization_code || selectedOrg?.organizationCode || undefined}
            >
              {active.note && <p className="text-xs text-slate-500 dark:text-slate-400">{active.note}</p>}
            </WorkerDataLocked>
          </>
        )}
      />
    </div>
  );
}
