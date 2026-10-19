import { useEffect, useState } from "react";
import { cancelMxCfdi, listMxCfdiCancelReasons } from "../../../../service/payrollService";

// Cancellation / substitution (MX-018). Reason codes come ONLY from the Active
// CFDI catalog; a reason that needs a related UUID asks for the stamped
// replacement's UUID. Disabled while the catalog is empty (S30 not transcribed).
export default function MXCancelReplaceDialog({ doc, onClose }) {
  const [reasons, setReasons] = useState(null);
  const [code, setCode] = useState("");
  const [replacement, setReplacement] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    listMxCfdiCancelReasons()
      .then((r) => active && setReasons(r || []))
      .catch((err) => active && setError(err?.message || "Cancellation reasons could not be loaded."));
    return () => { active = false; };
  }, []);

  const chosen = (reasons || []).find((r) => r.code === code);
  async function submit() {
    setError(null);
    try {
      await cancelMxCfdi(doc.id, code, chosen?.requiresRelatedUuid ? replacement : null);
      onClose();
    } catch (err) {
      setError(err?.message || "The cancellation was refused.");
    }
  }

  return (
    <div className="mt-3 rounded-[12px] border border-border p-3 text-[12px]" data-testid="mx-cfdi-cancel-dialog">
      <p className="mb-2 font-semibold">Cancel CFDI {doc.uuid}</p>
      {reasons && reasons.length === 0 && (
        <p className="mb-2 text-foreground-muted" data-testid="mx-cfdi-no-reasons">
          Cancellation reasons are not transcribed (S30 CFDI catalogs) — cancellation is unavailable.
        </p>
      )}
      <select aria-label="Cancellation reason" value={code} onChange={(e) => setCode(e.target.value)}
        disabled={!reasons || reasons.length === 0} className="mb-2 w-full rounded-[8px] border border-border bg-background px-2 py-1">
        <option value="">Choose a reason…</option>
        {(reasons || []).map((r) => <option key={r.code} value={r.code}>{r.code} — {r.description}</option>)}
      </select>
      {chosen?.requiresRelatedUuid && (
        <input aria-label="Replacement UUID" placeholder="UUID of the stamped replacement CFDI" value={replacement}
          onChange={(e) => setReplacement(e.target.value)}
          className="mb-2 w-full rounded-[8px] border border-border bg-background px-2 py-1 font-mono text-[11px]" />
      )}
      {error && <p className="mb-2 text-error" role="alert">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={!code || (chosen?.requiresRelatedUuid && !replacement.trim())} onClick={submit}
          className="rounded-[8px] border border-border px-2 py-1 font-semibold disabled:opacity-40">Request cancellation</button>
        <button type="button" onClick={onClose} className="rounded-[8px] px-2 py-1">Close</button>
      </div>
    </div>
  );
}
