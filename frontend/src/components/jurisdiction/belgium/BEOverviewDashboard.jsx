import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { getBeSigningStatus, getBeSummary, seedBeDraftPack } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// Belgium pack overview (ZP-BE-ENG-001 §14 "Belgium readiness"): pack status,
// the release gates G1–G7 exactly as the backend statutory summary reports them
// (NOT MET until Phase 10 computes them), and the signing counts. With no
// Belgian pack yet, offers the governed "create the Draft pack" action. No
// "ready" status is ever shown while a gate is NOT MET.

function SeedDraftPanel({ onDone }) {
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null });
  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null });
    try {
      await seedBeDraftPack(reason.trim());
      setState({ busy: false, error: null });
      onDone?.();
    } catch (err) {
      setState({ busy: false, error: err.message || "Could not create the Draft pack." });
    }
  };
  return (
    <form onSubmit={submit} className={`${card} space-y-2`} data-testid="be-seed-draft">
      <h3 className="text-[14px] font-semibold text-foreground">No Belgium pack yet</h3>
      <p className="text-[12px] text-foreground-secondary">
        Creates the Draft pack from the content catalogue: every row PENDING G1 with no value. Nothing becomes Active here.
      </p>
      <label className={labelClass} htmlFor="be-seed-reason">Reason *</label>
      <input id="be-seed-reason" className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      <ErrorNote message={state.error} />
      <button type="submit" disabled={state.busy || !reason.trim()}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
        {state.busy ? "Creating…" : "Create the Draft pack"}
      </button>
    </form>
  );
}

function SigningCounts({ pack }) {
  const [status, error] = useLoad(() => getBeSigningStatus(pack.id));
  if (error) return <ErrorNote message={error} />;
  if (!status) return null;
  const items = [
    ["Pending (unsigned) rows", status.pendingRates.length],
    ["Rows without a value", status.emptyValues.length],
    ["Rows without a source", status.unsourced.length],
    ["Signed NOT_SUPPORTED", status.notSupported.length],
    ["Earning classes still REVIEW", status.reviewClasses],
  ];
  return (
    <div className={card} data-testid="be-signing-counts">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Signing — {status.packId} v{status.version} ({status.status})</h3>
      <dl className="grid grid-cols-2 gap-2 text-[12px] md:grid-cols-5">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-lg bg-surface-muted p-2">
            <dt className="text-foreground-muted">{label}</dt>
            <dd className="text-[16px] font-semibold text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      {status.activationRefusal && (
        <p className="mt-3 flex items-start gap-2 text-[12px] text-warning"><AlertTriangle size={14} /> {status.activationRefusal}</p>
      )}
    </div>
  );
}

export default function BEOverviewDashboard({ pack }) {
  const [summary, error, , reload] = useLoad(getBeSummary);
  if (error) return <ErrorNote message={error} />;
  if (!summary) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return (
    <div className="space-y-4" data-testid="be-overview">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Belgium — {summary.spec}</h3>
        <p className="text-[12px] text-foreground-secondary">
          Engine status: <strong>{summary.status}</strong> · available for onboarding: <strong>{summary.available ? "yes" : "no"}</strong>
        </p>
        <h4 className="mt-3 mb-1 text-[12px] font-semibold text-foreground">Release gates</h4>
        <ul className="grid grid-cols-2 gap-1 text-[12px] md:grid-cols-7" data-testid="be-gates">
          {Object.entries(summary.gates || {}).map(([gate, state]) => (
            <li key={gate} className="rounded border border-error/30 bg-error/5 px-2 py-1 text-error">{gate}: {state}</li>
          ))}
        </ul>
      </div>
      {(summary.packs || []).length === 0 ? <SeedDraftPanel onDone={reload} /> : pack && <SigningCounts key={pack.id} pack={pack} />}
    </div>
  );
}
