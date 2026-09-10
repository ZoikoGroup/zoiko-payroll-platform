import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import Modal from "../../Modal";
import { getStateLocalReadiness, upsertStateLocalReadiness } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";

// India state/local statutory readiness registry (ZP-TAX-IN-2026-27-001
// §16, gap-closure Phase C, 2026-09-10) — one row per (state/UT, optional
// local authority, program), even when the status is NOT_APPLICABLE or
// SOURCE_REQUIRED, "so a tenant adding a work location never silently
// falls through a gap." Backend CRUD + seed data have existed since this
// same gap-closure pass; this is its first UI. Deliberately informational
// only — no onboarding/calculation path enforces this registry yet.

const STATUS_STYLES = {
  APPLICABLE: "bg-success/10 text-success",
  NOT_APPLICABLE: "bg-foreground-muted/10 text-foreground-muted",
  SOURCE_REQUIRED: "bg-warning/10 text-warning",
};

const PROGRAM_LABELS = {
  STATE_PT: "State Professional Tax",
  LOCAL_PT: "Local Professional Tax",
  LWF: "Labour Welfare Fund",
  OTHER_STATE_PAYROLL: "Other State Payroll",
};

function ReadinessFormModal({ onClose, onSaved, addToast }) {
  const [state, setState] = useState("");
  const [locality, setLocality] = useState("");
  const [program, setProgram] = useState("STATE_PT");
  const [legalStatus, setLegalStatus] = useState("SOURCE_REQUIRED");
  const [localAuthorityRequired, setLocalAuthorityRequired] = useState(false);
  const [registrationRequired, setRegistrationRequired] = useState(true);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!state.trim()) {
      addToast?.("State/UT is required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertStateLocalReadiness({
        jurisdictionCountry: "IN", jurisdictionState: state.trim(), jurisdictionLocality: locality.trim() || null,
        program, legalStatus, localAuthorityRequired, registrationRequired, notes: notes || null,
      });
      addToast?.("Readiness row saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save readiness row.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Add / Update Readiness Row" onClose={onClose} maxWidth="max-w-md">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelClass}>State / UT</label>
          <input className={inputClass} value={state} onChange={(e) => setState(e.target.value)} placeholder="Karnataka" />
        </div>
        <div>
          <label className={labelClass}>Local Authority <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional)</span></label>
          <input className={inputClass} value={locality} onChange={(e) => setLocality(e.target.value)} placeholder="e.g. Chennai" />
        </div>
        <div>
          <label className={labelClass}>Program</label>
          <select className={inputClass} value={program} onChange={(e) => setProgram(e.target.value)}>
            {Object.entries(PROGRAM_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Status</label>
          <select className={inputClass} value={legalStatus} onChange={(e) => setLegalStatus(e.target.value)}>
            <option value="SOURCE_REQUIRED">Source Required (activation blocked)</option>
            <option value="APPLICABLE">Applicable</option>
            <option value="NOT_APPLICABLE">Not Applicable</option>
          </select>
        </div>
        <div className="col-span-2 flex gap-4">
          <label className="flex items-center gap-1.5 text-[12px] text-foreground-secondary">
            <input type="checkbox" checked={localAuthorityRequired} onChange={(e) => setLocalAuthorityRequired(e.target.checked)} />
            Local authority required
          </label>
          <label className="flex items-center gap-1.5 text-[12px] text-foreground-secondary">
            <input type="checkbox" checked={registrationRequired} onChange={(e) => setRegistrationRequired(e.target.checked)} />
            Registration required
          </label>
        </div>
        <div className="col-span-2">
          <label className={labelClass}>Notes <span className="font-normal normal-case tracking-normal text-foreground-disabled">(optional)</span></label>
          <input className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Source citation / status reason" />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

export default function INStateLocalReadinessTab() {
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
      const data = await getStateLocalReadiness({ country: "IN" });
      setRows(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  return (
    <div className="space-y-3">
      {toast && (
        <div className={`rounded-lg px-3 py-2 text-xs font-semibold ${toast.type === "error" ? "bg-error/10 text-error" : "bg-success/10 text-success"}`}>
          {toast.message}
        </div>
      )}
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          One row per state/UT + optional local authority + statutory program — prevents a silent gap when a tenant adds a new work location.
        </p>
        <button onClick={() => setShowForm(true)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Row
        </button>
      </div>
      {loading ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No readiness rows yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">State / UT</th>
                <th className="px-3 py-2">Local Authority</th>
                <th className="px-3 py-2">Program</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="px-3 py-2 font-medium text-foreground">{r.jurisdictionState}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.jurisdictionLocality || "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{PROGRAM_LABELS[r.program] || r.program}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_STYLES[r.legalStatus] || ""}`}>{r.legalStatus}</span>
                  </td>
                  <td className="px-3 py-2 text-foreground-muted">{r.notes || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {showForm && (
        <ReadinessFormModal onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); refresh(); }} addToast={addToast} />
      )}
    </div>
  );
}
