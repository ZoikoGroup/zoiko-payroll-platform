import { useState } from "react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { CPF_AGE_BANDS, CPF_COHORTS, CPF_RATE_BAND, CPF_WAGE_BANDS, SHG_FUNDS, SHG_FUND_BAND, wageBandBounds } from "./sgComponentConfig";

// Add/Edit form for Singapore's two band tables — the generic
// SlabFormModal has no cohort / age-band / formula-type / fund fields, and
// would overwrite taxRegime (the CPF age band) with the pack's regime.
// Writes through the SAME canonical upsertCanonicalTaxSlab endpoint every
// other country's slab form uses (server-side: editable-pack guard,
// approval invalidation, TaxConfigurationAudit).
//
// `kind`: "CPF" | "SHG". `initial` pre-fills an add (e.g. the matrix cell
// that was clicked); `slab` is the row being edited.
export default function SGBandFormModal({ pack, slabs = [], kind, slab, initial = {}, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const isCpf = kind === "CPF";
  const seed = { ...initial, ...(slab || {}) };
  // Prefill thresholds only from the pack's own rows of the same band kind;
  // otherwise the author enters them from the authority source.
  const bounds = isCpf ? wageBandBounds(slabs, seed.assessmentBasis || "FULL") : null;
  const [form, setForm] = useState({
    cohort: seed.filingStatus || (isCpf ? "SC_SPR3" : "CDAC"),
    ageBand: seed.taxRegime || "AGE_LE_55",
    basis: seed.assessmentBasis || "FULL",
    minAmount: seed.minAmount ?? (isCpf ? (bounds?.min ?? "") : "0"),
    maxAmount: seed.maxAmount ?? (isCpf ? (bounds?.max ?? "") : ""),
    ratePct: seed.ratePct ?? "",
    employerRatePct: seed.employerRatePct ?? "",
    flatAmount: seed.flatAmount ?? "",
    sortOrder: seed.sortOrder ?? 0,
    reason: "",
  });
  const [saving, setSaving] = useState(false);
  // Validation error shown inline (role="alert") and linked to the offending
  // field(s) via aria-invalid / aria-describedby — not only as a toast.
  const [fieldError, setFieldError] = useState(null);
  const set = (field) => (e) => {
    setForm((f) => ({ ...f, [field]: e.target.value }));
    setFieldError((err) => (err && err.fields.includes(field) ? null : err));
  };
  const errorProps = (field) =>
    fieldError?.fields.includes(field) ? { "aria-invalid": true, "aria-describedby": "sg-band-error" } : {};
  function fail(fields, message) {
    setFieldError({ fields, message });
    addToast?.(message, "error");
  }

  function setBasis(e) {
    const basis = e.target.value;
    const next = wageBandBounds(slabs, basis);
    setForm((f) => ({ ...f, basis, minAmount: next?.min ?? "", maxAmount: next?.max ?? "" }));
  }

  const needsEmployee = isCpf && (form.basis === "FULL" || form.basis === "PHASE_IN");
  const needsEmployer = isCpf && form.basis !== "NIL";

  async function save() {
    if (!form.reason.trim()) {
      fail(["reason"], "A reason (with its authority source) is required for every statutory change.");
      return;
    }
    if (isCpf && ((needsEmployee && form.ratePct === "") || (needsEmployer && form.employerRatePct === ""))) {
      fail([needsEmployee && form.ratePct === "" && "ratePct", needsEmployer && form.employerRatePct === "" && "employerRatePct"].filter(Boolean),
        "Enter the rate(s) exactly as published for this formula type.");
      return;
    }
    if (!isCpf && form.flatAmount === "") {
      fail(["flatAmount"], "Enter the monthly contribution for this band.");
      return;
    }
    setFieldError(null);
    const ruleId = isCpf
      ? `CPF-${pack.taxYear || ""}-${form.cohort}-${form.ageBand}-${form.basis}`
      : slab?.rateLabel || `SHG-${pack.taxYear || ""}-${form.cohort}-${form.minAmount}`;
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry,
        jurisdictionState: null,
        ruleType: isCpf ? CPF_RATE_BAND : SHG_FUND_BAND,
        filingStatus: form.cohort,
        taxRegime: isCpf ? form.ageBand : null,
        assessmentBasis: isCpf ? form.basis : null,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: needsEmployee ? form.ratePct : "0",
        employerRatePct: needsEmployer ? form.employerRatePct : null,
        flatAmount: isCpf ? null : form.flatAmount,
        rateLabel: ruleId, taxFormula: slab?.taxFormula || "",
        sortOrder: Number(form.sortOrder) || 0, reason: form.reason,
      });
      addToast?.("Statutory row saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save statutory row.", "error");
    } finally {
      setSaving(false);
    }
  }

  const title = `${slab ? "Edit" : "Add"} ${isCpf ? "CPF rate row" : "SHG contribution band"}`;
  return (
    <Modal title={title} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-4">
        {isCpf ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass} htmlFor="sg-band-cohort">Cohort</label>
              <select id="sg-band-cohort" className={inputClass} value={form.cohort} onChange={set("cohort")}>
                {CPF_COHORTS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass} htmlFor="sg-band-age">Age band</label>
              <select id="sg-band-age" className={inputClass} value={form.ageBand} onChange={set("ageBand")}>
                {CPF_AGE_BANDS.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass} htmlFor="sg-band-basis">Wage band / formula</label>
              <select id="sg-band-basis" className={inputClass} value={form.basis} onChange={setBasis}>
                {CPF_WAGE_BANDS.map((b) => <option key={b.basis} value={b.basis}>{b.label} ({b.basis})</option>)}
              </select>
            </div>
          </div>
        ) : (
          <div>
            <label className={labelClass} htmlFor="sg-band-fund">Fund</label>
            <select id="sg-band-fund" className={inputClass} value={form.cohort} onChange={set("cohort")}>
              {SHG_FUNDS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass} htmlFor="sg-band-min">Total wages above (S$)</label>
            <input id="sg-band-min" className={inputClass} inputMode="decimal" value={form.minAmount} onChange={set("minAmount")} />
          </div>
          <div>
            <label className={labelClass} htmlFor="sg-band-max">Up to and including (S$, blank = no upper limit)</label>
            <input id="sg-band-max" className={inputClass} inputMode="decimal" value={form.maxAmount} onChange={set("maxAmount")} />
          </div>
        </div>

        {isCpf ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {needsEmployee && (
              <div>
                <label className={labelClass} htmlFor="sg-band-ee">
                  {form.basis === "PHASE_IN" ? "Employee phase-in factor × 100 (e.g. 60 for 0.6)" : "Employee rate (%)"}
                </label>
                <input id="sg-band-ee" className={inputClass} inputMode="decimal" value={form.ratePct} onChange={set("ratePct")} {...errorProps("ratePct")} />
              </div>
            )}
            {needsEmployer && (
              <div>
                <label className={labelClass} htmlFor="sg-band-er">Employer rate (%)</label>
                <input id="sg-band-er" className={inputClass} inputMode="decimal" value={form.employerRatePct} onChange={set("employerRatePct")} {...errorProps("employerRatePct")} />
              </div>
            )}
            {form.basis === "NIL" && (
              <p className="text-xs text-foreground-muted sm:col-span-2">NIL rows carry no rates — CPF is not payable in this wage band.</p>
            )}
          </div>
        ) : (
          <div>
            <label className={labelClass} htmlFor="sg-band-flat">Monthly contribution (S$)</label>
            <input id="sg-band-flat" className={inputClass} inputMode="decimal" value={form.flatAmount} onChange={set("flatAmount")} {...errorProps("flatAmount")} />
          </div>
        )}

        <div>
          <label className={labelClass} htmlFor="sg-band-reason">Reason and authority source (recorded in the audit trail)</label>
          <textarea id="sg-band-reason" rows={2} className={inputClass} value={form.reason} onChange={set("reason")}
            {...errorProps("reason")} placeholder="e.g. CPF Board 2026 contribution rate table, row …" />
        </div>

        {fieldError && (
          <p id="sg-band-error" role="alert" className="text-sm font-medium text-error">{fieldError.message}</p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-foreground-secondary hover:bg-surface-muted">Cancel</button>
          <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
