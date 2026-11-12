import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { addBeSlabRow, retireBeSlabRow } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { EditButton } from "../new_zealand/NZPackRowsTab";
import { governanceError, governancePayload, useSources } from "../new_zealand/nzForm";
import { ErrorNote, GovernanceFields, SignedPill } from "../new_zealand/nzShared";
import BERowEditor from "./BERowEditor";
import { cleanLabel, isDraftPack, isEditablePack, slabRowsFor } from "./beShared";

// The governed slab rows of one band / formula / table key (rule type BE_<KEY>):
// list, add (source + reason; sign with a reviewed source) and retire (Draft
// packs only; reason; the backend audits the full before-image). The fields and
// dimension names come from config.slabSpecs[key]; the backend validates again.

const OPTIONAL = { band: ["maxAmount", "ratePct", "flatAmount", "effectiveFrom", "effectiveTo"],
  formula: ["effectiveFrom", "effectiveTo"], table: [] };
const FIELD_LABELS = { minAmount: "From", maxAmount: "To (empty = open)", ratePct: "Rate %", flatAmount: "Amount",
  formulaText: "Formula (stored as text; never executed)", name: "Name", date: "Date",
  effectiveFrom: "Row effective from", effectiveTo: "Row effective to" };
const DATE_FIELDS = new Set(["date", "effectiveFrom", "effectiveTo"]);

function AddRowForm({ pack, rowKey, spec, onClose, onSaved }) {
  const sources = useSources();
  const fields = [...spec.fields, ...(OPTIONAL[spec.kind] || [])];
  const [values, setValues] = useState({});
  const [dims, setDims] = useState({});
  const [governance, setGovernance] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    const problem = governanceError(governance);
    if (problem) { setError(problem); return; }
    const payload = Object.fromEntries(Object.entries(values).filter(([, v]) => String(v ?? "").trim() !== ""));
    if (spec.dimensions.length) {
      payload.dimension = spec.dimensions.map((name) => `${name}=${(dims[name] || "").trim()}`).join(";");
    }
    setSaving(true);
    setError(null);
    try {
      await addBeSlabRow(pack.id, rowKey, { ...payload, ...governancePayload(governance) });
      onSaved();
    } catch (err) {
      setError(err.message || "The row was refused.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-3 rounded-lg border border-border p-3" data-testid="be-add-slab-row">
      <div className="grid grid-cols-2 gap-3">
        {spec.dimensions.map((name) => (
          <div key={name}>
            <label className={labelClass}>Dimension {name} *</label>
            <input className={inputClass} value={dims[name] || ""} onChange={(e) => setDims({ ...dims, [name]: e.target.value })} />
          </div>
        ))}
        {fields.map((name) => (
          <div key={name} className={name === "formulaText" ? "col-span-2" : ""}>
            <label className={labelClass}>{FIELD_LABELS[name] || name}{spec.fields.includes(name) ? " *" : ""}</label>
            <input className={inputClass} type={DATE_FIELDS.has(name) ? "date" : "text"}
              inputMode={DATE_FIELDS.has(name) || name === "name" || name === "formulaText" ? undefined : "decimal"}
              value={values[name] || ""} onChange={(e) => setValues({ ...values, [name]: e.target.value })} />
          </div>
        ))}
      </div>
      <GovernanceFields value={governance} onChange={setGovernance} sources={sources} />
      <ErrorNote message={error} />
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose}
          className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary">Cancel</button>
        <button type="button" onClick={save} disabled={saving}
          className="rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50">
          {saving ? "Saving…" : governance.specialistVerified ? "Add and sign" : "Add (stays pending)"}
        </button>
      </div>
    </div>
  );
}

export default function BESlabRowsSection({ pack, config, rowKey, title, onReload }) {
  const spec = config?.slabSpecs?.[rowKey];
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  if (!spec) return null;
  const rows = slabRowsFor(config, rowKey);
  const editable = isEditablePack(pack);

  async function retire(row) {
    const reason = window.prompt(`Reason for retiring this ${spec.ruleType} row (audited):`);
    if (!reason || !reason.trim()) return;
    setError(null);
    try {
      await retireBeSlabRow(row.id, reason.trim());
      onReload?.();
    } catch (err) {
      setError(err.message || "The row could not be retired.");
    }
  }

  return (
    <div className={card} data-testid={`be-slab-${spec.ruleType}`}>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-[13px] font-semibold text-foreground">{title} — rows ({spec.ruleType})</h4>
        {editable && !adding && (
          <button type="button" onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
            <Plus size={11} /> Add row
          </button>
        )}
      </div>
      <Table rows={rows} empty="No rows yet — the key blocks until rows are added and signed (or the key is signed NOT_SUPPORTED)."
        columns={[
          ...(spec.dimensions.length ? [{ label: "Dimension", render: (row) => row.component || "—" }] : []),
          { label: "Row", render: (row) => cleanLabel(row.label) },
          { label: "From / to", render: (row) => (row.minAmount != null ? `${row.minAmount} → ${row.maxAmount ?? "open"}` : "—") },
          { label: "Rate % / amount", render: (row) => [row.ratePct, row.flatAmount].filter((v) => v != null).join(" / ") || "—" },
          { label: "In force", render: (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window") },
          { label: "Status", render: (row) => <SignedPill row={row} /> },
          ...(editable ? [{ label: "", render: (row) => (
            <span className="inline-flex gap-1">
              <EditButton onClick={() => setEditing(row)} />
              {isDraftPack(pack) && (
                <button type="button" onClick={() => retire(row)} title="Retire (Draft only)"
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] font-semibold text-error hover:bg-surface-muted">
                  <Trash2 size={11} /> Retire
                </button>
              )}
            </span>
          ) }] : []),
        ]} />
      <ErrorNote message={error} />
      {adding && (
        <AddRowForm pack={pack} rowKey={rowKey} spec={spec} onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); onReload?.(); }} />
      )}
      {editing && (
        <BERowEditor kind="slab" row={editing} config={config} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
