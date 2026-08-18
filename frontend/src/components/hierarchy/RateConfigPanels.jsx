import { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Pencil, Check, X } from "lucide-react";
import { useToast } from "../../context/ToastContext";
import ConfirmDialog from "../ConfirmDialog";
import * as hs from "../../service/hierarchyService";

// Generic Rate/Parameter Configuration panels (render by TaxRule.rule_type),
// shared between the Super Admin Jurisdiction Explorer (full CRUD, incl.
// rule/version creation and status transitions) and Statutory Rates (numeric
// values only — no rule/version creation, no status transitions; that page
// only ever calls RateConfigurationPanel/ParameterConfigurationPanel, never
// AddRuleInline). One implementation, two consumers — adding a new
// rule_type later means one new render branch here, never a new page.

const compactInputClass =
  "w-full rounded-md border border-border-strong bg-background px-2.5 py-1.5 text-xs text-foreground shadow-sm " +
  "focus:outline-none focus:ring-2 focus:ring-focus-ring/30";

function SlabRows({ rule, onChanged }) {
  const { addToast } = useToast() || {};
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({});
  const [deleting, setDeleting] = useState(null);

  function startEdit(slab) {
    setEditingId(slab.id);
    setDraft({
      min_amount: slab.min_amount, max_amount: slab.max_amount ?? "",
      rate_pct: slab.rate_pct ?? "", flat_fee_amount: slab.flat_fee_amount ?? "", rate_label: slab.rate_label ?? "",
    });
  }
  function startAdd() {
    setEditingId("new");
    setDraft({ min_amount: "", max_amount: "", rate_pct: "", flat_fee_amount: "", rate_label: "" });
  }
  async function save() {
    try {
      await hs.upsertTaxRuleSlab({
        id: editingId === "new" ? undefined : editingId, tax_rule_id: rule.id,
        min_amount: draft.min_amount || 0, max_amount: draft.max_amount === "" ? null : draft.max_amount,
        rate_pct: draft.rate_pct === "" ? null : draft.rate_pct,
        flat_fee_amount: draft.flat_fee_amount === "" ? null : draft.flat_fee_amount,
        rate_label: draft.rate_label || null, sort_order: rule.slabs.length,
      });
      setEditingId(null);
      onChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to save slab.", "error");
    }
  }
  async function confirmDelete() {
    try {
      await hs.deleteTaxRuleSlab(deleting.id);
      setDeleting(null);
      onChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to delete.", "error");
    }
  }

  const draftRow = (key) => (
    <tr key={key} className="bg-primary/5">
      <td className="p-1"><input className={compactInputClass} type="number" placeholder="Min" value={draft.min_amount} onChange={(e) => setDraft((d) => ({ ...d, min_amount: e.target.value }))} /></td>
      <td className="p-1"><input className={compactInputClass} type="number" placeholder="and above" value={draft.max_amount} onChange={(e) => setDraft((d) => ({ ...d, max_amount: e.target.value }))} /></td>
      <td className="p-1"><input className={compactInputClass} type="number" step="0.01" placeholder="%" value={draft.rate_pct} onChange={(e) => setDraft((d) => ({ ...d, rate_pct: e.target.value }))} /></td>
      <td className="p-1"><input className={compactInputClass} type="number" step="0.01" placeholder="flat" value={draft.flat_fee_amount} onChange={(e) => setDraft((d) => ({ ...d, flat_fee_amount: e.target.value }))} /></td>
      <td className="p-1"><input className={compactInputClass} placeholder="label" value={draft.rate_label} onChange={(e) => setDraft((d) => ({ ...d, rate_label: e.target.value }))} /></td>
      <td className="p-1">
        <div className="flex gap-1">
          <button type="button" onClick={save} className="rounded p-1 text-primary hover:bg-primary/10"><Check size={14} /></button>
          <button type="button" onClick={() => setEditingId(null)} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted"><X size={14} /></button>
        </div>
      </td>
    </tr>
  );

  return (
    <div>
      <table className="w-full text-xs">
        <thead className="text-left text-foreground-muted">
          <tr><th className="p-1">Min</th><th className="p-1">Max</th><th className="p-1">Rate %</th><th className="p-1">Flat Fee</th><th className="p-1">Label</th><th className="p-1 w-16"></th></tr>
        </thead>
        <tbody>
          {rule.slabs.map((s) => editingId === s.id ? draftRow(s.id) : (
            <tr key={s.id} className="border-t border-border-light">
              <td className="p-1.5">{s.min_amount}</td>
              <td className="p-1.5">{s.max_amount ?? "and above"}</td>
              <td className="p-1.5">{s.rate_pct != null ? `${s.rate_pct}%` : "—"}</td>
              <td className="p-1.5">{s.flat_fee_amount ?? "—"}</td>
              <td className="p-1.5">{s.rate_label || "—"}</td>
              <td className="p-1.5">
                <div className="flex gap-1">
                  <button type="button" onClick={() => startEdit(s)} disabled={editingId !== null} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted disabled:opacity-40"><Pencil size={11} /></button>
                  <button type="button" onClick={() => setDeleting(s)} disabled={editingId !== null} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light disabled:opacity-40"><Trash2 size={11} /></button>
                </div>
              </td>
            </tr>
          ))}
          {editingId === "new" && draftRow("new")}
        </tbody>
      </table>
      {editingId === null && (
        <button type="button" onClick={startAdd} className="mt-2 inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-[11px] text-foreground-secondary hover:border-primary hover:text-primary">
          <Plus size={11} /> Add Slab
        </button>
      )}
      {deleting && (
        <ConfirmDialog title="Delete Slab" message={`Delete the ${deleting.min_amount}–${deleting.max_amount ?? "∞"} band?`} busy={false} onConfirm={confirmDelete} onClose={() => setDeleting(null)} />
      )}
    </div>
  );
}

