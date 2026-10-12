import { useState, useEffect, useCallback } from "react";
import { Plus } from "lucide-react";
import StatusPill from "../StatusPill";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import {
  getFilingCalendarEntries, upsertFilingCalendarEntry, setFilingCalendarEntryStatus,
} from "../../service/superAdminService";
import { inputClass, labelClass } from "../jurisdiction/constants";
import { STATUS_PILL_MAP } from "./constants";

// Real, backend-owned due dates for this template's jurisdiction+report
// type+reporting year (e.g. India Form 138's Q1-Q4 dates) — never
// hardcoded in this component. A correction is a new version chained via
// previousVersionId, same lifecycle as the template itself.
export default function FilingCalendarTab({ template, editable }) {
  const { addToast } = useToast() || {};
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({ periodKey: "", periodLabel: "", dueDate: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    getFilingCalendarEntries({
      country: template.jurisdictionCountry, state: template.jurisdictionState || undefined,
      reportType: template.reportType, reportingYear: template.reportingYear,
    }).then(setEntries).finally(() => setLoading(false));
  }, [template.jurisdictionCountry, template.jurisdictionState, template.reportType, template.reportingYear]);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    if (!form.periodKey.trim() || !form.periodLabel.trim() || !form.dueDate) {
      addToast?.("Period Key, Period Label and Due Date are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertFilingCalendarEntry({
        jurisdictionCountry: template.jurisdictionCountry, jurisdictionState: template.jurisdictionState || null,
        reportType: template.reportType, reportingYear: template.reportingYear,
        periodKey: form.periodKey.trim(), periodLabel: form.periodLabel.trim(), dueDate: form.dueDate,
      });
      addToast?.("Filing calendar entry saved.", "success");
      setShowNew(false);
      setForm({ periodKey: "", periodLabel: "", dueDate: "" });
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to save entry.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleActivate(entry) {
    try {
      await setFilingCalendarEntryStatus(entry.id, "Active");
      addToast?.("Entry activated.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to activate — supersede the existing Active entry for this period first.", "error");
    }
  }

  return (
    <div className="space-y-3">
      {editable && (
        <div className="flex justify-end">
          <button
            onClick={() => setShowNew(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
          >
            <Plus size={13} /> Add Due Date
          </button>
        </div>
      )}
      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No filing due dates configured yet for this report/year.</p>
      ) : (
        <div className="space-y-1.5">
          {entries.map((entry) => (
            <div key={entry.id} className="flex items-center justify-between rounded-lg border border-border-light px-3 py-2 text-xs">
              <div>
                <span className="font-semibold text-foreground">{entry.periodKey}</span>
                <span className="ml-2 text-foreground-muted">{entry.periodLabel}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-foreground-secondary">Due {entry.dueDate}</span>
                <StatusPill status={STATUS_PILL_MAP[entry.status] || "pending"} label={entry.status} />
                {editable && entry.status === "Draft" && (
                  <button onClick={() => handleActivate(entry)} className="rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
                    Activate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showNew && (
        <Modal title="Add Filing Due Date" onClose={() => setShowNew(false)} maxWidth="max-w-md">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Period Key</label>
              <input className={inputClass} value={form.periodKey} onChange={(e) => setForm((f) => ({ ...f, periodKey: e.target.value }))} placeholder="Q1" />
            </div>
            <div>
              <label className={labelClass}>Due Date</label>
              <input type="date" className={inputClass} value={form.dueDate} onChange={(e) => setForm((f) => ({ ...f, dueDate: e.target.value }))} />
            </div>
            <div className="col-span-2">
              <label className={labelClass}>Period Label</label>
              <input className={inputClass} value={form.periodLabel} onChange={(e) => setForm((f) => ({ ...f, periodLabel: e.target.value }))} placeholder="April-June" />
            </div>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setShowNew(false)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={handleCreate} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
