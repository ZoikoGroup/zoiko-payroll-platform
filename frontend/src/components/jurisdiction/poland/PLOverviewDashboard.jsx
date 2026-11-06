import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { getPlDecisions, getPlSigningStatus, listPlPacks, seedPlDraftPack } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// Poland pack overview (ZP-PL-ENG-001 §12 statutory content console): what
// still blocks activation, straight from the backend signing status, and the
// owner decisions D-1..D-7. With no Poland pack yet, offers the governed
// "create the Draft pack from the specification" action (backend refuses once
// any Poland pack exists). Nothing becomes Active here.

export function SeedDraftPanel() {
  const [packs, setPacks] = useState(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null, done: false });

  useEffect(() => {
    listPlPacks().then((rows) => setPacks(rows || [])).catch(() => setPacks([]));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null, done: false });
    try {
      await seedPlDraftPack(reason.trim());
      setState({ busy: false, error: null, done: true });
    } catch (err) {
      setState({ busy: false, error: err.message || "Could not create the draft pack.", done: false });
    }
  };

  if (packs === null) return null;
  if (packs.length > 0 && !state.done) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-muted p-8 text-center">
        <AlertTriangle size={32} className="mx-auto text-foreground-disabled" />
        <p className="mt-3 text-sm text-foreground-muted">Select a Poland tax pack to see its configuration.</p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-border bg-surface p-5" data-testid="pl-seed-draft">
      <h3 className="text-[14px] font-semibold text-foreground">No Poland pack yet</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        Create the Draft PL-PAYROLL-2026 pack from the specification (ZP-PL-ENG-001). Values the specification does not
        give start empty or PENDING G1 — no payroll can use the pack until each is signed here, the pack is approved by a
        Super Admin who made none of the edits, and then activated.
      </p>
      <ErrorNote message={state.error} />
      {state.done ? (
        <div className="mt-3 text-[12px] text-success" role="status">
          <p>Draft pack created.</p>
          <button type="button" onClick={() => window.location.reload()}
            className="mt-2 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
            Open the new pack
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-3 space-y-2" aria-label="Create the Draft Poland pack">
          <label className={labelClass} htmlFor="pl-seed-reason">Reason *</label>
          <input id="pl-seed-reason" className={inputClass} required value={reason}
            onChange={(e) => setReason(e.target.value)} placeholder="Why the Poland pack is being started" />
          <button type="submit" disabled={state.busy || !reason.trim()}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
            Create draft pack from the specification
          </button>
        </form>
      )}
    </div>
  );
}

export default function PLOverviewDashboard({ pack, onReload }) {
  const [status, setStatus] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    if (!pack) return;
    getPlSigningStatus(pack.id)
      .then((data) => { setStatus(data); setError(null); })
      .catch((e) => setError(e.message || "Could not load the signing status."));
    getPlDecisions().then((rows) => setDecisions(rows || [])).catch(() => setDecisions([]));
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  if (!pack) return <SeedDraftPanel />;
  const ready = status && !status.activationRefusal;

  return (
    <div className="space-y-6" data-testid="pl-overview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Poland statutory configuration</h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Pack <span className="font-mono text-foreground">{pack.packId} v{pack.version}</span> · {pack.status} ·{" "}
            {pack.effectiveFrom || "—"} to {pack.effectiveTo || "open"}
          </p>
        </div>
        <button type="button" onClick={() => { load(); onReload?.(); }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <ErrorNote message={error} />
      {status && (
        <div className={`rounded-xl border p-3 text-[12px] ${ready ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10"}`}
          data-testid="pl-activation-state">
          {ready ? (
            <span className="inline-flex items-center gap-1.5 text-success">
              <CheckCircle2 size={14} /> Every row is signed and configured. A Super Admin who made none of the edits may
              approve, then activate.
            </span>
          ) : (
            <span className="text-foreground-secondary"><strong>Activation is refused:</strong> {status.activationRefusal}</span>
          )}
        </div>
      )}
      {status && (
        <div className="grid gap-3 sm:grid-cols-4">
          {[["Pending parameters", status.pendingRates.length], ["Empty values", status.emptyValues.length],
            ["Undecided policies", status.pendingPolicies.length], ["Not supported", status.notSupported.length]]
            .map(([label, value]) => (
              <div key={label} className={card}>
                <p className="text-[11px] uppercase tracking-wide text-foreground-muted">{label}</p>
                <p className="mt-1 text-xl font-bold text-foreground">{value}</p>
              </div>
            ))}
        </div>
      )}
      <div className={card} data-testid="pl-decisions">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
        <ul className="space-y-1">
          {decisions.map((d) => (
            <li key={d.key} className="flex items-start justify-between gap-3 text-[12px]">
              <span className="text-foreground">{d.key} — {d.label}{d.blocksLaunch ? " (blocks launch)" : ""}</span>
              <span className={d.state === "RECORDED" ? "text-success" : "text-warning"}>{d.state}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
