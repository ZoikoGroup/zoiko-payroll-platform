import { useState } from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import {
  addBeAuthorityExample, getBeGoldenCheck, getBeSummary, runBeGoldenCertification, seedBeDraftPack,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import PackOverviewSummary from "../PackOverviewSummary";
import { beOverviewCounts, loadConfiguration, rowsHint } from "./beShared";

// Belgium pack Overview: the same summary every country shows
// (PackOverviewSummary — status chips, counts, effective dates, regions, needs
// attention) plus one chip with the engine certification and how many release
// gates are met, which opens the Release Readiness tab. The gates, their
// evidence and the golden certification live on that tab
// (BEReleaseReadinessTab, "Pack status"). With no Belgian pack yet, BECompliancePage offers the
// governed "create the Draft pack" action (SeedDraftPanel below).

export function SeedDraftPanel({ onDone }) {
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
        Creates the Draft pack from the content catalogue, with the approved specification values filled in. Nothing becomes Active here.
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

export function GoldenCertification({ pack }) {
  const [check, error, loading, reload] = useLoad(() => getBeGoldenCheck(pack.id));
  const [form, setForm] = useState({ name: "", description: "", case: "", sourceDocumentId: "", reason: "" });
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const act = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      const out = await fn();
      setState({ busy: false, error: null, notice: typeof notice === "function" ? notice(out) : notice });
      reload();
    } catch (err) {
      setState({ busy: false, error: err.message || "Refused.", notice: null });
    }
  };
  const register = (e) => {
    e.preventDefault();
    act(() => addBeAuthorityExample(pack.id, { ...form, sourceDocumentId: Number(form.sourceDocumentId) }),
      "Authority example registered.");
  };
  return (
    <div className={card} data-testid="be-golden">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">Golden certification (gate G1)</h3>
      <p className="text-[12px] text-foreground-secondary">
        Each official or independently prepared example is replayed through the engine with this pack&apos;s own rows;
        every expected figure must match exactly. The certification run is what pack activation requires.
      </p>
      <ErrorNote message={error || state.error} />
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {loading || !check ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <>
          <p className="mt-2 text-[12px] text-foreground">
            {check.examples} example(s) · {check.passed ? "all replay exactly" : "not passing"}
          </p>
          <ul className="mt-1 space-y-1 text-[12px]">
            {check.results.map((r) => (
              <li key={r.rowId} className={r.ok ? "text-success" : "text-error"}>
                {r.example}: {r.ok ? "match" : r.error || r.failures.map((f) => `${f.field} expected ${f.expected}, got ${f.actual}`).join("; ")}
              </li>
            ))}
          </ul>
        </>
      )}
      <button type="button" disabled={state.busy} className="mt-2 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50"
        onClick={() => act(() => runBeGoldenCertification(pack.id), (out) => `Certification run #${out?.runId}: ${out?.status}.`)}>
        Record certification run
      </button>
      <form onSubmit={register} className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2" aria-label="Register an authority example">
        <label className={labelClass}>Name *<input className={inputClass} value={form.name} onChange={set("name")} /></label>
        <label className={labelClass}>Reviewed source id *<input className={inputClass} inputMode="numeric"
          value={form.sourceDocumentId} onChange={set("sourceDocumentId")} /></label>
        <label className={`${labelClass} md:col-span-2`}>Description *<input className={inputClass} value={form.description}
          onChange={set("description")} /></label>
        <label className={`${labelClass} md:col-span-2`}>Worked case (inputs =&gt; expected; figures from the source)
          <input className={inputClass} value={form.case} onChange={set("case")} /></label>
        <label className={labelClass}>Reason *<input className={inputClass} value={form.reason} onChange={set("reason")} /></label>
        <div className="flex items-end">
          <button type="submit" disabled={state.busy} className="rounded-lg border border-border px-3 py-1.5 text-[12px]">Register example</button>
        </div>
      </form>
    </div>
  );
}

function EngineChip({ onOpen }) {
  const [summary, error] = useLoad(getBeSummary);
  if (error || !summary) return null;
  const ok = Boolean(summary.available);
  const Icon = ok ? ShieldCheck : ShieldAlert;
  return (
    <button type="button" onClick={onOpen} data-testid="be-engine-chip"
      title="Open Pack status"
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold underline-offset-2 hover:underline ${
        ok ? "bg-success/10 text-success" : "bg-warning/10 text-warning"
      }`}>
      <Icon size={12} aria-hidden="true" />
      Onboarding: {ok ? "open" : "closed until a pack is Active"}
    </button>
  );
}

// The four summary cards counted from Belgium's own configuration data (the
// generic counter only sees rows with a stored rate; every unsigned Belgian
// row is empty until it is signed). Falls back to the generic cards while the
// configuration loads or if it cannot be read.
function useBeStats(pack) {
  const [config] = useLoad(() => loadConfiguration(pack));
  if (!config) return null;
  const c = beOverviewCounts(config);
  return [
    { label: "Employee deductions", value: c.employee.rows, hint: `ONSS employee · ${rowsHint(c.employee)}` },
    { label: "Employer contributions", value: c.employer.rows, hint: `ONSS employer & reductions · ${rowsHint(c.employer)}` },
    { label: "Parameters & thresholds", value: c.parameters.rows, hint: rowsHint(c.parameters) },
    { label: "Tax slabs / bands", value: c.slabs.rows,
      hint: `${rowsHint(c.slabs)}${c.slabs.keysWithoutRows ? ` · ${c.slabs.keysWithoutRows} of ${c.slabs.keys} band / formula keys have none yet` : ""}` },
  ];
}

function Summary({ pack, refreshKey, onNavigateTab }) {
  const stats = useBeStats(pack);
  return (
    <PackOverviewSummary
      pack={pack} refreshKey={refreshKey} stats={stats}
      extraFlags={<EngineChip onOpen={() => onNavigateTab?.("be-release")} />}
    />
  );
}

export default function BEOverviewDashboard({ pack, refreshKey, onNavigateTab }) {
  return (
    <div data-testid="be-overview">
      <Summary key={pack?.id} pack={pack} refreshKey={refreshKey} onNavigateTab={onNavigateTab} />
    </div>
  );
}
