import { useState } from "react";
import Modal from "../../Modal";
import { updateBeRow } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { governanceError, governancePayload, useSources } from "../new_zealand/nzForm";
import { ErrorNote, GovernanceFields } from "../new_zealand/nzShared";
import { cleanLabel } from "./beShared";

// Governed edit / sign of one canonical Belgium row (be_super_admin.update_row).
// The value slot, choices and NOT_SUPPORTED option come from the configuration
// API (row.valueKind + config.vocabulary[key]); the backend validates again.
// Sending only the governance fields signs the row as it stands.

const NUMERIC_LABELS = { employeeRatePct: "Employee %", employerRatePct: "Employer %", flatAmount: "Value",
  minAmount: "From", maxAmount: "To (empty = open)", ratePct: "Rate %" };

function initialValues(kind, row) {
  if (kind === "slab") {
    if (row.treatment !== undefined && row.obligation) return { treatment: row.treatment || "" };
    return { minAmount: row.minAmount ?? "", maxAmount: row.maxAmount ?? "", ratePct: row.ratePct ?? "",
      flatAmount: row.flatAmount ?? "" };
  }
  if (row.valueKind === "rate") {
    return { employeeRatePct: row.employeeRatePct ?? "", employerRatePct: row.employerRatePct ?? "",
      textValue: row.textValue ?? "" };
  }
  if (row.valueKind === "amount") return { flatAmount: row.flatAmount ?? "", textValue: row.textValue ?? "" };
  return { textValue: row.textValue ?? "" };
}

function changed(values, initial) {
  return Object.fromEntries(Object.entries(values).filter(([k, v]) => String(v ?? "") !== String(initial[k] ?? "")));
}

function TextValueField({ vocab, value, onChange }) {
  const notSupported = vocab?.notSupported;
  const mode = vocab?.mode || "choice";
  if (mode === "list") {
    const chosen = new Set(String(value || "").split(",").map((v) => v.trim()).filter(Boolean));
    const toggle = (choice) => {
      const next = new Set(chosen);
      next.delete(notSupported);
      if (next.has(choice)) next.delete(choice); else next.add(choice);
      onChange([...next].join(","));
    };
    return (
      <div className="space-y-1">
        {vocab.choices.map((choice) => (
          <label key={choice} className="flex items-center gap-2 text-[12px]">
            <input type="checkbox" checked={chosen.has(choice)} onChange={() => toggle(choice)} /> {choice}
          </label>
        ))}
        <label className="flex items-center gap-2 text-[12px] text-foreground-muted">
          <input type="checkbox" checked={value === notSupported} onChange={() => onChange(value === notSupported ? "" : notSupported)} />
          {notSupported} (feature stays blocked)
        </label>
      </div>
    );
  }
  if (mode === "codes" || mode === "date") {
    return (
      <div className="space-y-1">
        <input className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}
          placeholder={mode === "codes" ? "Comma-separated codes" : "YYYY-MM-DD"} />
        <p className="text-[11px] text-foreground-muted">Or sign {notSupported} (feature stays blocked).</p>
      </div>
    );
  }
  return (
    <select className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Not configured</option>
      {(vocab?.choices || []).map((choice) => <option key={choice} value={choice}>{choice}</option>)}
      {notSupported && <option value={notSupported}>{notSupported} (feature stays blocked)</option>}
    </select>
  );
}

export default function BERowEditor({ kind, row, config, onClose, onSaved }) {
  const sources = useSources();
  const [initial] = useState(() => initialValues(kind, row));
  const [values, setValues] = useState(initial);
  const [governance, setGovernance] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const vocab = kind === "rate" ? config?.vocabulary?.[row.componentKey] : null;
  const treatments = config?.earningClass?.treatments || [];
  const set = (name) => (e) => setValues({ ...values, [name]: e.target.value });

  async function save() {
    const problem = governanceError(governance);
    if (problem) { setError(problem); return; }
    const edits = changed(values, initial);
    // F-G12-1 (Block F1): a row is edited OR signed, never both; the editor never signs it.
    if (governance.specialistVerified && Object.keys(edits).length) {
      setError("Four-eyes: save the change first (it stays pending); another Super Admin who did not edit the row signs it.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await updateBeRow(kind, row.id, { ...edits, ...governancePayload(governance) }));
    } catch (err) {
      setError(err.message || "The change was refused.");
    } finally {
      setSaving(false);
    }
  }

  const numeric = Object.keys(values).filter((name) => name in NUMERIC_LABELS);
  const title = kind === "rate" ? row.componentKey : `${row.ruleType} ${row.obligation || ""} ${row.component || ""}`.trim();
  return (
    <Modal title={`Edit / sign — ${title}`} onClose={onClose} maxWidth="max-w-lg">
      <p className="mb-1 text-[12px] text-foreground-muted">{cleanLabel(row.label)}</p>
      {row.specReference && <p className="mb-3 text-[11px] text-foreground-muted">Spec reference: {row.specReference}</p>}
      {row.referenceOnly && (
        <p className="mb-3 rounded-lg border border-warning/40 bg-warning/10 p-2 text-[12px] text-warning" data-testid="be-reference-note">
          {row.referenceNote}
        </p>
      )}
      <div className="space-y-3" data-testid="be-row-editor">
        {"treatment" in values && (
          <div>
            <label className={labelClass}>Treatment ({row.obligation} · {row.component})</label>
            <select className={inputClass} value={values.treatment} onChange={set("treatment")}>
              {treatments.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}
        {numeric.length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            {numeric.map((name) => (
              <div key={name}>
                <label className={labelClass}>{NUMERIC_LABELS[name]}</label>
                <input className={inputClass} inputMode="decimal" value={values[name]} onChange={set(name)} />
              </div>
            ))}
          </div>
        )}
        {"textValue" in values && kind === "rate" && (
          <div>
            <label className={labelClass}>{numeric.length ? "Or a signed decision" : "Value"}</label>
            <TextValueField vocab={numeric.length ? { mode: "choice", choices: [], notSupported: vocab?.notSupported } : vocab}
              value={values.textValue} onChange={(v) => setValues({ ...values, textValue: v })} />
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
          {saving ? "Saving…" : governance.specialistVerified ? "Sign (no changes)" : "Save (stays pending)"}
        </button>
      </div>
    </Modal>
  );
}
