import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Modal from "../../Modal";
import { getTaxabilityRules, upsertTaxabilityRule, deleteTaxabilityRule } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";

// Canada Taxability Matrix (ZP-TAX-CA-2026-001 §17/AC-17, gap-closure
// Phase 5) — per-program (federal tax/provincial tax/CPP/EI) earning-
// component classification. Mirrors INCodeWagesTab.jsx's structure
// exactly (same TaxabilityRule model/CRUD), but Canada has FOUR
// tax_components instead of India's one ("code_wages"), so this adds a
// program selector; and the default here is the OPPOSITE of India's —
// every component counts (is_taxable=True) unless explicitly excluded,
// matching today's single-ctx.gross behavior. Dormant behind
// shared._CA_TAXABILITY_MATRIX_ENABLED_COUNTRIES until enabled.

const PROGRAMS = [
  { value: "income_tax_federal", label: "Federal Income Tax" },
  { value: "income_tax_provincial", label: "Provincial / Quebec Income Tax" },
  { value: "cpp_pensionable", label: "CPP / QPP Pensionable Earnings" },
  { value: "ei_insurable", label: "EI / QPIP Insurable Earnings" },
];

const COMPONENTS = [
  { value: "basic", label: "Basic" },
  { value: "hra", label: "HRA" },
  { value: "special_allowance", label: "Special Allowance" },
  { value: "overtime", label: "Overtime" },
  { value: "additional_compensation", label: "Additional Compensation" },
  { value: "named_allowances", label: "Named Allowances (policy-defined)" },
];

function RuleFormModal({ taxComponent, onClose, onSaved, addToast }) {
  const [earningType, setEarningType] = useState("additional_compensation");
  const [isTaxable, setIsTaxable] = useState(false);
  const [state, setState] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await upsertTaxabilityRule({
        jurisdictionCountry: "CA", jurisdictionState: state.trim() || null,
        taxComponent, earningType, isTaxable,
      });
      addToast?.("Classification saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save classification.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Add / Update Classification" onClose={onClose} maxWidth="max-w-sm">
      <div className="space-y-3">
        <div>
          <label className={labelClass}>Component</label>
          <select className={inputClass} value={earningType} onChange={(e) => setEarningType(e.target.value)}>
            {COMPONENTS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Classification</label>
          <select className={inputClass} value={isTaxable ? "1" : "0"} onChange={(e) => setIsTaxable(e.target.value === "1")}>
            <option value="1">Counts toward this program</option>
            <option value="0">Excluded from this program</option>
          </select>
        </div>
        <div>
          <label className={labelClass}>State <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional — leave blank for country-wide)</span></label>
          <input className={inputClass} value={state} onChange={(e) => setState(e.target.value)} placeholder="e.g. ON" />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

export default function CATaxabilityMatrixTab() {
  const [program, setProgram] = useState("income_tax_federal");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [toast, setToast] = useState(null);

  function addToast(message, type) {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }

  async function refresh() {
    setLoading(true);
    try {
      const data = await getTaxabilityRules({ country: "CA", taxComponent: program });
      setRows(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, [program]);

  async function handleDelete(id) {
    try {
      await deleteTaxabilityRule(id);
      refresh();
    } catch (err) {
      addToast(err.message || "Failed to delete.", "error");
    }
  }

  return (
    <div className="space-y-3">
      {toast && (
        <div className={`rounded-lg px-3 py-2 text-xs font-semibold ${toast.type === "error" ? "bg-error/10 text-error" : "bg-success/10 text-success"}`}>
          {toast.message}
        </div>
      )}
      <div className="flex items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 flex-wrap">
        {PROGRAMS.map((p) => (
          <button
            key={p.value} onClick={() => setProgram(p.value)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${program === p.value ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="rounded-lg border border-info/30 bg-info/5 px-3 py-2 text-[11px] text-foreground-secondary">
        With no row configured for a component, it counts toward every program by default (today's existing
        behavior — one gross figure feeds all of CPP/EI/federal/provincial tax). Add a row below only to EXCLUDE a
        component from this specific program. Dormant until a Super Admin enables the Taxability Matrix rollout
        switch — configuring rows here has no effect on live payroll until then.
      </div>
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Overrides only — see default above.</p>
        <button onClick={() => setShowForm(true)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Override
        </button>
      </div>
      {loading ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No overrides configured — every component counts toward this program.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Component</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Classification</th>
                <th className="px-3 py-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="px-3 py-2 font-medium text-foreground">{COMPONENTS.find((c) => c.value === r.earningType)?.label || r.earningType}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.jurisdictionState || "Country-wide"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 font-semibold ${r.isTaxable ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                      {r.isTaxable ? "Included" : "Excluded"}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => handleDelete(r.id)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {showForm && (
        <RuleFormModal taxComponent={program} onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); refresh(); }} addToast={addToast} />
      )}
    </div>
  );
}
