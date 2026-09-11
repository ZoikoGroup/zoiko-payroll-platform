import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Modal from "../../Modal";
import { getTaxabilityRules, upsertTaxabilityRule, deleteTaxabilityRule } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";

// India Earnings & Taxability (ZP-TAX-IN-2026-27-001 §7/§8/§9/§10/§13,
// gap-closure Phase B/E/G) — which of an employee's own named salary
// components count toward FOUR independent wage bases: Code Wages (the
// Labour Codes' 50%-cap add-back mechanism, feeding EPF/EPS/EDLI when
// that switch is on), and three plainer per-component sums added in
// Phase G (2026-09-11) — EPF's own wage base, ESI's wage base, and
// Professional Tax's assessment base — for orgs that want to configure
// those without the Code Wages add-back complexity. All four back the
// SAME TaxabilityRule model (tax_component="code_wages"/"epf_base"/
// "esi_base"/"pt_base" respectively), so this is one tab with a program
// selector rather than four near-identical tabs — same shape Canada's
// CATaxabilityMatrixTab.jsx already established for its own 4 programs.
//
// Defaults (india.py's _resolve_code_wages_classification /
// _classify_wage_base) differ per program, exactly matching each
// program's ORIGINAL hardcoded behavior with no rows configured:
//   - Code Wages: only "basic" defaults to core-included.
//   - EPF base:   only "basic" defaults to included (today's
//                 `pf_base_pre_ceiling = basic`).
//   - ESI / PT base: every component defaults to included (today's
//                 plain `gross`-based calculation).
// With no row configured for a component on any of the four, engine
// behavior is completely unchanged — every row here is an override.

const PROGRAMS = [
  { value: "code_wages", label: "Code Wages (EPF/EPS/EDLI add-back)", defaultIncluded: new Set(["basic"]), includedLabel: "Core included wages", excludedLabel: "Excluded (subject to 50% add-back test)" },
  { value: "epf_base", label: "EPF Wage Base", defaultIncluded: new Set(["basic"]), includedLabel: "Included in EPF wage base", excludedLabel: "Excluded from EPF wage base" },
  { value: "esi_base", label: "ESI Wage Base", defaultIncluded: null, includedLabel: "Included in ESI wage base", excludedLabel: "Excluded from ESI wage base" },
  { value: "pt_base", label: "Professional Tax Assessment Base", defaultIncluded: null, includedLabel: "Included in PT assessment base", excludedLabel: "Excluded from PT assessment base" },
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
  const [isTaxable, setIsTaxable] = useState(true);
  const [state, setState] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await upsertTaxabilityRule({
        jurisdictionCountry: "IN", jurisdictionState: state.trim() || null,
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

  const program = PROGRAMS.find((p) => p.value === taxComponent) || PROGRAMS[0];

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
            <option value="1">{program.includedLabel}</option>
            <option value="0">{program.excludedLabel}</option>
          </select>
        </div>
        <div>
          <label className={labelClass}>State <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional — leave blank for country-wide)</span></label>
          <input className={inputClass} value={state} onChange={(e) => setState(e.target.value)} placeholder="e.g. Karnataka" />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

export default function INCodeWagesTab() {
  const [program, setProgram] = useState("code_wages");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [toast, setToast] = useState(null);

  const activeProgram = PROGRAMS.find((p) => p.value === program) || PROGRAMS[0];

  function addToast(message, type) {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }

  async function refresh() {
    setLoading(true);
    try {
      const data = await getTaxabilityRules({ country: "IN", taxComponent: program });
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

  const defaultText = activeProgram.defaultIncluded
    ? `With no row configured for a component, it defaults to: ${[...activeProgram.defaultIncluded].join(", ")} = included, every other component excluded.`
    : "With no row configured for a component, every component defaults to included (today's plain gross-based calculation).";

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
        {defaultText} Add a row below only to override that default for a specific component.
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
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No overrides configured — every component uses the default above.</p>
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
                      {r.isTaxable ? activeProgram.includedLabel : activeProgram.excludedLabel}
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
