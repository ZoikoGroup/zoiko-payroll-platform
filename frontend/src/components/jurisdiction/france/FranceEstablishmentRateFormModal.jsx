import { useState } from "react";
import Modal from "../../Modal";
import { inputClass, labelClass } from "../constants";
import { FNAL_CLASS_REFERENCE, CFP_CLASS_REFERENCE } from "./franceStatutoryConfig";
import {
  upsertFranceEstablishmentRatePack, updateFranceEstablishmentRatePack,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";

const AGS_STATUSES = [
  { value: "", label: "Standard (0.25%)" },
  { value: "TEMPORARY_WORK", label: "Temporary-work agency (special AGS rate)" },
  { value: "EXEMPT", label: "Exempt / not affiliated" },
];

function initial(period) {
  return {
    atMpRatePct: period?.atMpRatePct ?? "", atMpRiskCode: period?.atMpRiskCode || "",
    atMpEvidence: period?.atMpEvidence || "", atMpSource: period?.atMpSource || "",
    vmRatePct: period?.vmRatePct ?? "", vmNotDue: period ? period.vmThresholdApplies === false : false,
    vmEvidence: period?.vmEvidence || "", vmSource: period?.vmSource || "",
    agsSpecialStatus: period?.agsSpecialStatus || "",
    fnalClass: period?.fnalClass || "UNDER_50", cfpClass: period?.cfpClass || "UNDER_11",
    effectif: period?.effectif ?? "",
  };
}

// Employer rates for one establishment (FR-002/FR-013, §11 panel E).
//   mode "append" — a new effective-dated period; the open one auto-closes
//                   the day before. Backdating is allowed (Urssaf AT/MP
//                   notices are often retroactive) with a warning.
//   mode "edit"   — a period that has NOT started yet; in-force periods are
//                   append-only (the backend enforces the same).
// AT/MP and versement mobilité are authority data: a rate needs its
// evidence or source. A missing VM rate blocks payroll unless the
// establishment is explicitly below the 11-employee threshold.
export default function FranceEstablishmentRateFormModal({
  organizationId, establishments = [], defaultEstablishmentId = null, period = null, onClose, onSaved,
}) {
  const mode = period ? "edit" : "append";
  const today = new Date().toISOString().slice(0, 10);
  const [establishmentId, setEstablishmentId] = useState(
    period?.establishmentId ?? defaultEstablishmentId ?? (establishments.length === 1 ? establishments[0].id : ""),
  );
  const [effectiveFrom, setEffectiveFrom] = useState(period?.effectiveFrom || "");
  const [form, setForm] = useState(() => initial(period));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const backdated = mode === "append" && effectiveFrom && effectiveFrom < today;
  const fnalRef = FNAL_CLASS_REFERENCE[form.fnalClass];
  const cfpRef = CFP_CLASS_REFERENCE[form.cfpClass];

  function pct(value, label) {
    if (value === "" || value === null) return null;
    const n = Number(value);
    if (Number.isNaN(n) || n < 0 || n > 100) throw new Error(`${label} rate must be between 0 and 100%.`);
    return n;
  }

  async function save() {
    try {
      if (mode === "append" && !establishmentId) throw new Error("Choose the establishment (register it under Establishments first).");
      if (mode === "append" && !effectiveFrom) throw new Error("Effective from is required.");
      const atMp = pct(form.atMpRatePct, "AT/MP");
      const vm = form.vmNotDue ? null : pct(form.vmRatePct, "Versement mobilité");
      if (atMp == null) throw new Error("An AT/MP rate is mandatory — enter the rate from the Urssaf decision.");
      if (!form.atMpEvidence.trim() && !form.atMpSource.trim()) throw new Error("AT/MP is Urssaf decision data — give its evidence reference or source.");
      if (!form.vmNotDue && vm == null) throw new Error("Enter the versement mobilité rate, or tick “not due” for an establishment under 11 employees.");
      if (vm != null && !form.vmEvidence.trim() && !form.vmSource.trim()) throw new Error("Versement mobilité is authority data — give its evidence reference or source.");
      if (form.effectif !== "" && (!Number.isInteger(Number(form.effectif)) || Number(form.effectif) < 0)) throw new Error("Effectif must be a whole number.");
    } catch (err) {
      setError(err.message);
      return;
    }
    const payload = {
      atMpRatePct: Number(form.atMpRatePct), atMpRiskCode: form.atMpRiskCode.trim() || null,
      atMpEvidence: form.atMpEvidence.trim() || null, atMpSource: form.atMpSource.trim() || null,
      vmRatePct: form.vmNotDue ? null : Number(form.vmRatePct),
      vmThresholdApplies: form.vmNotDue ? false : true,
      vmEvidence: form.vmNotDue ? null : form.vmEvidence.trim() || null,
      vmSource: form.vmNotDue ? null : form.vmSource.trim() || null,
      agsSpecialStatus: form.agsSpecialStatus || null,
      fnalClass: form.fnalClass, cfpClass: form.cfpClass,
      effectif: form.effectif === "" ? null : Number(form.effectif),
    };
    setError("");
    setSaving(true);
    try {
      if (mode === "edit") await updateFranceEstablishmentRatePack(period.id, payload, { organizationId });
      else await upsertFranceEstablishmentRatePack({ ...payload, establishmentId: Number(establishmentId), effectiveFrom }, { organizationId });
      onSaved();
    } catch (err) {
      setError(loadErrorText(describeLoadError(err)));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={mode === "edit" ? `Edit future period (${period.effectiveFrom})` : "Add employer-rate period"} onClose={onClose} maxWidth="max-w-2xl">
      <p className="mb-4 text-xs text-foreground-muted">
        {mode === "edit"
          ? "This period has not started yet, so it can still be corrected. Once in force it is append-only."
          : "A new effective-dated period for the establishment. Its current open period is closed the day before — history is never rewritten."}
      </p>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <label className={labelClass}>Establishment *</label>
          <select className={inputClass} value={establishmentId} disabled={mode === "edit"} onChange={(e) => setEstablishmentId(e.target.value)}>
            <option value="">{establishments.length ? "Select…" : "No active establishment"}</option>
            {establishments.map((e) => <option key={e.id} value={e.id}>{e.siret}{e.name ? ` — ${e.name}` : ""}</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Effective from *</label>
          <input type="date" className={inputClass} value={effectiveFrom} disabled={mode === "edit"} onChange={(e) => setEffectiveFrom(e.target.value)} />
          {backdated && <p className="mt-1 text-[11px] text-warning">Backdated — payrolls already run for this period are not recalculated automatically.</p>}
        </div>

        <p className="col-span-2 border-t border-border-light pt-3 font-semibold text-foreground-secondary">AT/MP — workplace accident &amp; disease (Urssaf decision)</p>
        <div><label className={labelClass}>AT/MP rate % *</label><input type="number" min="0" max="100" step="0.01" className={inputClass} value={form.atMpRatePct} placeholder="e.g. 2.09" onChange={set("atMpRatePct")} /></div>
        <div><label className={labelClass}>Risk code</label><input className={inputClass} value={form.atMpRiskCode} placeholder="e.g. 741GA" onChange={set("atMpRiskCode")} /></div>
        <div><label className={labelClass}>Evidence reference</label><input className={inputClass} value={form.atMpEvidence} placeholder="Urssaf decision ref" onChange={set("atMpEvidence")} /></div>
        <div><label className={labelClass}>Source</label><input className={inputClass} value={form.atMpSource} placeholder="e.g. net-entreprises notice" onChange={set("atMpSource")} /></div>

        <p className="col-span-2 border-t border-border-light pt-3 font-semibold text-foreground-secondary">Versement mobilité (commune / 11+ threshold)</p>
        <label className="col-span-2 inline-flex items-center gap-2 font-medium text-foreground-muted">
          <input type="checkbox" checked={form.vmNotDue} onChange={set("vmNotDue")} />
          Not due — establishment below the 11-employee threshold
        </label>
        {!form.vmNotDue && (
          <>
            <div><label className={labelClass}>VM rate % *</label><input type="number" min="0" max="100" step="0.01" className={inputClass} value={form.vmRatePct} placeholder="e.g. 2.95" onChange={set("vmRatePct")} /></div>
            <div />
            <div><label className={labelClass}>Evidence reference</label><input className={inputClass} value={form.vmEvidence} placeholder="AOM rate table ref" onChange={set("vmEvidence")} /></div>
            <div><label className={labelClass}>Source</label><input className={inputClass} value={form.vmSource} placeholder="e.g. Urssaf VM table" onChange={set("vmSource")} /></div>
          </>
        )}

        <p className="col-span-2 border-t border-border-light pt-3 font-semibold text-foreground-secondary">Employer-size classes &amp; special status</p>
        <div>
          <label className={labelClass}>FNAL class</label>
          <select className={inputClass} value={form.fnalClass} onChange={set("fnalClass")}>
            {Object.entries(FNAL_CLASS_REFERENCE).map(([key, ref]) => <option key={key} value={key}>{ref.label}</option>)}
          </select>
          <p className="mt-1 text-[11px] text-foreground-muted">{fnalRef.note}.</p>
        </div>
        <div>
          <label className={labelClass}>CFP class</label>
          <select className={inputClass} value={form.cfpClass} onChange={set("cfpClass")}>
            {Object.entries(CFP_CLASS_REFERENCE).map(([key, ref]) => <option key={key} value={key}>{ref.label}</option>)}
          </select>
          <p className="mt-1 text-[11px] text-foreground-muted">{cfpRef.note}.</p>
        </div>
        <div>
          <label className={labelClass}>Unemployment / AGS status</label>
          <select className={inputClass} value={form.agsSpecialStatus} onChange={set("agsSpecialStatus")}>
            {AGS_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
        <div><label className={labelClass}>Establishment effectif</label><input type="number" min="0" className={inputClass} value={form.effectif} placeholder="headcount" onChange={set("effectif")} /></div>
      </div>

      {error && <p className="mt-3 text-xs text-error">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} disabled={saving} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
          {saving ? "Saving…" : mode === "edit" ? "Save changes" : "Add period"}
        </button>
      </div>
    </Modal>
  );
}
