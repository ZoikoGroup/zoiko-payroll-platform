import { useMemo } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { BookOpen } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import FranceAuthorityPanel from "../../components/jurisdiction/france/FranceAuthorityPanel";
import FranceStatutoryReferencePanel from "../../components/jurisdiction/france/FranceStatutoryReferencePanel";

// France Compliance — the same pack-based jurisdiction architecture as every
// other country, split into two views:
//
//   1. "Tax Configuration" — JurisdictionLayout(country="FR"). The France
//      statutory content (PASS/SMIC/rates/RGDU/PAS parameters) is PACK DATA
//      (ZP-FR-ENG-001 FR-003): the FR-2026-H1/H2 packs are edited in Draft on
//      the "Statutory Values" tab, then approved and activated like any
//      other country's pack. France has no income-tax brackets, so the
//      shared "Tax Slabs" tab is hidden.
//
//   2. "Employer & Authority Configuration" — FranceAuthorityPanel, the
//      organization-scoped payroll_fr_* data (SIREN profile, establishments,
//      governed effectif, SIRET rate packs, PAS rates, DSN, readiness). That
//      data is not pack-versioned, so it is NOT a pack tab — it is always
//      reachable, with or without a pack selected.
//
// The selected view and organization live in the URL (?view=&org=) so they
// survive navigation and every France section shares ONE organization.
const extraTabs = [
  {
    key: "statutory-reference", label: "Statutory Values", icon: BookOpen, after: "overview",
    isVisible: (pack) => pack?.packType === "tax",
    render: ({ pack, onReload }) => <FranceStatutoryReferencePanel pack={pack} onReload={onReload} />,
  },
];

const VIEWS = [
  { key: "tax", label: "Tax Configuration" },
  { key: "employer", label: "Employer & Authority Configuration" },
];

export default function FRCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const view = searchParams.get("view") === "employer" ? "employer" : "tax";
  const organizationId = useMemo(() => {
    const raw = Number(searchParams.get("org"));
    return Number.isInteger(raw) && raw > 0 ? raw : null;
  }, [searchParams]);

  function updateParams(changes) {
    const next = new URLSearchParams(searchParams);
    Object.entries(changes).forEach(([k, v]) => (v == null ? next.delete(k) : next.set(k, String(v))));
    setSearchParams(next, { replace: true });
  }

  return (
    <div>
      <div className="mb-5 flex gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {VIEWS.map((v) => (
          <button
            key={v.key} onClick={() => updateParams({ view: v.key === "tax" ? null : v.key })}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${view === v.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {v.label}
          </button>
        ))}
      </div>
      {view === "tax" ? (
        <>
          <p className="mb-4 rounded-lg border border-border bg-surface-muted px-3 py-2 text-[11px] text-foreground-muted">
            France statutory content ships as the Draft packs <span className="font-mono">FR-2026-H1</span> (Jan–Apr)
            and <span className="font-mono">FR-2026-H2</span> (from 1 May, the PAS neutral-grid boundary). Review and edit
            values on a pack&apos;s <b>Statutory Values</b> tab, then approve and set it Active. Organization data (PAS,
            establishments, employer rates, DSN) is under <b>Employer &amp; Authority Configuration</b>.
          </p>
          <JurisdictionLayout
            country="FR" countryName="France"
            initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
            onStateChange={(state) =>
              navigate(state ? `/super-admin/compliance/france/${encodeURIComponent(state)}` : "/super-admin/compliance/france")
            }
            extraTabs={extraTabs}
            hiddenTabs={["slabs"]}
          />
        </>
      ) : (
        <FranceAuthorityPanel
          organizationId={organizationId}
          onOrganizationIdChange={(id) => updateParams({ org: id })}
          section={searchParams.get("section") || "overview"}
          onSectionChange={(s) => updateParams({ section: s === "overview" ? null : s })}
        />
      )}
    </div>
  );
}
