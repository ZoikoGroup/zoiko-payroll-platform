import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { addNzTableRow, deleteNzTableRow } from "../../../service/superAdminService";
import { card } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { inputClass, labelClass } from "../constants";
import NZRowEditor from "./NZRowEditor";
import { AUTHORITY_TABLES, isEditablePack } from "./nzContent";
import { EditButton } from "./NZPackRowsTab";
import { band, governanceError, governancePayload, useSources } from "./nzForm";
import { ErrorNote, GovernanceFields, SignedPill } from "./nzShared";

// The New Zealand authority tables the specification does not reproduce
// (PAYE method, secondary / ND rates, IETC, variation codes, extra-pay and
// holiday-advance methods, IRD examples, public holidays, ACC classes). Each
// stays empty — and every calculation needing it blocked — until a Super Admin
// fills it from the archived source and it is signed.

function AddRowForm({ pack, table, sources, onAdded }) {
  const [values, setValues] = useState({});
  const [governance, setGovernance] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function add() {
    const problem = governanceError(governance);
    if (problem) { setError(problem); return; }
    const body = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "" && v != null));
    setSaving(true);
    setError(null);
    try {
      await addNzTableRow(pack.id, table.ruleType, { ...body, ...governancePayload(governance) });
      setValues({});
      onAdded();
    } catch (err) {
      setError(err.message || "The row was refused.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-3 rounded-lg border border-dashed border-border p-3" data-testid={`nz-add-${table.ruleType}`}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {table.fields.map((field) => (
          <div key={field.name}>
            <label className={labelClass}>{field.label}</label>
            {field.options ? (
              <select className={inputClass} value={values[field.name] ?? ""}
                onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}>
                {!field.options.includes("") && <option value="">Select…</option>}
                {field.options.map((o) => <option key={o || "none"} value={o}>{o || "National"}</option>)}
              </select>
            ) : (
              <input className={inputClass} type={field.type === "date" ? "date" : "text"}
                inputMode={field.type === "number" ? "decimal" : undefined} value={values[field.name] ?? ""}
                onChange={(e) => setValues({ ...values, [field.name]: e.target.value })} />
            )}
          </div>
        ))}
      </div>
      <GovernanceFields value={governance} onChange={setGovernance} sources={sources} />
      <ErrorNote message={error} />
      <button type="button" onClick={add} disabled={saving}
        className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
        <Plus size={13} /> {saving ? "Adding…" : governance.specialistVerified ? "Add and sign" : "Add (stays pending)"}
      </button>
    </div>
  );
}

export default function NZAuthorityTablesTab({ pack, slabs, onReload }) {
  const sources = useSources();
  const [open, setOpen] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const editable = isEditablePack(pack);

  async function remove(row) {
    const reason = window.prompt("Why is this row being removed?");
    if (!reason || !reason.trim()) return;
    setError(null);
    try {
      await deleteNzTableRow(row.id, reason.trim());
      onReload?.();
    } catch (err) {
      setError(err.message || "The row could not be removed.");
    }
  }

  return (
    <div className="space-y-4" data-testid="nz-authority-tables">
      <ErrorNote message={error} />
      {AUTHORITY_TABLES.map((table) => {
        const rows = (slabs || []).filter((row) => row.ruleType === table.ruleType);
        return (
          <div key={table.ruleType} className={card}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="text-[14px] font-semibold text-foreground">{table.label}</h3>
                <p className="text-[11px] text-foreground-muted">
                  <span className="font-mono">{table.ruleType}</span> · signed at {table.gate}
                  {table.employerContent ? " · employer content (not needed to activate the national pack)" : ""}
                </p>
              </div>
              {editable && (
                <button type="button" onClick={() => setOpen(open === table.ruleType ? null : table.ruleType)}
                  className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                  <Plus size={12} /> Add row
                </button>
              )}
            </div>
            {rows.length === 0 ? (
              <p className="mt-2 rounded-lg border border-warning/40 bg-warning/10 p-2 text-[12px] text-foreground-secondary">
                Empty — needs the archived authority source, signed at {table.gate}. Every calculation that needs it is blocked.
              </p>
            ) : (
              <div className="mt-2">
                <Table rows={rows} columns={[
                  { label: "Key", render: (row) => row.filingStatus || row.effectiveFrom || "—" },
                  { label: "Name", render: (row) => String(row.rateLabel || "").replace("[PENDING G1]", "").trim() },
                  { label: "Region", render: (row) => row.jurisdictionState || (table.ruleType === "NZ_PUBLIC_HOLIDAY" ? "National" : "—") },
                  { label: "Band / value", render: (row) => (row.ratePct != null && Number(row.ratePct) !== 0 ? `${row.ratePct}%`
                    : row.flatAmount ?? (row.minAmount != null || row.maxAmount != null ? band(row) : row.taxFormula || "—")) },
                  { label: "Status", render: (row) => <SignedPill row={row} /> },
                  ...(editable ? [{ label: "", render: (row) => (
                    <span className="inline-flex gap-1">
                      <EditButton onClick={() => setEditing(row)} />
                      <button type="button" onClick={() => remove(row)} aria-label="Remove row"
                        className="rounded border border-border px-1.5 py-0.5 text-error hover:bg-error/5">
                        <Trash2 size={11} />
                      </button>
                    </span>
                  ) }] : []),
                ]} />
              </div>
            )}
            {open === table.ruleType && (
              <AddRowForm pack={pack} table={table} sources={sources}
                onAdded={() => { setOpen(null); onReload?.(); }} />
            )}
          </div>
        );
      })}
      {editing && (
        <NZRowEditor kind="slab" row={editing} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
