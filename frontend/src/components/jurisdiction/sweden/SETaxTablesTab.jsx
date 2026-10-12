import { useMemo, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import SEBandFormModal from "./SEBandFormModal";
import { SE_ONE_TIME_PAYMENT_RULE, SE_TAX_TABLE_RULE } from "./seComponentConfig";

const isScaffold = (s) => !["AMOUNT", "PERCENT"].includes((s.assessmentBasis || "").toUpperCase());

// Skatteverket tax tables 29–42 and the one-time-payment tables (spec §5:
// "Tax tables are authority content, not application code"). The seed
// creates one inert Draft scaffold per table/column; the engine refuses to
// calculate from a scaffold, and the pack cannot go Active while any remain.
// Deleting is through the shared confirm flow (onDeleteSlab).
export default function SETaxTablesTab({ pack, slabs, onReload, onDeleteSlab }) {
  const [kind, setKind] = useState(SE_TAX_TABLE_RULE);
  const [table, setTable] = useState("");
  const [editing, setEditing] = useState(null);   // { slab?, initial? }

  const rows = useMemo(() => (slabs || []).filter((s) => s.ruleType === kind), [slabs, kind]);
  const tables = useMemo(() => Array.from(new Set(rows.map((s) => s.taxTableNumber).filter(Boolean))).sort(), [rows]);
  const visible = kind === SE_TAX_TABLE_RULE && table ? rows.filter((s) => s.taxTableNumber === table) : rows;
  const sorted = [...visible].sort((a, b) =>
    String(a.taxTableNumber || "").localeCompare(String(b.taxTableNumber || ""))
    || String(a.taxColumn || "").localeCompare(String(b.taxColumn || ""), undefined, { numeric: true })
    || Number(a.minAmount) - Number(b.minAmount));
  const scaffolds = rows.filter(isScaffold).length;
  const editable = pack && pack.status !== "Active";

  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        Enter bands exactly as Skatteverket publishes them. Monthly tax tables: the monthly pay band and either the
        withholding amount or, for top incomes, the published percentage. One-time payments: the expected annual
        income band and the published percentage. The engine never interpolates between bands or turns an amount
        into a percentage.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Table family" className="inline-flex rounded-lg border border-border p-0.5">
          {[[SE_TAX_TABLE_RULE, "Tax tables 29–42"], [SE_ONE_TIME_PAYMENT_RULE, "One-time payments"]].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={kind === k} onClick={() => { setKind(k); setTable(""); }}
              className={`rounded-md px-3 py-1 text-xs font-semibold ${kind === k ? "bg-primary text-white" : "text-foreground-secondary hover:bg-surface-muted"}`}>
              {label}
            </button>
          ))}
        </div>
        {kind === SE_TAX_TABLE_RULE && (
          <select aria-label="Filter by table" value={table} onChange={(e) => setTable(e.target.value)}
            className="rounded-lg border border-border bg-background px-2 py-1 text-xs">
            <option value="">All tables</option>
            {tables.map((t) => <option key={t} value={t}>Table {t}</option>)}
          </select>
        )}
        <span className={`text-xs ${scaffolds ? "text-warning" : "text-success"}`}>
          {scaffolds ? `${scaffolds} unfilled Draft scaffold row(s) — replace them with published bands` : "No unfilled scaffolds"}
        </span>
        {editable && (
          <button onClick={() => setEditing({ initial: { taxTableNumber: table || "" } })}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
            <Plus size={13} /> Add band
          </button>
        )}
      </div>
      {sorted.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No bands in this pack.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                {kind === SE_TAX_TABLE_RULE && <th className="px-3 py-2">Table</th>}
                <th className="px-3 py-2">Column</th>
                <th className="px-3 py-2">From</th>
                <th className="px-3 py-2">Up to</th>
                <th className="px-3 py-2">Published value</th>
                <th className="px-3 py-2 w-16"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.id} className="border-t border-border-light">
                  {kind === SE_TAX_TABLE_RULE && <td className="px-3 py-2 text-foreground-secondary">{s.taxTableNumber || "—"}</td>}
                  <td className="px-3 py-2 text-foreground-secondary">{s.taxColumn || "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.minAmount}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.maxAmount ?? "and above"}</td>
                  <td className="px-3 py-2 font-medium text-foreground">
                    {isScaffold(s) ? <span className="text-warning">Draft scaffold — not yet entered</span>
                      : s.assessmentBasis === "AMOUNT" ? `SEK ${s.flatAmount}` : `${s.ratePct}%`}
                  </td>
                  <td className="px-3 py-2">
                    {editable && (
                      <div className="flex items-center gap-1">
                        <button aria-label="Edit band" onClick={() => setEditing({ slab: s })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                        <button aria-label="Delete band" onClick={() => onDeleteSlab(s)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <SEBandFormModal pack={pack} kind={kind} slab={editing.slab} initial={editing.initial}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
