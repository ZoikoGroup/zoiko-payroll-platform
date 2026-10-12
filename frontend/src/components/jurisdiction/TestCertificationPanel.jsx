import { useState, useEffect, Fragment } from "react";
import { ShieldCheck, Play } from "lucide-react";
import { useToast } from "../../context/ToastContext";
import { runTestCertification, getTestCertificationRuns } from "../../service/superAdminService";

// Shared body of the Certification Console (§19 gap-closure Part 11,
// 2026-09-09) — extracted from the standalone TestCertificationPage so
// it can ALSO be surfaced inside a single country's own Compliance
// workspace (gap-closure Plan Phase 4, 2026-09-14: "surface the
// Certification Console per-country" — previously it only existed as a
// disconnected top-level page with its own jurisdiction picker, with no
// path from e.g. USACompliancePage into it at all). "NO_REAL_CASES" is
// deliberately never displayed as a pass — an empty real-case set
// proves nothing about correctness.
const STATUS_STYLE = {
  PASS: "bg-success/10 text-success",
  FAIL: "bg-error/10 text-error",
  NO_REAL_CASES: "bg-warning/10 text-warning",
};
const STATUS_LABEL = {
  PASS: "Pass", FAIL: "Fail", NO_REAL_CASES: "No real cases yet",
};

export default function TestCertificationPanel({ jurisdiction, label, fixturesPath }) {
  const { addToast } = useToast() || {};
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState(null);

  function load() {
    setLoading(true);
    getTestCertificationRuns({ jurisdiction_country: jurisdiction }).then(setRuns).finally(() => setLoading(false));
  }
  useEffect(load, [jurisdiction]);

  async function handleRun() {
    setRunning(true);
    try {
      const run = await runTestCertification(jurisdiction);
      if (run.status === "NO_REAL_CASES") {
        addToast?.(`Run complete — 0 real ${label} cases exist yet. Nothing was certified.`, "info");
      } else {
        addToast?.(`Run complete — ${run.passedCases}/${run.totalCases} passed.`, run.status === "PASS" ? "success" : "error");
      }
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to run certification.", "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-primary" />
          <div>
            <h2 className="text-lg font-bold text-foreground">Test Certification</h2>
            <p className="mt-0.5 text-xs text-foreground-muted">
              A real run of the golden-test harness for {label}, blocking pack activation (§11.2) on any unresolved failure.
            </p>
          </div>
        </div>
        <button
          onClick={handleRun} disabled={running}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
        >
          <Play size={14} /> {running ? "Running…" : "Run Now"}
        </button>
      </div>

      {fixturesPath && (
        <div className="mb-4 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-foreground-secondary">
          Golden cases are only as good as their source — see <code>{fixturesPath}</code> for how cases for {label} are sourced and added.
        </div>
      )}

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : runs.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No runs yet — click "Run Now" to certify.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-muted text-foreground-muted">
              <tr>
                <th className="px-3 py-2 text-left">Run</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-right">Real Cases</th>
                <th className="px-3 py-2 text-right">Passed</th>
                <th className="px-3 py-2 text-right">Failed</th>
                <th className="px-3 py-2 text-left"></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <Fragment key={r.id}>
                  <tr className="border-t border-border-light">
                    <td className="px-3 py-2">{r.runAt ? new Date(r.runAt).toLocaleString() : "—"}</td>
                    <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_STYLE[r.status] || ""}`}>{STATUS_LABEL[r.status] || r.status}</span></td>
                    <td className="px-3 py-2 text-right">{r.realCaseCount}</td>
                    <td className="px-3 py-2 text-right">{r.passedCases}</td>
                    <td className="px-3 py-2 text-right">{r.failedCases}</td>
                    <td className="px-3 py-2">
                      {r.failureDetails?.length > 0 && (
                        <button onClick={() => setExpanded(expanded === r.id ? null : r.id)} className="font-semibold text-primary hover:underline">
                          {expanded === r.id ? "Hide" : "View"} failures
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded === r.id && r.failureDetails?.map((f, i) => (
                    <tr key={`${r.id}-fail-${i}`} className="border-t border-border-light bg-error/5">
                      <td colSpan={6} className="px-3 py-2">
                        <span className="font-semibold">{f.case}</span>:{" "}
                        {f.diffs.map((d, j) => (
                          <span key={j} className="mr-3">{d.field}: expected {d.expected}, got {d.actual}</span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
