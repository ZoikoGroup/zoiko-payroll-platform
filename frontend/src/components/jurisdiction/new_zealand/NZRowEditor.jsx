import { useState } from "react";
import Modal from "../../Modal";
import { updateNzRow } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { REGIONS, TEXT_ROWS, TREATMENTS } from "./nzContent";
import { governanceError, governancePayload, useSources } from "./nzForm";
import { ErrorNote, GovernanceFields } from "./nzShared";

// Governed edit / sign of one canonical New Zealand row (a parameter, or a
// table row). Only the fields nz_super_admin.update_row accepts are offered;
// sending the governance fields alone signs the row as it stands.

function initialValues(kind, row) {
  if (kind === "rate") {
    return TEXT_ROWS[row.componentKey]
      ? { textValue: row.textValue && row.textValue !== "PENDING_G1" ? row.textValue : "" }
      : { flatAmount: row.flatAmount ?? "" };
  }
  if (row.ruleType === "NZ_EARNING_CLASS") return { treatment: row.assessmentBasis || "REVIEW" };
  if (row.ruleType === "NZ_PUBLIC_HOLIDAY") {
    return { name: String(row.rateLabel || "").replace("[PENDING G1]", "").trim(), region: row.jurisdictionState || "" };
  }
  return { minAmount: row.minAmount ?? "", maxAmount: row.maxAmount ?? "", ratePct: row.ratePct ?? "",
    flatAmount: row.flatAmount ?? "", taxFormula: row.taxFormula ?? "" };
}

// Only fields whose value changed are sent: an unchanged row is signed as-is.
function changed(values, initial) {
  return Object.fromEntries(Object.entries(values).filter(([k, v]) => String(v ?? "") !== String(initial[k] ?? "")));
}

export default function NZRowEditor({ kind, row, onClose, onSaved }) {
  const sources = useSources();
  const [initial] = useState(() => initialValues(kind, row));
  const [values, setValues] = useState(initial);
  const [governance, setGovernance] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const text = kind === "rate" ? TEXT_ROWS[row.componentKey] : null;
  const set = (name) => (e) => setValues({ ...values, [name]: e.target.value });

  async function save() {
    const problem = governanceError(governance);
    if (problem) { setError(problem); return; }
    setSaving(true);
    setError(null);
    try {
      const saved = await updateNzRow(kind, row.id, { ...changed(values, initial), ...governancePayload(governance) });
      onSaved(saved);
    } catch (err) {
      setError(err.message || "The change was refused.");
    } finally {
      setSaving(false);
    }
  }

  const title = kind === "rate" ? row.componentKey : `${row.ruleType} ${row.filingStatus || ""}`.trim();
  return (
    <Modal title={`Edit / sign — ${title}`} onClose={onClose} maxWidth="max-w-lg">
      <p className="mb-3 text-[12px] text-foreground-muted">{row.label || row.rateLabel}</p>
      <div className="space-y-3">
        {kind === "rate" && text?.choices && (
          <div>
            <label className={labelClass}>Value</label>
            <select className={inputClass} value={values.textValue} onChange={set("textValue")}>
              <option value="">Not configured</option>
              {text.choices.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        )}
        {kind === "rate" && text && !text.choices && (
          <div>
            <label className={labelClass}>Value</label>
            <input className={inputClass} value={values.textValue} onChange={set("textValue")} />
            <p className="mt-1 text-[11px] text-foreground-muted">{text.hint}</p>
          </div>
        )}
        {kind === "rate" && !text && (
          <div>
            <label className={labelClass}>Value</label>
            <input className={inputClass} inputMode="decimal" value={values.flatAmount} onChange={set("flatAmount")} />
          </div>
        )}
        {kind === "slab" && "treatment" in values && (
          <div>
            <label className={labelClass}>Treatment ({row.taxRegime} · {row.filingStatus})</label>
            <select className={inputClass} value={values.treatment} onChange={set("treatment")}>
              {TREATMENTS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}
        {kind === "slab" && "region" in values && (
          <>
            <div>
              <label className={labelClass}>Holiday</label>
              <input className={inputClass} value={values.name} onChange={set("name")} />
            </div>
            <div>
              <label className={labelClass}>Region (empty = national)</label>
              <select className={inputClass} value={values.region} onChange={set("region")}>
                <option value="">National</option>
                {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </>
        )}
        {kind === "slab" && "minAmount" in values && (
          <div className="grid grid-cols-2 gap-3">
            {[["minAmount", "From"], ["maxAmount", "To (empty = open)"], ["ratePct", "Rate %"], ["flatAmount", "Amount"]]
              .map(([name, label]) => (
                <div key={name}>
                  <label className={labelClass}>{label}</label>
                  <input className={inputClass} inputMode="decimal" value={values[name]} onChange={set(name)} />
                </div>
              ))}
          </div>
        )}
        <GovernanceFields value={governance} onChange={setGovernance} sources={sources} />
        <ErrorNote message={error} />
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose}
          className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-foreground-secondary hover:bg-surface-muted">
          Cancel
        </button>
        <button type="button" onClick={save} disabled={saving}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {saving ? "Saving…" : governance.specialistVerified ? "Save and sign" : "Save (stays pending)"}
        </button>
      </div>
    </Modal>
  );
}
