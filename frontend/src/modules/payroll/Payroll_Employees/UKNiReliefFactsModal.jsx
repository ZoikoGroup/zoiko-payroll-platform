import { useEffect, useState } from "react";
import Modal from "../../../components/Modal";
import { listUkNiReliefFacts, createUkNiReliefFact, deleteUkNiReliefFact } from "../../../service/payrollService";

// UK NI category relief-eligibility facts (ZP-TAX-UK-2026-27-001 §8.2/§9.3
// gap-closure Part 2) management UI. Found on a 2026-09-10 gap audit to
// have a complete backend CRUD API with no frontend anywhere — recording a
// Freeport/Investment Zone site assignment or veteran/apprentice status was
// only reachable via a raw API call. This is that missing screen. Once
// recorded, derive_ni_category() (enabled 2026-09-10 —
// _UK_DERIVE_NI_CATEGORY_ENABLED_COUNTRIES) will use these facts, plus the
// employee's own date of birth, to derive the correct NI category letter
// automatically instead of trusting whatever an admin manually typed —
// see uk.py's own precedence rules (site assignment beats age/veteran/
// apprentice; State Pension age further selects the site's own letter).
const RELIEF_TYPES = [
  { value: "FREEPORT", label: "Freeport site employee" },
  { value: "INVESTMENT_ZONE", label: "Investment Zone site employee" },
  { value: "VETERAN", label: "Qualifying veteran (first 12 months of civilian employment)" },
  { value: "APPRENTICE", label: "Apprentice under 25" },
];

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";
const selectClass = inputClass;

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

const emptyForm = { reliefType: "FREEPORT", reference: "", effectiveFrom: "", effectiveTo: "" };

export default function UKNiReliefFactsModal({ employee, onClose }) {
  const [facts, setFacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  async function refresh() {
    setLoading(true);
    setLoadError("");
    try {
      const data = await listUkNiReliefFacts(employee.id);
      setFacts(Array.isArray(data) ? data : []);
    } catch (err) {
      setLoadError(err.message || "Could not load relief-eligibility facts.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee.id]);

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleCreate() {
    setSubmitError("");
    if (!form.effectiveFrom) {
      setSubmitError("Effective from date is required.");
      return;
    }
    setSubmitting(true);
    try {
      await createUkNiReliefFact(employee.id, form);
      setForm(emptyForm);
      setShowForm(false);
      refresh();
    } catch (err) {
      setSubmitError(err.message || "Could not record this fact.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(factId) {
    setDeletingId(factId);
    try {
      await deleteUkNiReliefFact(employee.id, factId);
      refresh();
    } catch (err) {
      setLoadError(err.message || "Could not delete this fact.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Modal title={`NI Category Relief Facts — ${employee.name}`} onClose={onClose} maxWidth="max-w-xl">
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        These are eligibility facts, not a rate toggle — recording one here does not itself change this
        employee's NI category. It only gives the automatic-derivation feature real evidence to act on the
        next time payroll runs; the employee's manually-set NI category is used whenever no fact applies.
      </p>

      {loadError && (
        <div className="mb-4 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{loadError}</div>
      )}

      {loading ? (
        <p className="text-[13px] text-foreground-muted">Loading…</p>
      ) : facts.length === 0 ? (
        <p className="text-[13px] text-foreground-muted">No relief-eligibility facts recorded for this employee.</p>
      ) : (
        <div className="space-y-2.5 mb-4">
          {facts.map((f) => (
            <div key={f.id} className="flex items-center justify-between gap-3 rounded-[14px] border border-border bg-surface-muted p-4">
              <div>
                <p className="text-[13px] font-bold text-foreground">
                  {RELIEF_TYPES.find((t) => t.value === f.reliefType)?.label || f.reliefType}
                </p>
                <p className="mt-0.5 text-[12px] text-foreground-muted">
                  {f.reference ? `Ref ${f.reference} · ` : ""}
                  From {f.effectiveFrom}{f.effectiveTo ? ` to ${f.effectiveTo}` : " (ongoing)"}
                </p>
              </div>
              <button
                onClick={() => handleDelete(f.id)}
                disabled={deletingId === f.id}
                className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-error hover:border-error disabled:opacity-50"
              >
                {deletingId === f.id ? "Removing…" : "Remove"}
              </button>
            </div>
          ))}
        </div>
      )}

      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          className="w-full rounded-[12px] border border-dashed border-border px-4 py-2.5 text-[13px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary"
        >
          + Add relief-eligibility fact
        </button>
      ) : (
        <div className="rounded-[14px] border border-border p-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <Field label="Relief type">
                <select className={selectClass} value={form.reliefType} onChange={(e) => updateField("reliefType", e.target.value)}>
                  {RELIEF_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </Field>
            </div>
            <Field label="Reference (optional)" hint="Site name, discharge reference, apprenticeship ID, etc.">
              <input className={inputClass} value={form.reference} onChange={(e) => updateField("reference", e.target.value)} />
            </Field>
            <Field label="Effective from">
              <input type="date" className={inputClass} value={form.effectiveFrom} onChange={(e) => updateField("effectiveFrom", e.target.value)} />
            </Field>
            <Field label="Effective to (optional)" hint="Leave blank if still ongoing.">
              <input type="date" className={inputClass} value={form.effectiveTo} onChange={(e) => updateField("effectiveTo", e.target.value)} />
            </Field>
          </div>

          {submitError && (
            <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{submitError}</div>
          )}

          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => { setShowForm(false); setSubmitError(""); }} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">
              Cancel
            </button>
            <button
              onClick={handleCreate} disabled={submitting}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
            >
              {submitting ? "Saving…" : "Save fact"}
            </button>
          </div>
        </div>
      )}

      <div className="mt-5 flex justify-end">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Close</button>
      </div>
    </Modal>
  );
}
