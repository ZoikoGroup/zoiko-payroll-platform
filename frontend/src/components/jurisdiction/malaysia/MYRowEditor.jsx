import { useCallback, useEffect, useState } from "react";
import Modal from "../../Modal";
import { getMyConfiguration, updateMyRow } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { governanceError, governancePayload, useSources } from "../new_zealand/nzForm";
import { ErrorNote, GovernanceFields } from "../new_zealand/nzShared";
import { NOT_SUPPORTED, PENDING, TREATMENTS, cleanLabel, textRow } from "./myContent";

// Governed edit / sign of one canonical Malaysia row (my_super_admin.update_row).
// Only the slot the row's kind holds is offered; sending the governance fields
// alone signs the row as it stands. Same governance as Poland / New Zealand.

// The console's own copy of the pack rows (national + territorial parameters,
// schedules, holidays, earning classes) with a reload after every change.
export function useMyConfiguration(pack) {
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    if (!pack?.id) return;
    getMyConfiguration(pack.id).then((c) => { setConfig(c); setError(null); })
      .catch((e) => setError(e.message || "Could not load the Malaysia pack."));
  }, [pack?.id]);
  useEffect(() => { load(); }, [load]);
  return [config, error, load];
}

function initialValues(kind, row) {
  if (kind === "slab") {
    if (row.ruleType === "MY_EARNING_CLASS") return { treatment: row.treatment || "REVIEW" };
    if (String(row.ruleType || "").endsWith("_SCHEDULE")) {
      return { minAmount: row.minAmount ?? "", maxAmount: row.maxAmount ?? "", flatAmount: row.flatAmount ?? "" };
    }
    return {};
  }
  if (row.valueKind === "text") return { textValue: row.textValue && row.textValue !== PENDING ? row.textValue : "" };
  if (row.valueKind === "pct_both") return { employeeRatePct: row.employeeRatePct ?? "", employerRatePct: row.employerRatePct ?? "" };
  if (row.valueKind === "pct_employee") return { employeeRatePct: row.employeeRatePct ?? "" };
  if (row.valueKind === "pct_employer") return { employerRatePct: row.employerRatePct ?? "" };
  return { flatAmount: row.flatAmount ?? "" };
}

function changed(values, initial) {
  return Object.fromEntries(Object.entries(values).filter(([k, v]) => String(v ?? "") !== String(initial[k] ?? "")));
}

const FIELD_LABELS = { employeeRatePct: "Employee %", employerRatePct: "Employer %", flatAmount: "Value",
  minAmount: "Wage above", maxAmount: "Wage up to (empty = open)" };

export default function MYRowEditor({ kind, row, onClose, onSaved }) {
  const sources = useSources();
  const [initial] = useState(() => initialValues(kind, row));
  const [values, setValues] = useState(initial);
  const [governance, setGovernance] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const text = kind === "rate" && row.valueKind === "text" ? (textRow(row.componentKey) || { choices: [NOT_SUPPORTED] }) : null;
  const set = (name) => (e) => setValues({ ...values, [name]: e.target.value });

  async function save() {
    const problem = governanceError(governance);
    if (problem) { setError(problem); return; }
    setSaving(true);
    setError(null);
    try {
      onSaved(await updateMyRow(kind, row.id, { ...changed(values, initial), ...governancePayload(governance) }));
    } catch (err) {
      setError(err.message || "The change was refused.");
    } finally {
      setSaving(false);
    }
  }

  const title = kind === "rate" ? row.componentKey : `${row.ruleType} ${row.obligation || ""} ${row.memberClass || ""}`.trim();
  const numeric = Object.keys(values).filter((name) => name in FIELD_LABELS);
  return (
    <Modal title={`Edit / sign — ${title}`} onClose={onClose} maxWidth="max-w-lg">
      <p className="mb-3 text-[12px] text-foreground-muted">{cleanLabel(row)}</p>
      <div className="space-y-3" data-testid="my-row-editor">
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
            <label className={labelClass}>Treatment ({row.obligation} · {row.component})</label>
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
