import { useState } from "react";
import { Plus } from "lucide-react";
import { retireBeSlabRow } from "../../../service/superAdminService";
import { useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import { ContributionRatesTable, PackTableHeader, TaxSlabsTable } from "../PackRowTables";
import BEEmptyRows from "./BEEmptyRows";
import BERowEditor from "./BERowEditor";
import { AddRowForm } from "./BESlabRowsSection";
import { TAB_GROUPS, cleanLabel, isDraftPack, isEditablePack, loadConfiguration, slabRowsFor } from "./beShared";

// Belgium "Contribution Rates" and "Tax Slabs" tabs, in the same tables every
// other country uses (PackRowTables.jsx). Rows come from the Belgium
// configuration API (GET .../belgium/packs/{id}/configuration) — the generic
// canonical editor is refused for Belgium by the backend, so edits go through
// the governed BERowEditor (source + reason; a second Super Admin signs) and
// band rows are added / retired through the governed slab endpoints. Values
// are shown exactly as stored; nothing is combined or computed here.

const isActive = (pack) => pack?.status === "Active";
// Belgium has no state-level rows and no filing statuses (the slab
// filing-status column carries the dimension, shown as "Dimension").
const HIDDEN_COLUMNS = ["state", "filingStatus"];

function SignedBadge({ signed }) {
  return signed ? (
    <span className="inline-flex rounded border border-success/40 bg-success/10 px-1.5 py-0.5 text-[10px] font-semibold text-success">Signed</span>
  ) : (
    <span className="inline-flex rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px] font-semibold text-warning">Pending G1</span>
  );
}

const inForce = (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window");
const statusColumn = { key: "status", label: "Status", render: (row) => <SignedBadge signed={row.signed} /> };
const inForceColumn = { key: "inForce", label: "In force", render: inForce };

function ReadOnlyNote({ pack }) {
  if (isActive(pack) || isEditablePack(pack)) return null;
  return <p className="text-[11px] text-foreground-muted">{pack.status} pack — read-only. Create a new version to change a value.</p>;
}

// Scalar rows of the given catalogue groups, one section per group.
function scalarSections(config, groups) {
  return groups.map((group) => {
    const section = config.groups?.[group];
    if (!section) return null;
    const rows = section.rows
      .filter((row) => !config.slabSpecs?.[row.componentKey])
      .map((row) => ({ ...row, label: cleanLabel(row.label) }));
    return { key: group, label: section.label, rows };
  }).filter(Boolean);
}

// Band / formula / dimension keys of the given groups.
function slabKeys(config, groups) {
  return groups.flatMap((group) => (config.groups?.[group]?.rows || [])
    .filter((row) => config.slabSpecs?.[row.componentKey])
    .map((row) => ({ key: row.componentKey, title: cleanLabel(row.label) })));
}

function ScalarRatesTable({ pack, config, sections, onReload }) {
  const [editing, setEditing] = useState(null);
  const editable = isEditablePack(pack);
  const notSupported = (row) => row.textValue && row.textValue === config.vocabulary?.[row.componentKey]?.notSupported;
  const raw = (row) => config.groups?.[row.group]?.rows.find((r) => r.id === row.id) || row;
  return (
    <>
      <ContributionRatesTable
        sections={sections}
        hideColumns={HIDDEN_COLUMNS}
        onEdit={editable || isActive(pack) ? (row) => setEditing(raw(row)) : undefined}
        actionsDisabled={isActive(pack)}
        emptyText="No rows for these groups in the selected pack."
        componentNote={(row) => (
          <>
            {row.textValue ? (
              <p className="mt-0.5 text-[11px] text-foreground-secondary">
                {notSupported(row) ? "Not supported (blocked)" : row.textValue}
              </p>
            ) : null}
            {row.referenceOnly ? <p className="mt-0.5 text-[11px] text-warning" data-testid="be-reference-note">{row.referenceNote}</p> : null}
          </>
        )}
        extraColumns={[inForceColumn, statusColumn]}
      />
      {editing && (
        <BERowEditor kind="rate" row={editing} config={config} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload(); }} />
      )}
    </>
  );
}

