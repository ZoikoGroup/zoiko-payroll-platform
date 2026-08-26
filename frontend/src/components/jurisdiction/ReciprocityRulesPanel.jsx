import { useState, useEffect, useCallback } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import Modal from "../Modal";
import ConfirmDialog from "../ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import { getReciprocityRules, upsertReciprocityRule, deleteReciprocityRule, getSourceArtifacts } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// Directional cross-state reciprocity agreements (e.g. PA resident working
// in NJ) — platform-wide, jurisdiction-pair data with no relationship to
// any single JurisdictionPack, so kept separate from the pack-scoped
// Contribution Rates/Tax Slabs tabs, same reasoning as SuiEmployerRatesPanel.
export default function ReciprocityRulesPanel() {
  const { addToast } = useToast() || {};
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const loadRules = useCallback(() => {
    setLoading(true);
    getReciprocityRules().then(setRules).finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadRules(); }, [loadRules]);

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Reciprocity & Sourcing</h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            Directional resident/work state agreements. A rule only suppresses work-state withholding for an
            employee whose certificate is on file and unexpired — see ZP-TAX-US-2026-001 §8.
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover">
          <Plus size={14} /> Add Agreement
        </button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : rules.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No reciprocity agreements configured yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="pb-2 pr-3">Resident</th>
                <th className="pb-2 pr-3">Work</th>
                <th className="pb-2 pr-3">Type</th>
                <th className="pb-2 pr-3">Certificate</th>
                <th className="pb-2 pr-3">Required</th>
                <th className="pb-2 pr-3">Effective</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className="border-b border-border-light last:border-0">
                  <td className="py-2 pr-3 font-medium text-foreground">{r.residentJurisdiction}</td>
                  <td className="py-2 pr-3 font-medium text-foreground">{r.workJurisdiction}</td>
                  <td className="py-2 pr-3">{r.agreementType}</td>
                  <td className="py-2 pr-3 font-mono">{r.employeeCertificate || "—"}</td>
                  <td className="py-2 pr-3">{r.certificateRequired ? "Yes" : "No"}</td>
                  <td className="py-2 pr-3 text-foreground-muted">{r.effectiveFrom} → {r.effectiveTo || "open"}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setEditing(r)} className="rounded-md p-1.5 text-foreground-muted hover:bg-surface-muted"><Pencil size={13} /></button>
                      <button onClick={() => setDeleting(r)} className="rounded-md p-1.5 text-error hover:bg-error-light"><Trash2 size={13} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(showForm || editing) && (
        <ReciprocityRuleFormModal
          rule={editing}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); loadRules(); }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete Reciprocity Agreement"
          message={`Delete the ${deleting.residentJurisdiction} → ${deleting.workJurisdiction} agreement? This cannot be undone.`}
          onConfirm={async () => {
            try {
              await deleteReciprocityRule(deleting.id);
              addToast?.("Deleted.", "success");
            } catch (err) {
              addToast?.(err.message || "Failed to delete.", "error");
            }
            setDeleting(null);
            loadRules();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

function ReciprocityRuleFormModal({ rule, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [sources, setSources] = useState([]);
  const [form, setForm] = useState({
    residentJurisdiction: rule?.residentJurisdiction || "US-",
    workJurisdiction: rule?.workJurisdiction || "US-",
    agreementType: rule?.agreementType || "RECIPROCAL_WAGE_WITHHOLDING",
    employeeCertificate: rule?.employeeCertificate || "",
    certificateRequired: rule?.certificateRequired ?? true,
    resultWhenValid: rule?.resultWhenValid || "",
    effectiveFrom: rule?.effectiveFrom || "",
    effectiveTo: rule?.effectiveTo || "",
    sourceDocumentId: rule?.sourceDocumentId || "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  useEffect(() => {
    getSourceArtifacts().then(setSources).catch(() => setSources([]));
  }, []);

  async function save() {
    if (!form.residentJurisdiction.trim() || !form.workJurisdiction.trim() || !form.effectiveFrom) {
      addToast?.("Resident jurisdiction, work jurisdiction, and effective-from date are required.", "error");
      return;
    }
    if (form.residentJurisdiction === form.workJurisdiction) {
      addToast?.("Resident and work jurisdictions must differ — reciprocity is a cross-state question.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertReciprocityRule({
        id: rule?.id,
        residentJurisdiction: form.residentJurisdiction, workJurisdiction: form.workJurisdiction,
        agreementType: form.agreementType, employeeCertificate: form.employeeCertificate || null,
        certificateRequired: Boolean(form.certificateRequired), resultWhenValid: form.resultWhenValid || null,
        effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || null,
        sourceDocumentId: form.sourceDocumentId ? Number(form.sourceDocumentId) : null,
      });
      addToast?.("Reciprocity agreement saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={rule ? "Edit Reciprocity Agreement" : "Add Reciprocity Agreement"} onClose={onClose} maxWidth="max-w-lg">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Resident Jurisdiction</label><input className={inputClass} value={form.residentJurisdiction} onChange={set("residentJurisdiction")} placeholder="US-PA" /></div>
        <div><label className={labelClass}>Work Jurisdiction</label><input className={inputClass} value={form.workJurisdiction} onChange={set("workJurisdiction")} placeholder="US-NJ" /></div>
        <div className="col-span-2"><label className={labelClass}>Agreement Type</label><input className={inputClass} value={form.agreementType} onChange={set("agreementType")} /></div>
        <div><label className={labelClass}>Employee Certificate Form</label><input className={inputClass} value={form.employeeCertificate} onChange={set("employeeCertificate")} placeholder="NJ-165" /></div>
        <div className="flex items-end pb-2">
          <label className="flex items-center gap-2 text-xs text-foreground-secondary">
            <input type="checkbox" checked={form.certificateRequired} onChange={(e) => setForm((f) => ({ ...f, certificateRequired: e.target.checked }))} />
            Certificate required
          </label>
        </div>
        <div className="col-span-2"><label className={labelClass}>Result When Valid (optional note)</label><input className={inputClass} value={form.resultWhenValid} onChange={set("resultWhenValid")} placeholder="Suppress work-state wage PIT; tax resident state instead" /></div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To (optional)</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div className="col-span-2">
          <label className={labelClass}>Source Evidence (optional — the official agreement/form instructions this was taken from)</label>
          <select className={inputClass} value={form.sourceDocumentId} onChange={set("sourceDocumentId")}>
            <option value="">No source linked</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
          </select>
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
