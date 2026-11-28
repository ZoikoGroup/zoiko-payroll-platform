import { useMemo, useState } from "react";
import { CalendarPlus, ChevronDown, Users, X } from "lucide-react";

import CountryFlag from "../../../components/jurisdiction/CountryFlag";
import { getCurrencyForJurisdiction } from "../../../utils/currency";
import RunWorkflowTracker from "./RunWorkflowTracker";
import { STEP_GUIDE, monthLabel, periodRangeLabel, pickDefaultRuns, sortRunsNewestFirst } from "./runWorkflow";

// Below the lg breakpoint the panel sits above the table: start collapsed
// there (a one-line summary) so the table stays in view.
const startsCollapsed = () => {
  try {
    return window.matchMedia("(max-width: 1023px)").matches;
  } catch {
    return false;
  }
};

// The run code is made by generate_business_code (backend
// app/core/code_generation.py): organisation code + "PY" + the YEAR AND MONTH
// THE RUN WAS CREATED (not its pay period) + a 3-digit sequence within that
// month. VGPY202611001 = org VG, a payroll run, created Nov 2026, the first
// one that month.
const RUN_ID_HELP = "Run ID: organisation code + PY + the year and month the run was created "
  + "(not its pay period) + its number within that month.";

// Left panel of the Payroll Runs list. Nothing is tracked until the user picks
// a run - in the "Show run" dropdown or by clicking a row in the table (both
// set trackedRunId, so they stay in sync). Above it: "No payroll run for
// <this month>" + Create run when this month has no run yet.

function RunSummary({ run, countries }) {
  return (
    <div className="mb-3 rounded-[12px] border border-border bg-surface-muted p-3">
      <p className="text-[14px] font-bold text-foreground">{periodRangeLabel(run)}</p>
      {run.runCode && (
        <p className="mt-0.5 text-[11px] text-foreground-muted" title={RUN_ID_HELP}>
          Run ID: <span className="font-mono">{run.runCode}</span>
        </p>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-foreground-muted">
        <span className="inline-flex items-center gap-1.5">
          {countries.map((c) => (
            <span key={c.code} className="inline-flex items-center gap-1" title={c.name}>
              <CountryFlag code={c.code} name={c.name} size="xs" decorative />
              <span className="font-semibold text-foreground">{c.code}</span>
              {c.currency && <span>· {c.currency}</span>}
            </span>
          ))}
        </span>
        <span className="inline-flex items-center gap-1">
          <Users size={12} aria-hidden="true" /> {run.employees ?? 0} employee{run.employees === 1 ? "" : "s"}
        </span>
      </div>
      <p className="mt-1.5 text-[12px]">
        <span className="text-foreground-muted">Status: </span>
        <span className="font-bold text-foreground">{run.status}</span>
      </p>
    </div>
  );
}

export default function RunTrackerPanel({
  runs,
  trackedRunId,
  onTrack,
  activeCountries,
  canOperate,
  onAdvance,
  advancingId,
  onCreateRun,
  creating,
  onHighlight,
}) {
  const [collapsed, setCollapsed] = useState(startsCollapsed);
  const today = useMemo(() => new Date(), []);
  const { thisMonth } = useMemo(() => pickDefaultRuns(runs, today), [runs, today]);
  // Newest pay period first; the top one is marked "Latest".
  const ordered = useMemo(() => sortRunsNewestFirst(runs), [runs]);

  const run = trackedRunId != null ? ordered.find((r) => r.id === trackedRunId) || null : null;
  const noRunThisMonth = thisMonth.length === 0;
  const optionLabel = (r, i) => `${periodRangeLabel(r)} · ${r.status}${i === 0 ? " · Latest" : ""}`;

  // Countries a run pays: an org's run covers every one of its active
  // countries (each employee under their own country's rules).
  const countries = (activeCountries || []).map((c) => ({
    code: c.code, name: c.name, currency: getCurrencyForJurisdiction(c.code)?.code,
  }));

  return (
    <section aria-label="Run progress">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="mb-3 flex w-full items-center justify-between text-left lg:pointer-events-none"
      >
        <span className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Run progress</span>
        <ChevronDown size={14} aria-hidden="true"
          className={`text-foreground-muted transition-transform lg:hidden ${collapsed ? "-rotate-90" : ""}`} />
      </button>
      {collapsed && (
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="mb-1 w-full rounded-[10px] border border-border bg-surface-muted px-3 py-2 text-left text-[12px] lg:hidden"
        >
          {run ? (
            <>
              <span className="font-bold text-foreground">{periodRangeLabel(run)}</span>
              <span className="text-foreground-muted"> · {run.status}</span>
              {STEP_GUIDE[run.status]?.action && (
                <span className="block text-info">Next: {STEP_GUIDE[run.status].action}</span>
              )}
            </>
          ) : noRunThisMonth ? (
            <span className="text-foreground-muted">No payroll run for {monthLabel(today)}</span>
          ) : (
            <span className="text-foreground-muted">Select a payroll run</span>
          )}
        </button>
      )}

      <div className={collapsed ? "hidden lg:block" : ""}>
        {noRunThisMonth && (
          <div className="mb-3 rounded-[12px] border border-dashed border-border p-3">
            <p className="text-[13px] font-semibold text-foreground">No payroll run for {monthLabel(today)}</p>
            {canOperate && onCreateRun && (
              <button
                type="button"
                onClick={onCreateRun}
                disabled={creating}
                className="mt-2 inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-3 py-1.5 text-[12px] font-bold text-white hover:bg-primary-hover disabled:opacity-60"
              >
                <CalendarPlus size={13} aria-hidden="true" /> {creating ? "Loading…" : "Create run"}
              </button>
            )}
          </div>
        )}

        {ordered.length > 0 && (
          <div className="mb-3">
            <div className="mb-1 flex items-center justify-between">
              <label htmlFor="run-progress-select" className="text-[11px] font-semibold text-foreground-muted">
                Show run
              </label>
              {run && (
                <button
                  type="button"
                  onClick={() => onTrack(null)}
                  className="inline-flex items-center gap-0.5 rounded-[6px] px-1 text-[11px] font-semibold text-foreground-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <X size={11} aria-hidden="true" /> Clear
                </button>
              )}
            </div>
            <select
              id="run-progress-select"
              value={run ? String(run.id) : ""}
              onChange={(e) => onTrack(e.target.value ? Number(e.target.value) : null)}
              className="w-full rounded-[10px] border border-border bg-background px-2.5 py-1.5 text-[12px] text-foreground focus:border-primary focus:outline-none"
            >
              <option value="">Select a payroll run</option>
              {ordered.map((r, i) => <option key={r.id} value={r.id}>{optionLabel(r, i)}</option>)}
            </select>
          </div>
        )}

        {run ? (
          <>
            <RunSummary run={run} countries={countries} />
            <RunWorkflowTracker
              run={run}
              canOperate={canOperate}
              onAdvance={onAdvance}
              busy={advancingId === run.id}
              onHighlight={onHighlight}
            />
            <p className="mt-3 text-[11px] text-foreground-muted">
              Hover or tap a step to see what happens there. Pick another run above, or click a row in the table,
              to follow it.
            </p>
          </>
        ) : (
          ordered.length > 0 && (
            <p className="text-[12px] text-foreground-muted">
              Select a run above, or click a row in the table, to see its progress.
            </p>
          )
        )}
      </div>
    </section>
  );
}
