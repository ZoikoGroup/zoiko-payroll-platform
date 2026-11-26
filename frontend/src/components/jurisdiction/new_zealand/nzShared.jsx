import { inputClass, labelClass } from "../constants";
import { reviewed } from "./nzForm";

// The governance fields every statutory change carries (shared by NZ, PL, MY
// and BE): a change reason and, optionally, the source document it rests on.
// There is no signing step since the gate removal (owner decision 2026-11-25):
// a saved value is in force.

export function GovernanceFields({ value, onChange, sources }) {
  const set = (patch) => onChange({ ...value, ...patch });
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-muted p-3">
      <div>
        <label className={labelClass}>Source document (optional)</label>
        <select className={inputClass} value={value.sourceDocumentId || ""}
          onChange={(e) => set({ sourceDocumentId: e.target.value })}>
          <option value="">No source document</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.agency} — {s.title}{reviewed(s) ? " (reviewed)" : " (not reviewed)"}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelClass}>Change reason *</label>
        <textarea className={inputClass} rows={2} value={value.reason || ""}
          onChange={(e) => set({ reason: e.target.value })}
          placeholder="What changed and on what authority" />
      </div>
    </div>
  );
}

// Value state of a row. There is no signing step since the gate removal
// (owner decision 2026-11-25), so an old "[PENDING G1]" label marker means
// nothing: a row either has a value (in force) or does not (blocks only the
// calculation that needs it).
const VALUE_FIELDS = ["flatAmount", "textValue", "employeeRatePct", "employerRatePct", "ratePct", "minAmount",
  "maxAmount", "taxFormula", "treatment"];

export function SignedPill({ row }) {
  const hasValue = VALUE_FIELDS.some((key) => row?.[key] != null && row?.[key] !== "");
  if (!hasValue) {
    return (
      <span className="inline-flex rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px] font-semibold text-warning">
        No value
      </span>
    );
  }
  return <span className="inline-flex rounded border border-success/40 bg-success/10 px-1.5 py-0.5 text-[10px] font-semibold text-success">Set</span>;
}

export function ErrorNote({ message }) {
  if (!message) return null;
  return <p className="rounded-lg border border-error/30 bg-error/5 p-2 text-[12px] text-error" role="alert">{message}</p>;
}
