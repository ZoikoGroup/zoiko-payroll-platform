import { useState, useEffect, useCallback } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import Modal from "../Modal";
import ConfirmDialog from "../ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import {
  getLocalityRates, upsertLocalityRate, deleteLocalityRate, getSourceArtifacts,
} from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// Manually-entered county/municipal/school-district tax rates — no licensed
// geocoding provider is wired up (see ZP-TAX-US-2026-001 §C), so Tax Ops
// types in a real published rate against a known locality code, exactly
// the same pattern SuiEmployerRatesPanel already uses for SUI. Scoped by
// state (not by org — a locality's rate is the same for every employer in
// that state), so a state code picker stands in for SuiEmployerRatesPanel's
// organization picker.
export default function LocalityRatesPanel() {
  const { addToast } = useToast() || {};
  const [state, setState] = useState("");
  const [rates, setRates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const loadRates = useCallback(() => {
    if (!state.trim()) { setRates([]); return; }
    setLoading(true);
    getLocalityRates({ country: "US", state: state.trim().toUpperCase() })
      .then(setRates)
      .finally(() => setLoading(false));
  }, [state]);

  useEffect(() => { loadRates(); }, [loadRates]);

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-foreground">Locality Rates</h2>
        <p className="mt-0.5 text-xs text-foreground-muted">
          County/municipal/school-district tax rates, entered against the jurisdiction's actual published rate —
          never inferred from an address. An employee only sees this rate once their own Work Locality Code
          matches. See ZP-TAX-US-2026-001 §C.
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          className={inputClass + " w-auto min-w-[160px]"}
          value={state}
          onChange={(e) => setState(e.target.value.toUpperCase())}
          placeholder="State, e.g. PA"
          maxLength={2}
        />
        <button
          onClick={() => setShowForm(true)}
          disabled={!state.trim()}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Plus size={14} /> Add Locality Rate
        </button>
      </div>

      {!state.trim() ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Enter a state to view its configured locality rates.</p>
      ) : loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : rates.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No locality rates configured for this state yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="pb-2 pr-3">Code</th>
                <th className="pb-2 pr-3">Type</th>
                <th className="pb-2 pr-3">Name</th>
                <th className="pb-2 pr-3">Resident %</th>
                <th className="pb-2 pr-3">Nonresident %</th>
                <th className="pb-2 pr-3">Flat Amount</th>
                <th className="pb-2 pr-3">Tax Collector</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.id} className="border-b border-border-light last:border-0">
                  <td className="py-2 pr-3 font-mono font-medium text-foreground">{r.localityCode}</td>
                  <td className="py-2 pr-3">{r.localityType}</td>
                  <td className="py-2 pr-3">{r.localityName || "—"}</td>
                  <td className="py-2 pr-3">{r.residentRatePct != null ? `${r.residentRatePct}%` : "—"}</td>
                  <td className="py-2 pr-3">{r.nonresidentRatePct != null ? `${r.nonresidentRatePct}%` : "—"}</td>
                  <td className="py-2 pr-3">{r.flatAmount != null ? r.flatAmount : "—"}</td>
                  <td className="py-2 pr-3 font-mono text-foreground-disabled">{r.taxCollectorId || "—"}</td>
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
        <LocalityRateFormModal
          state={state.trim().toUpperCase()} rate={editing}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); loadRates(); }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete Locality Rate"
          message={`Delete the ${deleting.localityCode} locality rate? This cannot be undone.`}
          onConfirm={async () => {
            try {
              await deleteLocalityRate(deleting.id);
              addToast?.("Deleted.", "success");
            } catch (err) {
              addToast?.(err.message || "Failed to delete.", "error");
            }
            setDeleting(null);
            loadRates();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

function LocalityRateFormModal({ state, rate, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [sources, setSources] = useState([]);
  const [form, setForm] = useState({
    localityCode: rate?.localityCode || "",
    localityType: rate?.localityType || "MUNICIPAL",
    localityName: rate?.localityName || "",
    residentRatePct: rate?.residentRatePct ?? "",
    nonresidentRatePct: rate?.nonresidentRatePct ?? "",
    flatAmount: rate?.flatAmount ?? "",
    taxCollectorId: rate?.taxCollectorId || "",
    effectiveFrom: rate?.effectiveFrom || "",
    effectiveTo: rate?.effectiveTo || "",
    sourceDocumentId: rate?.sourceDocumentId || "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  useEffect(() => {
    getSourceArtifacts().then(setSources).catch(() => setSources([]));
  }, []);

  async function save() {
    if (!form.localityCode.trim()) {
      addToast?.("Locality code is required.", "error");
      return;
    }
    if (form.residentRatePct === "" && form.nonresidentRatePct === "" && form.flatAmount === "") {
      addToast?.("Enter at least one of resident %, nonresident %, or a flat amount.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertLocalityRate({
        id: rate?.id, jurisdictionCountry: "US", jurisdictionState: state,
        localityCode: form.localityCode.trim(), localityType: form.localityType,
        localityName: form.localityName || null,
        residentRatePct: form.residentRatePct === "" ? null : form.residentRatePct,
        nonresidentRatePct: form.nonresidentRatePct === "" ? null : form.nonresidentRatePct,
        flatAmount: form.flatAmount === "" ? null : form.flatAmount,
        taxCollectorId: form.taxCollectorId || null,
        effectiveFrom: form.effectiveFrom || null,
        effectiveTo: form.effectiveTo || null,
        sourceDocumentId: form.sourceDocumentId ? Number(form.sourceDocumentId) : null,
      });
      addToast?.("Locality rate saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={rate ? "Edit Locality Rate" : "Add Locality Rate"} onClose={onClose} maxWidth="max-w-lg">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Locality Code</label><input className={inputClass} value={form.localityCode} onChange={set("localityCode")} placeholder="e.g. PHILADELPHIA" /></div>
        <div><label className={labelClass}>Type</label>
          <select className={inputClass} value={form.localityType} onChange={set("localityType")}>
            <option value="COUNTY">County</option>
            <option value="MUNICIPAL">Municipal</option>
            <option value="SCHOOL_DISTRICT">School District</option>
            <option value="PSD_EIT_LST">PSD EIT/LST</option>
          </select>
        </div>
        <div className="col-span-2"><label className={labelClass}>Locality Name (optional)</label><input className={inputClass} value={form.localityName} onChange={set("localityName")} placeholder="City of Philadelphia" /></div>
        <div><label className={labelClass}>Resident Rate % (optional)</label><input className={inputClass} value={form.residentRatePct} onChange={set("residentRatePct")} placeholder="3.75" /></div>
        <div><label className={labelClass}>Nonresident Rate % (optional)</label><input className={inputClass} value={form.nonresidentRatePct} onChange={set("nonresidentRatePct")} placeholder="3.44" /></div>
        <div className="col-span-2"><label className={labelClass}>Flat Amount (optional, e.g. LST — applied per payslip, not annualized)</label><input className={inputClass} value={form.flatAmount} onChange={set("flatAmount")} placeholder="52.00" /></div>
        <div><label className={labelClass}>Effective From (optional)</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To (optional)</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div className="col-span-2"><label className={labelClass}>Tax Collector ID (optional)</label><input className={inputClass} value={form.taxCollectorId} onChange={set("taxCollectorId")} /></div>
        <div className="col-span-2">
          <label className={labelClass}>Source Evidence (optional — the official notice this rate was taken from)</label>
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
