import { useMemo, useState } from "react";
import Modal from "../../Modal";
import { inputClass, labelClass } from "../constants";
import { PAS_RATE_TYPES } from "./franceStatutoryConfig";
import { ingestFrancePASRate } from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";

const WINDOW_DAYS = 60;

function addDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// Record a DGFiP PAS rate (FR-008/FR-010). A PERSONALIZED rate is authority
// data transcribed WITH its provenance — the DGFiP rate id, the CRM
// reference and the receipt date are all mandatory, and it must start
// within the legal window (no earlier than receipt, no later than 60 days
// after). The source is derived from the type. A replacement closes the
// previous rate (kept for its own period); a correction replaces a row
// recorded in error (it never resolves again).
export default function FrancePASRateFormModal({ organizationId, rates = [], employees = [], onClose, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [employeeId, setEmployeeId] = useState("");
  const [rateType, setRateType] = useState("PERSONALIZED");
  const [ratePct, setRatePct] = useState("");
  const [dgfipRateId, setDgfipRateId] = useState("");
  const [crmReference, setCrmReference] = useState("");
  const [receivedDate, setReceivedDate] = useState(today);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [correctionOfId, setCorrectionOfId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isNeutral = rateType === "NEUTRAL";
  const numericEmployeeId = employeeId === "" ? null : Number(employeeId);
  const priorRates = useMemo(
    () => rates.filter((r) => r.employeeId === numericEmployeeId && r.status !== "CORRECTED")
      .sort((a, b) => String(b.effectiveFrom).localeCompare(String(a.effectiveFrom))),
    [rates, numericEmployeeId],
  );
  const latestWindowEnd = !isNeutral && receivedDate ? addDays(receivedDate, WINDOW_DAYS) : null;

  async function save() {
    if (numericEmployeeId == null) return setError("Select the France employee.");
    if (!effectiveFrom) return setError("Effective from is required.");
    if (!isNeutral) {
      const pct = Number(ratePct);
      if (ratePct === "" || Number.isNaN(pct) || pct < 0 || pct > 100) return setError("Enter the DGFiP rate (0–100%).");
      if (!dgfipRateId.trim() || !crmReference.trim() || !receivedDate) {
        return setError("A DGFiP rate needs its rate id, CRM reference and receipt date (FR-008/FR-010).");
      }
      if (effectiveFrom < receivedDate) return setError("A rate cannot apply before the CRM delivering it was received.");
      if (effectiveFrom > latestWindowEnd) return setError(`Must be applied within ${WINDOW_DAYS} days of receipt (latest start ${latestWindowEnd}).`);
    }
    setError("");
    setSaving(true);
    try {
      await ingestFrancePASRate({
        employeeId: numericEmployeeId,
        rateType,
        ratePct: isNeutral ? null : Number(ratePct),
        dgfipRateId: isNeutral ? null : dgfipRateId.trim(),
        crmReference: isNeutral ? null : crmReference.trim(),
        receivedDate: isNeutral ? null : receivedDate,
        effectiveFrom,
        correctionOfId: correctionOfId === "" ? null : Number(correctionOfId),
      }, { organizationId });
      onSaved();
    } catch (err) {
      setError(loadErrorText(describeLoadError(err)));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Record a DGFiP PAS rate" onClose={onClose} maxWidth="max-w-2xl">
      <p className="mb-4 text-xs text-foreground-muted">
        Transcribe the rate DGFiP returned in the PAS CRM, with its provenance. Rates are authority data — this records what
        DGFiP sent, it never sets a rate of your own.
      </p>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="col-span-2">
          <label className={labelClass}>France employee *</label>
          <select className={inputClass} value={employeeId} onChange={(e) => { setEmployeeId(e.target.value); setCorrectionOfId(""); }}>
            <option value="">{employees.length ? "Select…" : "No employees in this organization"}</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employeeCode})</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Rate type</label>
          <select className={inputClass} value={rateType} onChange={(e) => setRateType(e.target.value)}>
            {Object.entries(PAS_RATE_TYPES).map(([key, meta]) => <option key={key} value={key}>{meta.label}</option>)}
          </select>
          <p className="mt-1 text-[11px] text-foreground-muted">{PAS_RATE_TYPES[rateType].hint}</p>
        </div>
        <div>
          <label className={labelClass}>Effective from *</label>
          <input type="date" className={inputClass} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
          {latestWindowEnd && <p className="mt-1 text-[11px] text-foreground-muted">Legal window: {receivedDate} → {latestWindowEnd}</p>}
        </div>
        {!isNeutral && (
          <>
            <div><label className={labelClass}>DGFiP rate % *</label>
              <input type="number" min="0" max="100" step="0.1" className={inputClass} value={ratePct} placeholder="e.g. 7.5" onChange={(e) => setRatePct(e.target.value)} /></div>
            <div><label className={labelClass}>CRM receipt date *</label>
              <input type="date" className={inputClass} value={receivedDate} onChange={(e) => setReceivedDate(e.target.value)} /></div>
            <div><label className={labelClass}>DGFiP rate id *</label>
              <input className={inputClass} value={dgfipRateId} placeholder="Identifier from the CRM" onChange={(e) => setDgfipRateId(e.target.value)} /></div>
            <div><label className={labelClass}>CRM reference *</label>
              <input className={inputClass} value={crmReference} placeholder="CRM message / file reference" onChange={(e) => setCrmReference(e.target.value)} /></div>
          </>
        )}
        {isNeutral && (
          <p className="col-span-2 rounded-lg bg-surface-muted px-3 py-2 text-[11px] text-foreground-muted">
            No percentage — the statutory neutral grid applies. Note: the neutral grid is not loaded yet, so payroll for a
            NEUTRAL employee blocks until it is (the official BOFiP grid is required).
          </p>
        )}
        {priorRates.length > 0 && (
          <div className="col-span-2 rounded-lg bg-surface-muted px-3 py-2">
            <label className={labelClass}>Correction of a row recorded in error (optional)</label>
            <select className={inputClass} value={correctionOfId} onChange={(e) => setCorrectionOfId(e.target.value)}>
              <option value="">— No: a normal replacement (the previous rate keeps its own period) —</option>
              {priorRates.map((r) => (
                <option key={r.id} value={r.id}>
                  #{r.id} · {r.effectiveFrom} → {r.effectiveTo || "open"} · {r.ratePct != null ? `${r.ratePct}%` : "neutral"} · {r.status}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-foreground-muted">A corrected row is marked CORRECTED and never used for any period again.</p>
          </div>
        )}
      </div>
      {error && <p className="mt-3 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} disabled={saving} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
          {saving ? "Recording…" : "Record rate"}
        </button>
      </div>
    </Modal>
  );
}
