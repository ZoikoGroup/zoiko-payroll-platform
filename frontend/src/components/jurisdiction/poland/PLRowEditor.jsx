import { useState } from "react";
import Modal from "../../Modal";
import { updatePlRow } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { governanceError, governancePayload, useSources } from "../new_zealand/nzForm";
import { ErrorNote, GovernanceFields } from "../new_zealand/nzShared";
import { NOT_SUPPORTED, TEXT_ROWS, TREATMENTS, valueKind } from "./plContent";

// Governed edit / sign of one canonical Poland row (pl_super_admin.update_row).
// Only the slot the row's kind holds is offered; sending the governance fields
// alone signs the row as it stands. Same governance as New Zealand.

function initialValues(kind, row) {
  if (kind === "slab") {
    return row.ruleType === "PL_EARNING_CLASS"
      ? { treatment: row.assessmentBasis || "REVIEW" }
      : { minAmount: row.minAmount ?? "", maxAmount: row.maxAmount ?? "", ratePct: row.ratePct ?? "",
        flatAmount: row.flatAmount ?? "" };
  }
  const value = valueKind(row.componentKey);
  if (value === "text") return { textValue: row.textValue && row.textValue !== "PENDING_G1" ? row.textValue : "" };
  if (value === "pair") return { employeeRatePct: row.employeeRatePct ?? "", employerRatePct: row.employerRatePct ?? "" };
  if (value === "employee") return { employeeRatePct: row.employeeRatePct ?? "" };
  if (value === "employer") return { employerRatePct: row.employerRatePct ?? "" };
  return { flatAmount: row.flatAmount ?? "" };
}

function changed(values, initial) {
  return Object.fromEntries(Object.entries(values).filter(([k, v]) => String(v ?? "") !== String(initial[k] ?? "")));
}

const FIELD_LABELS = { employeeRatePct: "Employee %", employerRatePct: "Employer %", flatAmount: "Value",
  minAmount: "From", maxAmount: "To (empty = open)", ratePct: "Rate %" };

export default function PLRowEditor({ kind, row, onClose, onSaved }) {
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
      onSaved(await updatePlRow(kind, row.id, { ...changed(values, initial), ...governancePayload(governance) }));
    } catch (err) {
      setError(err.message || "The change was refused.");
    } finally {
      setSaving(false);
    }
  }

  const title = kind === "rate" ? row.componentKey : `${row.ruleType} ${row.taxRegime || ""} ${row.filingStatus || ""}`.trim();
  const numeric = Object.keys(values).filter((name) => name in FIELD_LABELS);
  return (
    <Modal title={`Edit / sign — ${title}`} onClose={onClose} maxWidth="max-w-lg">
      <p className="mb-3 text-[12px] text-foreground-muted">{String(row.label || row.rateLabel || "").replace("[PENDING G1]", "").trim()}</p>
      <div className="space-y-3" data-testid="pl-row-editor">
        {text?.choices && (
          <div>
            <label className={labelClass}>Value</label>
            <select className={inputClass} value={values.textValue} onChange={set("textValue")}>
              <option value="">Not configured</option>
              {text.choices.map((c) => <option key={c} value={c}>{c === NOT_SUPPORTED ? "NOT_SUPPORTED (feature stays blocked)" : c}</option>)}
            </select>
          </div>
        )}
        {text && !text.choices && (
          <div>
            <label className={labelClass}>Value</label>
            <input className={inputClass} value={values.textValue} onChange={set("textValue")} />
            <p className="mt-1 text-[11px] text-foreground-muted">{text.hint}{text.allowNotSupported ? ` — or ${NOT_SUPPORTED}` : ""}</p>
          </div>
        )}
        {"treatment" in values && (
          <div>
            <label className={labelClass}>Treatment ({row.taxRegime} · {row.filingStatus})</label>
            <select className={inputClass} value={values.treatment} onChange={set("treatment")}>
              {TREATMENTS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}
        {numeric.length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            {numeric.map((name) => (
              <div key={name}>
                <label className={labelClass}>{FIELD_LABELS[name]}</label>
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
