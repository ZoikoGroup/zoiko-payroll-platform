import Collapsible from "../../../../components/jurisdiction/Collapsible";
import Notice from "../../../../components/jurisdiction/Notice";
import { ContributionRatesTable, PackTableHeader } from "../../../../components/jurisdiction/PackRowTables";
import { useLoad } from "../../../../components/jurisdiction/japan/jpFormat";
import { getGermanyPackContributions } from "../../../../service/superAdminService";
import {
  ContributionCeilingsTab, HealthFundsTab, MinijobMidijobParametersTab, PvConfigTab,
} from "../../GermanyStatutoryRegistriesPage";
import { ENGINE_FILES } from "./deShared";

// Germany Contributions tab on the shared layout: the SAME shared rates table
// as every country, grouped by section. Rows come from
// GET .../germany/compliance-pack/{id}/contributions: the German registry rows
// (health funds, PV, ceilings, Minijob/Midijob parameters) and one row per
// fallback constant the engine reads from code, marked "Built into engine, no
// data row" with its source file. Every value is the stored / coded value,
// shown as returned. The pack's own rate rows (RV / ALV / GKV override keys)
// are listed first with the standard edit icons (locked on an Active pack).
// The registry editors (maker-checker) stay below, unchanged.

const inForce = (r) => (r.origin === "engine" ? "engine default" : `${r.effectiveFrom || "—"} → ${r.effectiveTo || "open"}`);

function note(r) {
  const parts = [];
  if (r.origin === "engine") parts.push(`${r.status} · ${r.sourceFile ? r.sourceFile.split("/").pop() : ENGINE_FILES.defaults}`);
  if (r.origin === "data" && r.linkedToPack === false) parts.push("registry row not linked to a pack (engine fallback path)");
  if (r.factor != null) parts.push("coefficient");
  if (r.note) parts.push(r.note);
  if (r.overriddenBy) parts.push(`overridden by ${r.overriddenBy}`);
  return parts.length ? <p className="text-[10px] text-foreground-muted" data-testid="de-row-note">{parts.join(" · ")}</p> : null;
}

function StatusCell({ row }) {
  if (row.origin !== "engine") return row.status || "—";
  // The full "Built into engine, no data row · <file>" text is in the row's note.
  return (
    <span title={row.status} className="whitespace-nowrap rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-[10px] font-semibold text-warning">
      Built into engine
    </span>
  );
}

const EXTRA_COLUMNS = [
  { key: "total", label: "Total %", render: (r) => (r.totalRatePct != null ? `${r.totalRatePct}%` : "—") },
  { key: "inForce", label: "In force", cellClass: "px-3 py-2 whitespace-nowrap text-foreground-secondary", render: inForce },
  { key: "status", label: "Status", render: (r) => <StatusCell row={r} /> },
];

// A stored coefficient (Midijob formula) shows in the amount column, as stored.
const shape = (r) => ({ ...r, flatAmount: r.flatAmount ?? r.factor ?? null });

export default function DEContributionsTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const [view, error] = useLoad(() => getGermanyPackContributions(pack.id));
  const locked = pack.status === "Active";
  const packRows = (rates || []).map((r) => ({ ...r, status: "Pack row", origin: "pack" }));
  return (
    <div className="space-y-4" data-testid="de-contributions">
      <div className="space-y-2">
        <PackTableHeader
          description="This pack's own contribution rows — the canonical RV / ALV / GKV override keys the engine reads (rv_pension, alv_unemployment, gkv_general)."
          locked={locked} lockedNoun="contribution rates" addLabel="Add Rate" onAdd={onAddRate} />
        <ContributionRatesTable rows={packRows} onEdit={onEditRate} onDelete={onDeleteRate} actionsDisabled={locked}
          hideColumns={["state", "filingStatus"]}
          extraColumns={[{ key: "inForce", label: "In force", render: inForce }, { key: "status", label: "Status", render: () => "Pack row" }]}
          emptyText="This pack has no rate rows of its own; the engine uses the registry rows and engine defaults below." />
      </div>

      <div className="space-y-2">
        <p className="text-xs text-foreground-muted">
          Registry rows linked to this pack (or unlinked rows dated inside it) and the engine&apos;s fallback values held in
          code. Values are shown exactly as stored; nothing here is editable — use the registry editors below.
        </p>
        {error && <p className="text-xs text-error">{error}</p>}
        {!view && !error && <p className="text-xs text-foreground-muted">Loading…</p>}
        {view && (
          <ContributionRatesTable
            sections={view.sections.map((s) => ({ key: s.key, label: s.label, rows: s.rows.map(shape) }))}
            hideColumns={["state", "filingStatus"]} extraColumns={EXTRA_COLUMNS} componentNote={note} />
        )}
        {view && (
          <Notice tone="info" title="Accident insurance" testId="de-accident-notice">{view.accidentInsurance}</Notice>
        )}
      </div>

      <h3 className="pt-1 text-[13px] font-semibold text-foreground">Registry editors</h3>
      <Collapsible title="Health funds and U1 tariffs" testId="de-reg-health-funds"
        summary="Krankenkasse Zusatzbeitrag, U1 / U2 levies and U1 tariffs (maker-checker lifecycle).">
        <HealthFundsTab />
      </Collapsible>
      <Collapsible title="Contribution ceilings" testId="de-reg-ceilings" summary="Beitragsbemessungsgrenzen per branch.">
        <ContributionCeilingsTab />
      </Collapsible>
      <Collapsible title="Care insurance (PV) configuration" testId="de-reg-pv"
        summary="PV rates by child category, including the childless surcharge and Saxony split.">
        <PvConfigTab />
      </Collapsible>
      <Collapsible title="Minijob / Midijob parameters" testId="de-reg-minijob"
        summary="Registry overrides of the engine's Minijob / Midijob defaults.">
        <MinijobMidijobParametersTab />
      </Collapsible>
    </div>
  );
}
