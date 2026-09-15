import { useEffect, useState } from "react";
import {
  FileCheck2, HeartPulse, Percent, ShieldCheck, Layers, Clock3, Gauge,
  Landmark, Church, RefreshCcw, FileSearch, History, ArrowRight, Banknote,
} from "lucide-react";
import {
  listPapReleases, listHealthFunds, listContributionCeilings, listPvConfigurations,
  listMinijobMidijobParameters,
  listEarningTaxabilityRules, listOvertimePremiumCategories, listOvertimeGrundlohnCaps,
  listGermanyAccidentInsuranceProfiles, listGermanyChurchTaxExceptions, getChurchTaxMatrix,
  getSourceArtifacts,
} from "../../../../service/superAdminService";
import { listElstamChangeListBatches } from "../../../../service/payrollService";
import { describeLoadError } from "../../../../service/errorClassification";
import { countLabel, latestStatus, churchTaxSummary } from "./germanyOverviewSummaries";

// Germany country-level overview — the landing content for
// Compliance -> Germany, giving one place that surfaces every existing
// statutory registry area without the operator needing to know the
// /germany/registries deep link exists. Every count below comes from the
// SAME list endpoints the registry tabs themselves already call (see
// GermanyStatutoryRegistriesPage.jsx) — no new backend endpoint, no
// aggregated "dashboard" API, and nothing invented: a card whose list
// call fails with SCHEMA_UNAVAILABLE (a migration not applied to this
// environment) or a network error shows "Not available"/"Backend
// unreachable" rather than a fabricated 0 or success state.
const AREAS = [
  { key: "pap", label: "PAP / Releases", icon: FileCheck2, loader: () => listPapReleases(), summarize: (rows) => latestStatus(rows) },
  { key: "health-funds", label: "Health Funds", icon: HeartPulse, loader: () => listHealthFunds(), summarize: countLabel("health fund") },
  { key: "ceilings", label: "Contribution Ceilings", icon: Percent, loader: () => listContributionCeilings(), summarize: countLabel("ceiling") },
  { key: "pv", label: "PV Configuration", icon: ShieldCheck, loader: () => listPvConfigurations(), summarize: countLabel("configuration") },
  // No seed data in any environment (Phase 8BK migration, deliberately) —
  // each consuming calculation falls back to its own existing hardcoded
  // default until a real PUBLISHED row exists, so a genuine 0 here means
  // "no override configured yet", not a bug, unlike the church-tax tile
  // above whose base matrix is always non-empty.
  { key: "minijob-midijob", label: "Minijob/Midijob Parameters", icon: Banknote, loader: () => listMinijobMidijobParameters(), summarize: countLabel("parameter") },
  { key: "earning-taxability", label: "Earning Taxability", icon: Layers, loader: () => listEarningTaxabilityRules(), summarize: countLabel("rule") },
  { key: "overtime-premium-categories", label: "Overtime Premium Categories", icon: Clock3, loader: () => listOvertimePremiumCategories(), summarize: countLabel("category", "categories") },
  { key: "overtime-grundlohn-caps", label: "Overtime Grundlohn Caps", icon: Gauge, loader: () => listOvertimeGrundlohnCaps(), summarize: countLabel("cap") },
  { key: "employer-levies", label: "Employer Levies (Accident Insurance)", icon: Landmark, loader: () => listGermanyAccidentInsuranceProfiles(), summarize: countLabel("profile") },
  {
    key: "church-tax",
    label: "Church Tax",
    icon: Church,
    // The 16-Land base matrix is a hardcoded constant, always present —
    // unlike every other area here, zero rows in the sub-Land exceptions
    // registry is the normal case, not "not configured" (see
    // churchTaxSummary's own doc comment). Load both so the summary can
    // distinguish "no church tax config" (never true) from "no exceptions"
    // (usually true).
    loader: () => Promise.all([getChurchTaxMatrix(), listGermanyChurchTaxExceptions()])
      .then(([matrix, exceptions]) => ({ laender: matrix?.laender, exceptions })),
    summarize: churchTaxSummary,
  },
  { key: "elstam-batches", label: "ELStAM Change-List Batches", icon: RefreshCcw, loader: () => listElstamChangeListBatches(), summarize: countLabel("batch") },
  { key: "source-evidence", label: "Source Evidence", icon: FileSearch, loader: () => getSourceArtifacts(), summarize: countLabel("artifact") },
];

function AreaCard({ area, onSelectSection }) {
  const [state, setState] = useState({ loading: true, rows: null, error: null });

  useEffect(() => {
    let cancelled = false;
    area.loader()
      .then((rows) => !cancelled && setState({ loading: false, rows, error: null }))
      .catch((err) => !cancelled && setState({ loading: false, rows: null, error: describeLoadError(err) }));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const Icon = area.icon;

  return (
    <button
      onClick={() => onSelectSection(area.key)}
      className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
    >
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon size={16} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground truncate">{area.label}</p>
          {state.loading ? (
            <p className="text-xs text-foreground-disabled">Loading…</p>
          ) : state.error ? (
            <p className="text-xs text-warning">
              {state.error.schemaUnavailable ? "Not available — migration pending" : state.error.networkError ? "Backend unreachable" : "Failed to load"}
            </p>
          ) : (
            <p className="text-xs text-foreground-muted">{area.summarize(state.rows)}</p>
          )}
        </div>
      </div>
      <ArrowRight size={14} className="shrink-0 text-foreground-disabled" />
    </button>
  );
}

export default function DEOverviewDashboard({ onSelectSection }) {
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border bg-surface p-5">
        <h3 className="mb-1 text-sm font-bold text-foreground">Germany payroll compliance</h3>
        <p className="text-xs text-foreground-muted">
          Statutory configuration Zoiko's payroll engine reads from for Germany — PAP, health funds (SI contribution
          rates), contribution ceilings, PV (Pflegeversicherung) configuration, church tax, overtime treatment,
          employer levies, ELStAM change-list batches, and the source evidence backing each of them. Select any
          area below to open it directly, or use the tabs above.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {AREAS.map((area) => (
          <AreaCard key={area.key} area={area} onSelectSection={onSelectSection} />
        ))}
        <button
          onClick={() => onSelectSection("audit")}
          className="flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
        >
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <History size={16} />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground truncate">Audit / History</p>
              <p className="text-xs text-foreground-muted">Tax configuration audit trail</p>
            </div>
          </div>
          <ArrowRight size={14} className="shrink-0 text-foreground-disabled" />
        </button>
      </div>
    </div>
  );
}
