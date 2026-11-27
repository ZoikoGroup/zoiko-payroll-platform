import { useMemo, useState } from "react";
import { CalendarPlus, ChevronDown, Users } from "lucide-react";

import CountryFlag from "../../../components/jurisdiction/CountryFlag";
import { getCurrencyForJurisdiction } from "../../../utils/currency";
import RunWorkflowTracker from "./RunWorkflowTracker";
import { STEP_GUIDE, monthLabel, pickDefaultRuns } from "./runWorkflow";

// Below the lg breakpoint the panel sits above the table: start collapsed
// there (a one-line summary) so the table stays in view.
const startsCollapsed = () => {
  try {
    return window.matchMedia("(max-width: 1023px)").matches;
  } catch {
    return false;
  }
};

// Left panel of the Payroll Runs list: follows ONE real run through
// Draft -> Closed. Which run:
//   1. the run the user clicked in the table (trackedRunId), else
//   2. this month's run (most recent if there are several - switchable), else
//   3. "No payroll run for <month>" + Create run, and the most recent run
//      that isn't Closed yet.

function RunSummary({ run, countries }) {
  return (
    <div className="mb-3 rounded-[12px] border border-border bg-surface-muted p-3">
      <p className="text-[14px] font-bold text-foreground">{run.period}</p>
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
}) {
  const [collapsed, setCollapsed] = useState(startsCollapsed);
  const today = useMemo(() => new Date(), []);
  const { thisMonth, latestUnfinished } = useMemo(() => pickDefaultRuns(runs, today), [runs, today]);

  const clicked = trackedRunId != null ? (runs || []).find((r) => r.id === trackedRunId) : null;
  const run = clicked || thisMonth[0] || latestUnfinished || null;
  const noRunThisMonth = thisMonth.length === 0;

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
              <span className="font-bold text-foreground">{run.period}</span>
              <span className="text-foreground-muted"> · {run.status}</span>
              {STEP_GUIDE[run.status]?.action && (
                <span className="block text-info">Next: {STEP_GUIDE[run.status].action}</span>
              )}
            </>
          ) : (
            <span className="text-foreground-muted">No payroll run for {monthLabel(today)}</span>
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
            {run && !clicked && (
              <p className="mt-2 text-[11px] text-foreground-muted">Showing the most recent unfinished run:</p>
            )}
          </div>
        )}

        {!noRunThisMonth && thisMonth.length > 1 && !clicked && (
          <label className="mb-3 block">
            <span className="mb-1 block text-[11px] font-semibold text-foreground-muted">
              {thisMonth.length} runs this month
            </span>
            <select
              value={run?.id ?? ""}
              onChange={(e) => onTrack(Number(e.target.value))}
              className="w-full rounded-[10px] border border-border bg-background px-2.5 py-1.5 text-[12px] text-foreground focus:border-primary focus:outline-none"
            >
              {thisMonth.map((r) => (
                <option key={r.id} value={r.id}>{r.period} · {r.status}{r.runCode ? ` · ${r.runCode}` : ""}</option>
              ))}
            </select>
          </label>
        )}

        {clicked && (
          <button
            type="button"
            onClick={() => onTrack(null)}
            className="mb-2 text-[11px] font-semibold text-primary hover:underline"
          >
            ← Back to {noRunThisMonth ? "the default run" : "this month's run"}
          </button>
        )}

        {run ? (
          <>
            <RunSummary run={run} countries={countries} />
            <RunWorkflowTracker
              run={run}
              orientation="vertical"
              canOperate={canOperate}
              onAdvance={onAdvance}
              busy={advancingId === run.id}
            />
            <p className="mt-3 text-[11px] text-foreground-muted">
              Hover or tap a step to see what happens there. Click a row in the table to follow another run.
            </p>
          </>
        ) : (
          !noRunThisMonth ? null : (
            <p className="text-[12px] text-foreground-muted">No unfinished runs.</p>
          )
        )}
      </div>
    </section>
  );
}
