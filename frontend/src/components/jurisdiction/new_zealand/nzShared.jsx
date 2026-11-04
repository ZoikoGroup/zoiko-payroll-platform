import { inputClass, labelClass } from "../constants";
import { reviewed } from "./nzForm";

// The governance fields every New Zealand statutory change carries: an
// existing source document, a change reason and — to SIGN the row (remove
// "[PENDING G1]") — "specialist verified", which the backend accepts only for a
// stored, hashed source reviewed by a Super Admin other than its uploader.

export function GovernanceFields({ value, onChange, sources }) {
  const set = (patch) => onChange({ ...value, ...patch });
  const chosen = sources.find((s) => String(s.id) === String(value.sourceDocumentId));
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-muted p-3">
      <div>
        <label className={labelClass}>Source document *</label>
        <select className={inputClass} value={value.sourceDocumentId || ""}
          onChange={(e) => set({ sourceDocumentId: e.target.value, specialistVerified: false })}>
          <option value="">Select the official source…</option>
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
      <label className="flex items-start gap-2 text-[12px] text-foreground">
        <input type="checkbox" checked={Boolean(value.specialistVerified)} disabled={!reviewed(chosen)}
          onChange={(e) => set({ specialistVerified: e.target.checked })} />
        <span>
          Specialist verified — <strong>sign</strong> this row (removes PENDING G1).
          {!reviewed(chosen) && (
            <span className="block text-foreground-muted">
              Needs a stored, hashed source reviewed by a different Super Admin.
            </span>
          )}
        </span>
      </label>
    </div>
  );
}

export function SignedPill({ row }) {
  const label = String(row?.label || row?.rateLabel || "");
  if (label.includes("[PENDING G1]")) {
    return (
      <span className="inline-flex rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px] font-semibold text-warning">
        PENDING G1
      </span>
    );
  }
  return <span className="inline-flex rounded border border-success/40 bg-success/10 px-1.5 py-0.5 text-[10px] font-semibold text-success">Signed</span>;
}

export function ErrorNote({ message }) {
  if (!message) return null;
  return <p className="rounded-lg border border-error/30 bg-error/5 p-2 text-[12px] text-error" role="alert">{message}</p>;
}
