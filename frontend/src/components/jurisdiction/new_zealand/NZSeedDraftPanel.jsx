import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { listNzPacks, seedNzDraftPack } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { ErrorNote } from "./nzShared";

// Shown only while NO New Zealand pack exists: creates the Draft
// NZ-PAYROLL-2026-27 pack from the specification (every row PENDING G1, the
// authority tables empty), the empty NZ-ELA-2028 staging pack and the PLANNED
// service-registry row. Nothing becomes Active here — every value is then
// signed in this console, approved by a Super Admin who made none of the
// edits, and activated. The backend refuses once any NZ pack exists.

export default function NZSeedDraftPanel() {
  const [packs, setPacks] = useState(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null, done: null });

  useEffect(() => {
    listNzPacks().then((rows) => setPacks(rows || [])).catch(() => setPacks([]));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null, done: null });
    try {
      const summary = await seedNzDraftPack(reason.trim());
      setState({ busy: false, error: null, done: summary });
    } catch (err) {
      setState({ busy: false, error: err.message || "Could not create the draft pack.", done: null });
    }
  };

  if (packs === null) return null;
  if (packs.length > 0 && !state.done) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-muted p-8 text-center">
        <AlertTriangle size={32} className="mx-auto text-foreground-disabled" />
        <p className="mt-3 text-sm text-foreground-muted">Select a New Zealand tax pack to see its configuration.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5" data-testid="nz-seed-draft">
      <h3 className="text-[14px] font-semibold text-foreground">No New Zealand pack yet</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        Create the Draft pack from the specification (ZP-NZ-ENG-001). Every value starts as PENDING G1 and the IRD
        authority tables start empty — nothing is active and no payroll can use it until each value is signed here,
        the pack is approved by a Super Admin who made none of the edits, and then activated.
      </p>
      <ErrorNote message={state.error} />
      {state.done ? (
        <div className="mt-3 text-[12px] text-success" role="status">
          <p>Draft pack created: {state.done.packs.map((p) => `${p.packId} (${p.status})`).join(", ")}.</p>
          <button type="button" onClick={() => window.location.reload()}
            className="mt-2 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
            Open the new pack
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-3 space-y-2" aria-label="Create the Draft New Zealand pack">
          <label className={labelClass} htmlFor="nz-seed-reason">Reason *</label>
          <input id="nz-seed-reason" className={inputClass} required value={reason}
            onChange={(e) => setReason(e.target.value)} placeholder="Why the New Zealand pack is being started" />
          <button type="submit" disabled={state.busy || !reason.trim()}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
            Create draft pack from the specification
          </button>
        </form>
      )}
    </div>
  );
}
