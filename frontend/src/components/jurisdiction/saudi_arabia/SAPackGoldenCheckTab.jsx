import { useCallback, useEffect, useRef, useState } from "react";
import { getSaudiArabiaPackGoldenCheck } from "../../../service/superAdminService";

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";

function useLoad(loadFn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadFnRef = useRef(loadFn);
  useEffect(() => { loadFnRef.current = loadFn; }, [loadFn]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    loadFnRef.current()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e?.message || "Could not load."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, deps);

  return [data, error, loading, reload];
}

function Messages({ error, notice }) {
  return (
    <>
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[13px] text-success">{notice}</p>}
    </>
  );
}

export function SAPackGoldenCheckTab({ pack, addToast, onReload }) {
  const [result, resultError, resultLoading, reloadResult] = useLoad(
    () => pack ? getSaudiArabiaPackGoldenCheck(pack.id) : Promise.resolve(null),
    [pack?.id]
  );
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadResult(); } catch (e) { setError(e?.message || "Refused."); }
  }

  return (
    <div className="space-y-4">
      {resultLoading ? (
        <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
      ) : result ? (
        <>
          <div className={card} aria-labelledby="sa-golden-check">
            <h3 id="sa-golden-check" className="mb-1 text-[14px] font-semibold text-foreground">Pack Golden Check — {pack?.packId} v{pack?.version}</h3>
            <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
              Re-proves this pack against every SA golden vector in its window. Read-only; writes nothing.
            </p>
            {resultError && <p role="alert" className="text-[13px] text-error">{resultError}</p>}
            <div className="mb-3">
              <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${result?.passed ? "bg-success/10 text-success" : "bg-error/10 text-error"}`}>
                {result?.passed ? "PASSED" : "FAILED"}
              </span>
              <span className="ml-2 text-[12px] text-foreground-muted">Pack: {result?.packId} v{result?.version} · {result?.totalVectors} vectors · {result?.passedVectors} passed · {result?.failedVectors} failed</span>
            </div>
            {result?.details && result.details.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-border-light">
                <table className="w-full text-xs">
                  <thead className="bg-surface-muted text-foreground-muted">
                    <tr>{["Vector", "Pay Date", "Status", "Diffs"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {result.details.map((d, i) => (
                      <tr key={i} className="border-t border-border-light">
                        <td className={td}>{d.vector}</td>
                        <td className={td}>{d.payDate}</td>
                        <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${d.passed ? "bg-success/10 text-success" : "bg-error/10 text-error"}`}>{d.passed ? "PASS" : "FAIL"}</span></td>
                        <td className={td}>
                          {d.diffs && d.diffs.length > 0 ? (
                            <ul className="list-disc list-inside text-[10px] text-foreground-secondary">
                              {d.diffs.map((diff, j) => <li key={j}>{diff.field}: expected {diff.expected}, got {diff.actual}</li>)}
                            </ul>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : (
        <p className="text-[12px] text-foreground-muted py-4">Select a pack to run golden check.</p>
      )}
    </div>
  );
}