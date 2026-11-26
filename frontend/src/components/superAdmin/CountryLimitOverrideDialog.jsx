import { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

// Shown when a Super Admin plan change is refused because the organization
// has more active countries than the new limit allows (HTTP 409,
// trace.reason "downgrade_exceeds_country_limit"). The Super Admin can
// cancel, or override with a reason — the backend writes the override to the
// billing audit log, keeps every existing country running, blocks adding new
// ones and flags the organization for review.
export default function CountryLimitOverrideDialog({ error, onOverride, onClose }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const trace = error?.trace || {};

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await onOverride(reason.trim());
    } catch (err) {
      setFailure(err.message || "The override failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="country-limit-override-title">
      <form onSubmit={submit} className="w-full max-w-lg rounded-xl bg-surface p-6 shadow-lg" data-testid="country-limit-override">
        <h3 id="country-limit-override-title" className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <AlertTriangle size={18} className="text-warning" /> Downgrade refused: too many countries
        </h3>
        <p className="mt-2 text-sm text-foreground-secondary">{error?.message}</p>
        {trace.countries?.length > 0 && (
          <p className="mt-1 text-xs text-foreground-muted">Active countries: {trace.countries.join(", ")}</p>
        )}
        <p className="mt-3 text-sm text-foreground-secondary">
          Override only with a commercial reason. All {trace.used ?? "existing"} countries keep running, the
          organization cannot add another until it is under {trace.new_limit ?? "the"} limit, and it is flagged for
          review. The override and your reason go to the billing audit log.
        </p>
        <label className="mt-3 block text-xs font-semibold uppercase tracking-wide text-foreground-muted" htmlFor="override-reason">
          Override reason
        </label>
        <textarea
          id="override-reason"
          required
          rows={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground"
        />
        {failure && <p className="mt-2 text-sm text-error">{failure}</p>}
        <div className="mt-5 flex justify-end gap-3">
          <button type="button" onClick={onClose} disabled={busy}
            className="rounded-lg bg-surface-muted px-4 py-2 text-sm font-medium text-foreground-secondary hover:bg-border-light disabled:opacity-50">
            Cancel
          </button>
          <button type="submit" disabled={busy || !reason.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-warning px-4 py-2 text-sm font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50">
            {busy && <Loader2 size={14} className="animate-spin" />} Override and save
          </button>
        </div>
      </form>
    </div>
  );
}
