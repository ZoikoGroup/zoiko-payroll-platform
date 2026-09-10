import { useState, useEffect, Fragment } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ShieldCheck, Play } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { runTestCertification, getTestCertificationRuns } from "../service/superAdminService";

// Super Admin > Compliance > Test Certification (§19 gap-closure
// Part 11, 2026-09-09) — triggers a real run of the Part 10 HMRC
// golden-test harness and shows run history. "NO_REAL_CASES" is
// deliberately never displayed as a pass — an empty real-case set
// proves nothing about correctness (Part 10 is blocked on Venu
// obtaining the actual HMRC test-data files; see tests/hmrc_golden's
// own README for how to get them).
const STATUS_STYLE = {
  PASS: "bg-success/10 text-success",
  FAIL: "bg-error/10 text-error",
  NO_REAL_CASES: "bg-warning/10 text-warning",
};
const STATUS_LABEL = {
  PASS: "Pass", FAIL: "Fail", NO_REAL_CASES: "No real cases yet",
};

export default function TestCertificationPage() {
  const { addToast } = useToast() || {};
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState(null);

  function load() {
    getTestCertificationRuns().then(setRuns).finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleRun() {
    setRunning(true);
    try {
      const run = await runTestCertification();
      if (run.status === "NO_REAL_CASES") {
        addToast?.("Run complete — 0 real HMRC cases exist yet. Nothing was certified.", "info");
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
    <div>
      <Link to="/super-admin/compliance" className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
        <ArrowLeft size={14} /> Back to Compliance
      </Link>
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck size={20} className="text-primary" />
          <div>
            <h1 className="text-2xl font-bold text-foreground">Test Certification</h1>
            <p className="text-sm text-foreground-muted mt-0.5">HMRC golden-test harness pass/fail history (Part 10).</p>
          </div>
        </div>
        <button
          onClick={handleRun} disabled={running}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
        >
          <Play size={14} /> {running ? "Running…" : "Run Now"}
        </button>
      </div>

      <div className="mb-4 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-foreground-secondary">
        Real HMRC test-data files haven't been obtained yet (GOV.UK's own published payroll test data) — every run today will
        correctly report "No real cases yet" rather than a false pass. See <code>backend/tests/fixtures/hmrc_golden/README.md</code> for how to add real cases.
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-sm text-foreground-disabled">No runs yet — click "Run Now" to certify.</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead className="bg-surface-muted text-foreground-muted">
              <tr>
                <th className="px-4 py-3 text-left">Run</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Real Cases</th>
                <th className="px-4 py-3 text-right">Passed</th>
                <th className="px-4 py-3 text-right">Failed</th>
                <th className="px-4 py-3 text-left"></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <Fragment key={r.id}>
                  <tr className="border-t border-border">
                    <td className="px-4 py-3">{r.runAt ? new Date(r.runAt).toLocaleString() : "—"}</td>
                    <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_STYLE[r.status] || ""}`}>{STATUS_LABEL[r.status] || r.status}</span></td>
                    <td className="px-4 py-3 text-right">{r.realCaseCount}</td>
                    <td className="px-4 py-3 text-right">{r.passedCases}</td>
                    <td className="px-4 py-3 text-right">{r.failedCases}</td>
                    <td className="px-4 py-3">
                      {r.failureDetails?.length > 0 && (
                        <button onClick={() => setExpanded(expanded === r.id ? null : r.id)} className="text-primary font-semibold hover:underline">
                          {expanded === r.id ? "Hide" : "View"} failures
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded === r.id && r.failureDetails?.map((f, i) => (
                    <tr key={`${r.id}-fail-${i}`} className="border-t border-border bg-error/5">
                      <td colSpan={6} className="px-4 py-2">
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
