import { useState } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertCompliancePolicy } from "../../service/superAdminService";
import { inputClass, labelClass, STATUS_OPTIONS, POLICY_STATUS_OPTIONS, nextPackVersion } from "./constants";
import { taxYearDateProblem } from "./taxYear";

// "New Version" passes `basePack` (the pack being versioned): the form starts
// on the next free version number with that pack's metadata, instead of
// version "1.0" with blank fields - which, with the same Pack ID, used to
// overwrite the existing 1.0 row in place.
export default function NewPackModal({ country, state, packType, stateOptions = [], onClose, onCreated, defaultPackId, basePack = null, existingVersions = [] }) {
  const { addToast } = useToast() || {};
  const b = basePack || {};
  const [form, setForm] = useState({
    packId: defaultPackId || "", jurisdictionState: b.jurisdictionState || state || "",
    version: basePack ? nextPackVersion(b.version, existingVersions) : "1.0", status: "Draft",
    effectiveFrom: "", effectiveTo: "", taxYear: "", taxRegime: b.taxRegime || "", currency: b.currency || "",
    regulatoryAuthority: b.regulatoryAuthority || "", complianceCategory: b.complianceCategory || "",
    complianceOwner: b.complianceOwner || "", engineeringOwner: b.engineeringOwner || "", changeSummary: "",
    nextReviewDate: "", sourceReferences: b.sourceReferences || "",
  });
  const [saving, setSaving] = useState(false);
  const [versionEdited, setVersionEdited] = useState(false);
  const set = (field) => (e) => {
    if (field === "version") setVersionEdited(true);
    setForm((f) => ({ ...f, [field]: e.target.value }));
  };

  // The version list loads in the background; if New Version was opened
  // before it arrived, a suggestion fixed at open time ignored versions that
  // already exist (UK 2026-11-17: offered 1.1 while 1.1 existed). Until the
  // user types their own, the suggestion is worked out on every render from
  // the current list.
  const version = basePack && !versionEdited
    ? (nextPackVersion(b.version, existingVersions) || form.version)
    : form.version;

  // Same rule the server applies on create (tax_year_rules): a pack within one
  // calendar year uses that single year; open-ended packs must include the start year.
  const taxYearProblem = taxYearDateProblem(form.taxYear, form.effectiveFrom, form.effectiveTo);

  async function save() {
    if (taxYearProblem) {
      addToast?.(taxYearProblem, "error");
      return;
    }
    if (!form.packId.trim() || !form.effectiveFrom || !version.trim()) {
      addToast?.("Pack ID, Version and Effective From are required.", "error");
      return;
    }
    if (existingVersions.includes(version.trim())) {
      addToast?.(`Version ${version.trim()} already exists - open it and use Edit, or choose another version.`, "error");
      return;
    }
    setSaving(true);
    try {
      const created = await upsertCompliancePolicy({
        packId: form.packId, jurisdictionCountry: country, jurisdictionState: form.jurisdictionState || null,
        packType, version: version.trim(), status: form.status,
        effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || null,
        taxYear: form.taxYear || null, taxRegime: form.taxRegime || null, currency: form.currency || null,
        regulatoryAuthority: form.regulatoryAuthority || null, complianceCategory: form.complianceCategory || null,
        complianceOwner: form.complianceOwner || null, engineeringOwner: form.engineeringOwner || null,
        nextReviewDate: form.nextReviewDate || null, sourceReferences: form.sourceReferences || null,
        changeSummary: form.changeSummary || null,
      });
      addToast?.("Pack created.", "success");
      onCreated(created);
    } catch (err) {
      addToast?.(err.message || "Failed to create pack.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`New ${packType === "tax" ? "Tax" : "Policy"} Pack`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="col-span-2"><label className={labelClass}>Pack ID</label><input className={inputClass} value={form.packId} onChange={set("packId")} placeholder="e.g. IN-PAYROLL-2026-V1" /></div>
        <div>
          <label className={labelClass}>State (optional)</label>
          {stateOptions.length > 0 ? (
            // A fixed state list (e.g. Canada's 13 provinces/territories)
            // prevents a typo (e.g. "Ontario" instead of "ON") from
            // silently creating a pack the engine's exact-match state
            // resolver will never actually select for any employee.
            <select className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")}>
              <option value="">— Country-level (no state) —</option>
              {stateOptions.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (
            <input className={inputClass} value={form.jurisdictionState} onChange={set("jurisdictionState")} placeholder="e.g. Maharashtra" />
          )}
        </div>
        <div><label className={labelClass}>Version</label><input className={inputClass} value={version} onChange={set("version")} /></div>
        <div><label className={labelClass}>Status</label><select className={inputClass} value={form.status} onChange={set("status")}>{(packType === "policy" ? POLICY_STATUS_OPTIONS : STATUS_OPTIONS).map((s) => <option key={s} value={s}>{s}</option>)}</select></div>
        <div>
          <label className={labelClass} htmlFor="pack-tax-year">Tax Year</label>
          <input id="pack-tax-year" className={inputClass} value={form.taxYear} onChange={set("taxYear")} placeholder="2026 or 2026-27"
            aria-invalid={taxYearProblem ? true : undefined} aria-describedby={taxYearProblem ? "pack-tax-year-problem" : undefined} />
          {taxYearProblem && <p id="pack-tax-year-problem" role="alert" data-testid="tax-year-problem" className="mt-1 text-[11px] text-error">{taxYearProblem}</p>}
        </div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div><label className={labelClass}>Tax Regime</label><input className={inputClass} value={form.taxRegime} onChange={set("taxRegime")} placeholder="Old / New" /></div>
        <div><label className={labelClass}>Currency</label><input className={inputClass} value={form.currency} onChange={set("currency")} placeholder="INR" /></div>
        <div><label className={labelClass}>Compliance Category</label><input className={inputClass} value={form.complianceCategory} onChange={set("complianceCategory")} /></div>
        <div className="col-span-3"><label className={labelClass}>Regulatory Authority</label><input className={inputClass} value={form.regulatoryAuthority} onChange={set("regulatoryAuthority")} /></div>
        <div><label className={labelClass}>Compliance Owner</label><input className={inputClass} value={form.complianceOwner} onChange={set("complianceOwner")} /></div>
        <div><label className={labelClass}>Engineering Owner</label><input className={inputClass} value={form.engineeringOwner} onChange={set("engineeringOwner")} /></div>
        <div><label className={labelClass}>Next Review Date</label><input type="date" className={inputClass} value={form.nextReviewDate} onChange={set("nextReviewDate")} /></div>
        <div className="col-span-3"><label className={labelClass}>Source References</label><input className={inputClass} value={form.sourceReferences} onChange={set("sourceReferences")} placeholder="e.g. ZP-TAX-UK-2026-27-001 v1.0" /></div>
        <div className="col-span-3"><label className={labelClass}>Change Summary</label><textarea className={inputClass} rows={2} value={form.changeSummary} onChange={set("changeSummary")} /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving || Boolean(taxYearProblem)} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Creating…" : "Create"}</button>
      </div>
    </Modal>
  );
}
