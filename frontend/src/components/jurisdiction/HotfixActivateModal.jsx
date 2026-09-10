import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { hotfixActivatePack } from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// Super Admin UI Part 11 (§19, 2026-09-09) — Emergency Hotfix Mode.
// Bypasses ONLY the distinct-approver maker-checker gate for a genuine
// production emergency (e.g. a live statutory bug producing wrong
// payslips right now) — every other safety guard (date-range overlap,
// inverted dates) still applies server-side. In exchange, this requires
// a mandatory incident reference and justification, and ALWAYS creates
// a flagged retrospective-review record — the accountability normal
// maker-checker provides is deferred to a mandatory after-the-fact
// review, never silently skipped. Deliberately styled as a dangerous
// action, not a routine one.
export default function HotfixActivateModal({ pack, onClose, onActivated }) {
  const { addToast } = useToast() || {};
  const [incidentId, setIncidentId] = useState("");
  const [justification, setJustification] = useState("");
  const [saving, setSaving] = useState(false);

  async function activate() {
    if (!incidentId.trim() || !justification.trim()) {
      addToast?.("Both an incident ID and a justification are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await hotfixActivatePack(pack.id, { incident_id: incidentId.trim(), justification: justification.trim() });
      addToast?.(`${pack.packId} activated via emergency hotfix — flagged for mandatory review.`, "success");
      onActivated(updated);
    } catch (err) {
      addToast?.(err.message || "Failed to activate hotfix.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Emergency Hotfix Activate — ${pack.packId} v${pack.version}`} onClose={onClose} maxWidth="max-w-lg">
      <div className="mb-4 rounded-lg border border-error/30 bg-error/5 p-3 text-xs text-error">
        This bypasses the normal distinct-approver requirement and activates the pack immediately.
        Every activation is permanently recorded and flagged for mandatory retrospective review.
        Use only for a genuine production emergency.
      </div>
      <div className="space-y-3">
        <div>
          <label className={labelClass}>Incident ID *</label>
          <input className={inputClass} value={incidentId} onChange={(e) => setIncidentId(e.target.value)} placeholder="INC-2026-0912" />
        </div>
        <div>
          <label className={labelClass}>Justification *</label>
          <textarea
            className={inputClass} rows={4} value={justification} onChange={(e) => setJustification(e.target.value)}
            placeholder="What's broken in production, and why can't this wait for normal maker-checker approval?"
          />
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
          Cancel
        </button>
        <button
          onClick={activate} disabled={saving}
          className="rounded-lg bg-error px-3 py-2 text-xs font-semibold text-white hover:bg-error/90 disabled:opacity-60"
        >
          {saving ? "Activating…" : "Activate Now (Emergency)"}
        </button>
      </div>
    </Modal>
  );
}