function RateRow({ rule, onChanged }) {
  const { addToast } = useToast() || {};
  const existing = rule.rates[0];
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});

  function startEdit() {
    setDraft({
      employee_rate_pct: existing?.employee_rate_pct ?? "", employer_rate_pct: existing?.employer_rate_pct ?? "",
      employee_flat_amount: existing?.employee_flat_amount ?? "", employer_flat_amount: existing?.employer_flat_amount ?? "",
    });
    setEditing(true);
  }
  async function save() {
    try {
      await hs.upsertTaxRuleRate({
        id: existing?.id, tax_rule_id: rule.id,
        employee_rate_pct: draft.employee_rate_pct || null, employer_rate_pct: draft.employer_rate_pct || null,
        employee_flat_amount: draft.employee_flat_amount || null, employer_flat_amount: draft.employer_flat_amount || null,
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    }
  }

  if (editing) {
    return (
      <div className="grid grid-cols-2 gap-2 rounded-lg border border-primary/30 bg-primary/5 p-2">
        <div><label className="text-[10px] text-foreground-muted">Employee %</label><input className={compactInputClass} type="number" step="0.01" value={draft.employee_rate_pct} onChange={(e) => setDraft((d) => ({ ...d, employee_rate_pct: e.target.value }))} /></div>
        <div><label className="text-[10px] text-foreground-muted">Employer %</label><input className={compactInputClass} type="number" step="0.01" value={draft.employer_rate_pct} onChange={(e) => setDraft((d) => ({ ...d, employer_rate_pct: e.target.value }))} /></div>
        <div><label className="text-[10px] text-foreground-muted">Employee Flat</label><input className={compactInputClass} type="number" step="0.01" value={draft.employee_flat_amount} onChange={(e) => setDraft((d) => ({ ...d, employee_flat_amount: e.target.value }))} /></div>
        <div><label className="text-[10px] text-foreground-muted">Employer Flat</label><input className={compactInputClass} type="number" step="0.01" value={draft.employer_flat_amount} onChange={(e) => setDraft((d) => ({ ...d, employer_flat_amount: e.target.value }))} /></div>
        <div className="col-span-2 flex justify-end gap-1">
          <button type="button" onClick={() => setEditing(false)} className="rounded-md border border-border px-2 py-1 text-[11px] text-foreground-secondary">Cancel</button>
          <button type="button" onClick={save} className="rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-white">Save</button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between rounded-lg border border-border-light p-2 text-xs">
      <div className="flex gap-4">
        <span>Employee: <strong>{existing?.employee_rate_pct != null ? `${existing.employee_rate_pct}%` : existing?.employee_flat_amount ?? "—"}</strong></span>
        <span>Employer: <strong>{existing?.employer_rate_pct != null ? `${existing.employer_rate_pct}%` : existing?.employer_flat_amount ?? "—"}</strong></span>
      </div>
      <button type="button" onClick={startEdit} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
    </div>
  );
}

export function AddRuleInline({ taxVersionId, onAdded }) {
  const { addToast } = useToast() || {};
  const [adding, setAdding] = useState(false);
  const [ruleType, setRuleType] = useState("PROGRESSIVE_BRACKET");
  const [label, setLabel] = useState("");

  async function submit() {
    try {
      await hs.upsertTaxRule({ tax_version_id: taxVersionId, rule_type: ruleType, label, sort_order: 0 });
      setAdding(false); setLabel("");
      onAdded();
    } catch (err) {
      addToast?.(err.message || "Failed to add rule.", "error");
    }
  }
  if (!adding) {
    return (
      <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:border-primary hover:text-primary">
        <Plus size={13} /> Add Rule
      </button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface p-2">
      <select value={ruleType} onChange={(e) => setRuleType(e.target.value)} className={compactInputClass + " w-auto"}>
        <option value="PROGRESSIVE_BRACKET">Progressive Bracket</option>
        <option value="FLAT_RATE">Flat Rate</option>
        <option value="CONTRIBUTION">Contribution</option>
        <option value="FIXED_PLUS_MARGINAL">Fixed + Marginal</option>
        <option value="TABLE_LOOKUP">Table Lookup</option>
        <option value="FORMULA">Formula</option>
      </select>
      <input className={compactInputClass + " w-auto flex-1"} placeholder="Label (e.g. Income Tax Slabs)" value={label} onChange={(e) => setLabel(e.target.value)} />
      <button type="button" onClick={submit} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white">Add</button>
      <button type="button" onClick={() => setAdding(false)} className="rounded-md p-1.5 text-foreground-disabled hover:bg-surface-muted"><X size={14} /></button>
    </div>
  );
}

export function RateConfigurationPanel({ taxVersionId, allowRuleCreation = true, allowRuleDeletion = true }) {
  const { addToast } = useToast() || {};
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deletingRule, setDeletingRule] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    hs.getTaxRules(taxVersionId).then(setRules).catch((err) => addToast?.(err.message, "error")).finally(() => setLoading(false));
  }, [taxVersionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  async function confirmDeleteRule() {
    try {
      await hs.deleteTaxRule(deletingRule.id);
      setDeletingRule(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to delete rule.", "error");
    }
  }

  if (loading) return <p className="py-6 text-center text-xs text-foreground-disabled">Loading…</p>;

  return (
    <div className="space-y-4">
      {rules.length === 0 && (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-4 text-center text-xs text-foreground-disabled">
          No rules configured for this version yet.
        </p>
      )}
      {rules.map((rule) => (
        <div key={rule.id} className="rounded-lg border border-border p-3">
          <div className="mb-2 flex items-center justify-between">
            <div>
              <span className="rounded-full bg-category-teal/10 px-2 py-0.5 text-[10px] font-bold text-category-teal">{rule.rule_type}</span>
              <span className="ml-2 text-xs font-medium text-foreground">{rule.label}</span>
            </div>
            {allowRuleDeletion && (
              <button type="button" onClick={() => setDeletingRule(rule)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={13} /></button>
            )}
          </div>
          {rule.rule_type === "FORMULA" ? (
            <pre className="whitespace-pre-wrap rounded-md bg-background p-2 text-[11px] text-foreground-secondary">{rule.formula_expression || "(no formula set)"}</pre>
          ) : rule.rule_type === "FLAT_RATE" || rule.rule_type === "CONTRIBUTION" ? (
            <RateRow rule={rule} onChanged={load} />
          ) : (
            <SlabRows rule={rule} onChanged={load} />
          )}
        </div>
      ))}
      {allowRuleCreation && <AddRuleInline taxVersionId={taxVersionId} onAdded={load} />}
      {deletingRule && (
        <ConfirmDialog title="Delete Rule" message={`Delete "${deletingRule.label}" and everything under it?`} busy={false} onConfirm={confirmDeleteRule} onClose={() => setDeletingRule(null)} />
      )}
    </div>
  );
}

export function ParameterConfigurationPanel({ taxVersionId }) {
  const { addToast } = useToast() || {};
  const [params, setParams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({});
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    hs.getTaxParameters(taxVersionId).then(setParams).finally(() => setLoading(false));
  }, [taxVersionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  function startEdit(p) {
    setEditingId(p.id);
    setDraft({ parameter_key: p.parameter_key, label: p.label, value_numeric: p.value_numeric ?? "", unit: p.unit || "currency" });
  }
  function startAdd() {
    setEditingId("new");
    setDraft({ parameter_key: "", label: "", value_numeric: "", unit: "currency" });
  }
  async function save() {
    try {
      await hs.upsertTaxParameter({
        id: editingId === "new" ? undefined : editingId, tax_version_id: taxVersionId,
        parameter_key: draft.parameter_key, label: draft.label,
        value_numeric: draft.value_numeric || null, unit: draft.unit,
      });
      setEditingId(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    }
  }
  async function confirmDelete() {
    try {
      await hs.deleteTaxParameter(deleting.id);
      setDeleting(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to delete.", "error");
    }
  }

  if (loading) return <p className="py-6 text-center text-xs text-foreground-disabled">Loading…</p>;

  return (
    <div className="space-y-2">
      {params.map((p) => editingId === p.id ? (
        <div key={p.id} className="grid grid-cols-4 gap-2 rounded-lg border border-primary/30 bg-primary/5 p-2">
          <input className={compactInputClass} placeholder="key" value={draft.parameter_key} onChange={(e) => setDraft((d) => ({ ...d, parameter_key: e.target.value }))} />
          <input className={compactInputClass} placeholder="Label" value={draft.label} onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} />
          <input className={compactInputClass} type="number" step="0.01" placeholder="Value" value={draft.value_numeric} onChange={(e) => setDraft((d) => ({ ...d, value_numeric: e.target.value }))} />
          <div className="flex gap-1">
            <button type="button" onClick={save} className="rounded p-1.5 text-primary hover:bg-primary/10"><Check size={14} /></button>
            <button type="button" onClick={() => setEditingId(null)} className="rounded p-1.5 text-foreground-disabled hover:bg-surface-muted"><X size={14} /></button>
          </div>
        </div>
      ) : (
        <div key={p.id} className="flex items-center justify-between rounded-lg border border-border-light p-2 text-xs">
          <div>
            <span className="font-mono text-foreground-secondary">{p.parameter_key}</span>
            <span className="ml-2 text-foreground">{p.label}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-medium">{p.value_numeric ?? p.value_text ?? "—"}</span>
            <button type="button" onClick={() => startEdit(p)} disabled={editingId !== null} className="rounded p-1 text-foreground-disabled hover:text-primary disabled:opacity-40"><Pencil size={12} /></button>
            <button type="button" onClick={() => setDeleting(p)} disabled={editingId !== null} className="rounded p-1 text-foreground-disabled hover:text-error disabled:opacity-40"><Trash2 size={12} /></button>
          </div>
        </div>
      ))}
      {editingId === "new" && (
        <div className="grid grid-cols-4 gap-2 rounded-lg border border-primary/30 bg-primary/5 p-2">
          <input className={compactInputClass} placeholder="key" value={draft.parameter_key} onChange={(e) => setDraft((d) => ({ ...d, parameter_key: e.target.value }))} />
          <input className={compactInputClass} placeholder="Label" value={draft.label} onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} />
          <input className={compactInputClass} type="number" step="0.01" placeholder="Value" value={draft.value_numeric} onChange={(e) => setDraft((d) => ({ ...d, value_numeric: e.target.value }))} />
          <div className="flex gap-1">
            <button type="button" onClick={save} className="rounded p-1.5 text-primary hover:bg-primary/10"><Check size={14} /></button>
            <button type="button" onClick={() => setEditingId(null)} className="rounded p-1.5 text-foreground-disabled hover:bg-surface-muted"><X size={14} /></button>
          </div>
        </div>
      )}
      {editingId === null && (
        <button type="button" onClick={startAdd} className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-[11px] text-foreground-secondary hover:border-primary hover:text-primary">
          <Plus size={11} /> Add Parameter
        </button>
      )}
      {deleting && (
        <ConfirmDialog title="Delete Parameter" message={`Delete "${deleting.label}"?`} busy={false} onConfirm={confirmDelete} onClose={() => setDeleting(null)} />
      )}
    </div>
  );
}
