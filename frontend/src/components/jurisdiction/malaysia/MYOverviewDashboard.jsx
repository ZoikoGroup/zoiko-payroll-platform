import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import {
  getMyDecisions, getMyRolloverPlan, getMySigningStatus, listMyPacks, rolloverMyPack, seedMyDraftPack,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import { GROUPS } from "./myContent";

// Malaysia pack overview (ZP-MY-ENG-001 statutory content console): what still
// blocks activation (straight from the backend signing status), the owner
// decisions D-1..D-8, and, with no Malaysia pack yet, the governed "create the
// Draft pack from the specification" action (refused once any MY pack exists).
// Nothing becomes Active here; Malaysia stays PLANNED until gates G1-G7 pass.

export function SeedDraftPanel() {
  const [packs, setPacks] = useState(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null, done: false });

  useEffect(() => {
    listMyPacks().then((rows) => setPacks(rows || [])).catch(() => setPacks([]));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null, done: false });
    try {
      await seedMyDraftPack(reason.trim());
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
        <p className="mt-3 text-sm text-foreground-muted">Select a Malaysia tax pack to see its configuration.</p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-border bg-surface p-5" data-testid="my-seed-draft">
      <h3 className="text-[14px] font-semibold text-foreground">No Malaysia pack yet</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        Create the Draft MY-PAYROLL-2026 pack from the specification (ZP-MY-ENG-001). Every row starts EXTRACTED (PENDING
        G1) — even values the specification states — and the contribution schedules and holiday calendars start empty.
        Fill them with the statutory workbook, have each row signed by a Super Admin against its reviewed source, then a
        Super Admin who made none of the edits approves and activates.
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
        <form onSubmit={submit} className="mt-3 space-y-2" aria-label="Create the Draft Malaysia pack">
          <label className={labelClass} htmlFor="my-seed-reason">Reason *</label>
          <input id="my-seed-reason" className={inputClass} required value={reason}
            onChange={(e) => setReason(e.target.value)} placeholder="Why the Malaysia pack is being started" />
          <button type="submit" disabled={state.busy || !reason.trim()}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
            Create draft pack from the specification
          </button>
        </form>
      )}
    </div>
  );
}

// Next tax year: a Draft copy of this pack with every row PENDING G1 (values
// prefilled, re-signed against the new year's sources); holidays, PCB tables
// and authority examples are not copied. Refused once that year's pack exists.
export function RolloverPanel({ pack, onReload }) {
  const [plan, setPlan] = useState(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null, done: null });

  useEffect(() => {
    if (!pack) return;
    getMyRolloverPlan(pack.id).then(setPlan).catch(() => setPlan(null));
  }, [pack]);

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null, done: null });
    try {
      const out = await rolloverMyPack(pack.id, reason.trim());
      setState({ busy: false, error: null, done: out.created });
      onReload?.();
    } catch (err) {
      setState({ busy: false, error: err.message || "Could not create next year's pack.", done: null });
    }
  };

  if (!plan || !plan.targetPackId) return null;
  return (
    <div className={card} data-testid="my-rollover">
      <h3 className="text-[14px] font-semibold text-foreground">Next tax year: {plan.targetPackId}</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        Creates a Draft copy of {plan.sourcePackId} for {plan.effectiveFrom} to {plan.effectiveTo}: {plan.rates} parameter
        row(s) and {plan.slabs} table row(s), every one PENDING G1 until re-signed against the new year&apos;s official
        source. Not copied (load fresh): {plan.notCopied.join(", ")}. This pack is not changed.
      </p>
      <ErrorNote message={state.error} />
      {state.done ? (
        <p className="mt-3 text-[12px] text-success" role="status">
          {state.done.packId} created as {state.done.status}. Select it in the pack list to start signing.
        </p>
      ) : plan.refusal ? (
        <p className="mt-3 text-[12px] text-foreground-secondary" role="status">{plan.refusal}</p>
      ) : (
        <form onSubmit={submit} className="mt-3 space-y-2" aria-label="Create next year's Draft Malaysia pack">
          <label className={labelClass} htmlFor="my-rollover-reason">Reason *</label>
          <input id="my-rollover-reason" className={inputClass} required value={reason}
            onChange={(e) => setReason(e.target.value)} placeholder="Why next year's pack is being started" />
          <button type="submit" disabled={state.busy || !reason.trim()}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
            Create {plan.targetPackId} as Draft
          </button>
        </form>
      )}
    </div>
  );
}

export default function MYOverviewDashboard({ pack, onReload }) {
  const [status, setStatus] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    if (!pack) return;
    getMySigningStatus(pack.id)
      .then((data) => { setStatus(data); setError(null); })
      .catch((e) => setError(e.message || "Could not load the signing status."));
    getMyDecisions().then((rows) => setDecisions(rows || [])).catch(() => setDecisions([]));
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  if (!pack) return <SeedDraftPanel />;
  const ready = status && !status.activationRefusal;

  return (
    <div className="space-y-6" data-testid="my-overview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Malaysia statutory configuration</h2>
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
      <p className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary">
        PCB / MTD is blocked until the HASiL 2026 computerised specification is archived — {GROUPS.pcb.description}
      </p>
      {status && (
        <div className={`rounded-xl border p-3 text-[12px] ${ready ? "border-success/40 bg-success/10" : "border-warning/40 bg-warning/10"}`}
          data-testid="my-activation-state">
          {ready ? (
            <span className="inline-flex items-center gap-1.5 text-success">
              <CheckCircle2 size={14} /> Every row is signed and every table loaded. A Super Admin who made none of the
              edits may approve, then activate.
            </span>
          ) : (
            <span className="text-foreground-secondary"><strong>Activation is refused:</strong> {status.activationRefusal}</span>
          )}
        </div>
      )}
      {status && (
        <div className="grid gap-3 sm:grid-cols-5">
          {[["Pending parameters", status.pendingRates.length], ["Empty values", status.emptyValues.length],
            ["Undecided policies", status.pendingPolicies.length], ["Empty tables", status.emptyTables.length],
            ["Not supported", status.notSupported.length]]
            .map(([label, value]) => (
              <div key={label} className={card}>
                <p className="text-[11px] uppercase tracking-wide text-foreground-muted">{label}</p>
                <p className="mt-1 text-xl font-bold text-foreground">{value}</p>
              </div>
            ))}
        </div>
      )}
      <RolloverPanel pack={pack} onReload={onReload} />
      <div className={card} data-testid="my-decisions">
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
