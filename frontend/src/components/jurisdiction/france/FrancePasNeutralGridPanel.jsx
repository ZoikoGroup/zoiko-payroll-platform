import { useCallback, useEffect, useState } from "react";
import { Percent, Plus, Pencil, Trash2 } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import {
  getCanonicalTaxSlabs, upsertCanonicalTaxSlab, deleteCanonicalTaxSlab,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass, labelClass } from "../constants";

const RULE_TYPE = "FR_PAS_NEUTRAL";
const BLANK = { minAmount: "", maxAmount: "", ratePct: "", effectiveFrom: "", effectiveTo: "" };

function windowLabel(row) {
  if (!row.effectiveFrom && !row.effectiveTo) return "Whole pack";
  return `${row.effectiveFrom || "…"} → ${row.effectiveTo || "open"}`;
}

// The statutory non-personalized PAS grid (FR-009) as pack content: monthly
// PAS-base bands (from inclusive, to exclusive) with the withholding rate,
// dated per band so the 1 May 2026 grid switches without a new pack. The
// engine picks the band for an employee on the NEUTRAL rate (no DGFiP
// personalized rate) and blocks if no band covers the pay date. Values must
// come from the official BOFiP grid — this editor never pre-fills numbers.
export default function FrancePasNeutralGridPanel({ pack, editable }) {
  const { addToast } = useToast() || {};
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // { id?, form, error, saving }

  const load = useCallback(() => {
    setLoading(true);
    getCanonicalTaxSlabs({ jurisdictionPackId: pack.id })
      .then((all) => { setRows((all || []).filter((r) => r.ruleType === RULE_TYPE)); setError(null); })
      .catch((err) => setError(describeLoadError(err)))
      .finally(() => setLoading(false));
  }, [pack.id]);

  useEffect(() => {
    load();
  }, [load]);

  const sorted = [...rows].sort((a, b) =>
    String(a.effectiveFrom || "").localeCompare(String(b.effectiveFrom || "")) || Number(a.minAmount) - Number(b.minAmount));

  async function save() {
    const f = editing.form;
    const min = Number(f.minAmount);
    const max = f.maxAmount === "" ? null : Number(f.maxAmount);
    const rate = Number(f.ratePct);
    let problem = "";
    if (f.minAmount === "" || Number.isNaN(min) || min < 0) problem = "“From” must be a monthly amount ≥ 0.";
    else if (max !== null && (Number.isNaN(max) || max <= min)) problem = "“To” must be greater than “From” (leave empty for the top band).";
    else if (f.ratePct === "" || Number.isNaN(rate) || rate < 0 || rate > 100) problem = "Rate must be between 0 and 100%.";
    else if (f.effectiveFrom && f.effectiveTo && f.effectiveTo < f.effectiveFrom) problem = "Effective to is before effective from.";
    if (problem) return setEditing((e) => ({ ...e, error: problem }));
    setEditing((e) => ({ ...e, saving: true, error: "" }));
    try {
      await upsertCanonicalTaxSlab({
        id: editing.id, jurisdictionPackId: pack.id, jurisdictionCountry: "FR",
        minAmount: min, maxAmount: max, ratePct: rate, rateLabel: `${rate}%`, taxFormula: "",
        ruleType: RULE_TYPE, effectiveFrom: f.effectiveFrom || null, effectiveTo: f.effectiveTo || null,
        reason: "PAS neutral grid (BOFiP)",
      });
      addToast?.("Grid band saved.", "success");
      setEditing(null);
      load();
    } catch (err) {
      setEditing((e) => ({ ...e, saving: false, error: loadErrorText(describeLoadError(err)) }));
    }
  }

  async function remove(row) {
    try {
      await deleteCanonicalTaxSlab(row.id);
      addToast?.("Grid band removed.", "success");
      load();
    } catch (err) {
      addToast?.(loadErrorText(describeLoadError(err)), "error");
    }
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-background px-3 py-2">
        <p className="flex items-center gap-1.5 text-xs font-bold text-foreground">
          <Percent size={13} /> PAS neutral grid (non-personalized rate, FR-009)
        </p>
        {editable && (
          <button onClick={() => setEditing({ form: { ...BLANK }, error: "", saving: false })}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
            <Plus size={11} /> Add band
          </button>
        )}
      </div>
      {loading ? (
        <p className="px-3 py-4 text-xs text-foreground-disabled">Loading grid…</p>
      ) : error ? (
        <p className="px-3 py-4 text-xs text-foreground-muted">{loadErrorText(error)}</p>
      ) : sorted.length === 0 ? (
        <p className="px-3 py-4 text-xs text-foreground-muted">
          No grid loaded — employees without a DGFiP personalized rate block until the official BOFiP 2026 grid
          (pre- and post-1 May) is entered here.
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-left text-foreground-muted">
            <tr>
              <th className="px-3 py-2">Monthly PAS base from</th>
              <th className="px-3 py-2">to (exclusive)</th>
              <th className="px-3 py-2">Rate</th>
              <th className="px-3 py-2">Applies</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.id} className="border-t border-border-light">
                <td className="px-3 py-2 font-mono tabular-nums">{r.minAmount}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{r.maxAmount ?? "and above"}</td>
                <td className="px-3 py-2 font-mono font-bold tabular-nums">{r.ratePct}%</td>
                <td className="px-3 py-2 text-[11px] text-foreground-muted">{windowLabel(r)}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {editable && (
                    <>
                      <button onClick={() => setEditing({ id: r.id, error: "", saving: false, form: {
                        minAmount: String(r.minAmount), maxAmount: r.maxAmount == null ? "" : String(r.maxAmount),
                        ratePct: String(r.ratePct), effectiveFrom: r.effectiveFrom || "", effectiveTo: r.effectiveTo || "" } })}
                        className="mr-1 rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      <button onClick={() => remove(r)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editing && (
        <Modal title={editing.id ? "Edit grid band" : "Add grid band"} onClose={() => setEditing(null)}>
          <div className="grid grid-cols-2 gap-3 text-xs">
            {[
              ["minAmount", "Monthly base from (€) *", "e.g. 0"],
              ["maxAmount", "to (€, exclusive — empty = top band)", "e.g. 1620"],
              ["ratePct", "Rate % *", "e.g. 0"],
            ].map(([key, label, ph]) => (
              <div key={key}>
                <label className={labelClass}>{label}</label>
                <input className={inputClass} value={editing.form[key]} placeholder={ph}
                  onChange={(e) => setEditing((s) => ({ ...s, form: { ...s.form, [key]: e.target.value } }))} />
              </div>
            ))}
            <div />
            <div>
              <label className={labelClass}>Effective from</label>
              <input type="date" className={inputClass} value={editing.form.effectiveFrom}
                onChange={(e) => setEditing((s) => ({ ...s, form: { ...s.form, effectiveFrom: e.target.value } }))} />
            </div>
            <div>
              <label className={labelClass}>Effective to</label>
              <input type="date" className={inputClass} value={editing.form.effectiveTo}
                onChange={(e) => setEditing((s) => ({ ...s, form: { ...s.form, effectiveTo: e.target.value } }))} />
            </div>
          </div>
          <p className="mt-2 text-[11px] text-foreground-muted">Use the official BOFiP metropolitan grid. Pre-1 May bands end 2026-04-30; the new grid starts 2026-05-01.</p>
          {editing.error && <p className="mt-2 text-xs text-error">{editing.error}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setEditing(null)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={save} disabled={editing.saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {editing.saving ? "Saving…" : "Save band"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
