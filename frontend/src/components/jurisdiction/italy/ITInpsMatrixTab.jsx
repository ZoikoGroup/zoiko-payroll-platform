import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalContributionRate } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { IT_MATRIX_FAMILIES, isMatrixRow } from "./itComponentConfig";

// §7 INPS classification matrix (IT-002). Each row is a ContributionRate
// scoped to CSC_<csc>[_CA_<ca>] with the worker class in tax_regime and the
// UniEmens causale in filing_status. The generic rate form writes the PACK's
// tax_regime and drops filing_status, which would silently move a row to the
// wrong worker class — so the matrix has this dedicated form, writing through
// the SAME canonical endpoint (editable-pack guard and audit server-side).
const splitScope = (scope) => {
  const m = /^CSC_([A-Z0-9]+)(?:_CA_([A-Z0-9]+))?$/.exec(scope || "");
  return m ? { csc: m[1], ca: m[2] || "" } : { csc: "", ca: "" };
};

function MatrixRowModal({ pack, row, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const { csc, ca } = splitScope(row?.jurisdictionState);
  const [form, setForm] = useState({
    csc, ca, workerClass: row?.taxRegime || "", family: row?.componentKey || "it_inps_ivs",
    causale: row?.filingStatus || "", employee: row?.employeeRatePct ?? "", employer: row?.employerRatePct ?? "",
    reason: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (e) => { setForm((f) => ({ ...f, [field]: e.target.value })); setError(null); };
  const code = (v) => v.trim().toUpperCase();

  async function save() {
    const problems = [];
    if (!/^[A-Z0-9]+$/.test(code(form.csc))) problems.push("Enter the CSC code (letters and digits).");
    if (form.ca && !/^[A-Z0-9]+$/.test(code(form.ca))) problems.push("The CA code must be letters and digits.");
    if (!/^[A-Z_]{3,20}$/.test(code(form.workerClass))) problems.push("Enter the worker class code (e.g. IMPIEGATO).");
    if (!/^it_inps_[a-z_]+$/.test(form.family.trim())) problems.push("The family key must start with it_inps_.");
    if (form.employee === "" && form.employer === "") problems.push("Enter at least one share.");
    if (form.family === "it_inps_ivs" && (form.employee === "" || form.employer === "")) {
      problems.push("IVS needs both the employee and the employer share.");
    }
    if (!form.reason.trim()) problems.push("A reason citing the INPS source is required.");
    if (problems.length) { setError(problems.join(" ")); return; }
    const scope = `CSC_${code(form.csc)}${form.ca.trim() ? `_CA_${code(form.ca)}` : ""}`;
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: row?.id, jurisdictionPackId: pack.id, jurisdictionCountry: "IT",
        jurisdictionState: scope, taxRegime: code(form.workerClass), filingStatus: form.causale.trim() || null,
        componentKey: form.family.trim(), label: `INPS ${form.family.trim()} ${scope} ${code(form.workerClass)}`.slice(0, 100),
        employeeSharePct: form.employee === "" ? null : form.employee,
        employerSharePct: form.employer === "" ? null : form.employer,
        flatAmount: null, sortOrder: row?.sortOrder ?? 0, reason: form.reason,
      });
      addToast?.("INPS matrix row saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save the row.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`${row ? "Edit" : "Add"} INPS matrix row`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div><label className={labelClass} htmlFor="it-mx-csc">CSC</label>
            <input id="it-mx-csc" className={inputClass} value={form.csc} onChange={set("csc")} placeholder="70501" /></div>
          <div><label className={labelClass} htmlFor="it-mx-ca">CA (optional)</label>
            <input id="it-mx-ca" className={inputClass} value={form.ca} onChange={set("ca")} /></div>
          <div><label className={labelClass} htmlFor="it-mx-class">Worker class</label>
            <input id="it-mx-class" className={inputClass} value={form.workerClass} onChange={set("workerClass")} placeholder="IMPIEGATO" /></div>
          <div><label className={labelClass} htmlFor="it-mx-family">Contribution family</label>
            <input id="it-mx-family" className={inputClass} list="it-mx-families" value={form.family} onChange={set("family")} />
            <datalist id="it-mx-families">{IT_MATRIX_FAMILIES.map((f) => <option key={f} value={f} />)}</datalist></div>
          <div><label className={labelClass} htmlFor="it-mx-causale">UniEmens causale (optional)</label>
            <input id="it-mx-causale" className={inputClass} value={form.causale} onChange={set("causale")} /></div>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div><label className={labelClass} htmlFor="it-mx-ee">Employee share (%)</label>
            <input id="it-mx-ee" className={inputClass} inputMode="decimal" value={form.employee} onChange={set("employee")} /></div>
          <div><label className={labelClass} htmlFor="it-mx-er">Employer share (%)</label>
            <input id="it-mx-er" className={inputClass} inputMode="decimal" value={form.employer} onChange={set("employer")} /></div>
        </div>
        <div><label className={labelClass} htmlFor="it-mx-reason">Reason and INPS source (recorded in the audit trail)</label>
          <textarea id="it-mx-reason" rows={2} className={inputClass} value={form.reason} onChange={set("reason")}
            placeholder="e.g. INPS circolare n. … / 2026, CSC 70501 aliquote" /></div>
        {error && <p role="alert" className="text-sm font-medium text-error">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-foreground-secondary hover:bg-surface-muted">Cancel</button>
          <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function ITInpsMatrixTab({ pack, rates, onReload, onDeleteRate }) {
  const [editing, setEditing] = useState(null);   // { row? }
  const rows = (rates || []).filter(isMatrixRow).sort((a, b) =>
    String(a.jurisdictionState).localeCompare(String(b.jurisdictionState))
    || String(a.taxRegime || "").localeCompare(String(b.taxRegime || ""))
    || String(a.componentKey).localeCompare(String(b.componentKey)));
  const editable = pack && pack.status !== "Active";
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        INPS rates by employer classification (CSC, plus CA where the employer has one) and worker class. A worker
        whose classification has no IVS row here is blocked — there is no national average rate (IT-002). Codes
        must come from the current INPS catalogs (IT-043); the seeded rows are Draft placeholders.
      </p>
      {editable && (
        <button onClick={() => setEditing({})}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add matrix row
        </button>
      )}
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No INPS matrix rows in this pack.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Classification</th>
                <th className="px-3 py-2">Worker class</th>
                <th className="px-3 py-2">Family</th>
                <th className="px-3 py-2">Causale</th>
                <th className="px-3 py-2">Employee</th>
                <th className="px-3 py-2">Employer</th>
                <th className="px-3 py-2 w-16"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="px-3 py-2 font-mono text-foreground-secondary">{r.jurisdictionState}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.taxRegime || "—"}</td>
                  <td className="px-3 py-2 font-mono text-foreground-secondary">{r.componentKey}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.filingStatus || "—"}</td>
                  <td className="px-3 py-2 font-medium text-foreground">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                  <td className="px-3 py-2 font-medium text-foreground">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                  <td className="px-3 py-2">
                    {editable && (
                      <div className="flex items-center gap-1">
                        <button aria-label="Edit matrix row" onClick={() => setEditing({ row: r })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                        <button aria-label="Delete matrix row" onClick={() => onDeleteRate(r)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
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
        <MatrixRowModal pack={pack} row={editing.row} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