function SlabKeyTable({ pack, config, rowKey, title, onReload, onImport }) {
  const spec = config.slabSpecs?.[rowKey];
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  if (!spec) return null;
  const editable = isEditablePack(pack);
  const source = slabRowsFor(config, rowKey);
  const rows = source.map((row) => ({ ...row, rateLabel: cleanLabel(row.label) }));
  const raw = (row) => source.find((r) => r.id === row.id) || row;
  const hasFormula = rows.some((row) => row.taxFormula);

  async function retire(row) {
    const reason = window.prompt(`Reason for retiring this ${spec.ruleType} row (audited):`);
    if (!reason || !reason.trim()) return;
    setError(null);
    try {
      await retireBeSlabRow(row.id, reason.trim());
      onReload();
    } catch (err) {
      setError(err.message || "The row could not be retired.");
    }
  }

  return (
    <div className="space-y-2" data-testid={`be-slab-${spec.ruleType}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[13px] font-semibold text-foreground">{title}</h4>
        {editable && !adding && rows.length > 0 && (
          <button type="button" onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
            <Plus size={13} /> Add row
          </button>
        )}
      </div>
      <TaxSlabsTable
        rows={rows}
        hideColumns={HIDDEN_COLUMNS}
        onEdit={editable || isActive(pack) ? (row) => setEditing(raw(row)) : undefined}
        onDelete={(editable && isDraftPack(pack)) || isActive(pack) ? retire : undefined}
        actionsDisabled={isActive(pack)}
        emptyState={<BEEmptyRows title={title} pack={pack} editable={editable} onAdd={() => setAdding(true)} onImport={onImport} />}
        extraColumns={[
          ...(spec.dimensions.length ? [{ key: "dimension", label: "Dimension", render: (row) => row.component || "—" }] : []),
          { key: "amount", label: "Amount", render: (row) => (row.flatAmount != null ? row.flatAmount : "—") },
          ...(hasFormula ? [{ key: "formula", label: "Formula", render: (row) => (
            <span className="font-mono text-[11px]">{row.taxFormula || "—"}</span>
          ) }] : []),
          inForceColumn, statusColumn,
        ]}
      />
      <ErrorNote message={error} />
      {adding && (
        <AddRowForm pack={pack} rowKey={rowKey} spec={spec} onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); onReload(); }} />
      )}
      {editing && (
        <BERowEditor kind="slab" row={editing} config={config} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload(); }} />
      )}
    </div>
  );
}

function useConfiguration(pack) {
  return useLoad(() => loadConfiguration(pack));
}

function Loading({ error, loading, config }) {
  if (error) return <ErrorNote message={error} />;
  if (loading && !config) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return null;
}

function RatesLoaded({ pack, onImport }) {
  const [config, error, loading, reload] = useConfiguration(pack);
  if (error || !config) return <Loading error={error} loading={loading} config={config} />;
  const groups = [...TAB_GROUPS.onssEmployee, ...TAB_GROUPS.onssEmployer];
  const bands = slabKeys(config, groups);
  return (
    <div className="space-y-4" data-testid="be-rates-tab">
      <PackTableHeader
        description="ONSS/RSZ employee and employer contributions and reductions. Employer rows are resolved by employer category and worker code; no all-in employer rate is shown."
        locked={isActive(pack)} lockedNoun="rates"
      />
      <ReadOnlyNote pack={pack} />
      <ScalarRatesTable pack={pack} config={config} sections={scalarSections(config, groups)} onReload={reload} />
      {bands.map((b) => <SlabKeyTable key={b.key} pack={pack} config={config} rowKey={b.key} title={b.title} onReload={reload} onImport={onImport} />)}
    </div>
  );
}

function SlabsLoaded({ pack, onImport }) {
  const [config, error, loading, reload] = useConfiguration(pack);
  if (error || !config) return <Loading error={error} loading={loading} config={config} />;
  const groups = TAB_GROUPS.withholding;
  const bands = slabKeys(config, groups);
  const parameters = scalarSections(config, groups);
  const hasParameters = parameters.some((s) => s.rows.length > 0);
  return (
    <div className="space-y-4" data-testid="be-slabs-tab">
      <PackTableHeader
        description="Professional withholding (précompte professionnel / bedrijfsvoorheffing, Annex III). Regular and exceptional remuneration are separate strategies."
        locked={isActive(pack)} lockedNoun="brackets"
      />
      <ReadOnlyNote pack={pack} />
      {bands.length === 0 && !hasParameters && (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No withholding rows in this pack.</p>
      )}
      {bands.map((b) => <SlabKeyTable key={b.key} pack={pack} config={config} rowKey={b.key} title={b.title} onReload={reload} onImport={onImport} />)}
      {hasParameters && (
        <div className="space-y-2">
          <h4 className="text-[13px] font-semibold text-foreground">Withholding parameters</h4>
          <ScalarRatesTable pack={pack} config={config} sections={parameters} onReload={reload} />
        </div>
      )}
    </div>
  );
}

// "Import from file" opens Readiness, where the content workbook import lives
// (Signing status: preview, all-or-nothing, source per row, rows unsigned).
const importer = (onNavigateTab) => (onNavigateTab ? () => onNavigateTab("be-release") : undefined);

export function BEContributionRatesTab({ pack, onNavigateTab }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return <RatesLoaded key={pack.id} pack={pack} onImport={importer(onNavigateTab)} />;
}

export function BETaxSlabsTab({ pack, onNavigateTab }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return <SlabsLoaded key={pack.id} pack={pack} onImport={importer(onNavigateTab)} />;
}
