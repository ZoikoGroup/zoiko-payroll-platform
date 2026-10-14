import { useCallback, useEffect, useRef, useState } from "react";
import {
  listSaWpsFiles,
  buildSaWpsFile,
  listSaWpsObservations,
  acceptSaWpsFile,
  rejectSaWpsFile,
} from "../../../service/superAdminService";

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

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

export function SAWpsTab({ organizationId, packId, disabled }) {
  const [files, filesError, filesLoading, reloadFiles] = useLoad(
    () => listSaWpsFiles(organizationId),
    [organizationId]
  );
  const [buildRunId, setBuildRunId] = useState("");
  const [obsFileId, setObsFileId] = useState("");
  const [obs, obsError, obsLoading, reloadObs] = useLoad(
    () => obsFileId ? listSaWpsObservations(organizationId, obsFileId) : Promise.resolve(null),
    [obsFileId, organizationId]
  );
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reloadFiles(); } catch (e) { setError(e?.message || "Refused."); }
  }

  if (disabled) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-surface/50 p-4 text-center">
          <p className="text-[13px] text-foreground-muted">Select an organization from the picker above to manage WPS SIE Extract.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Messages error={error || filesError} notice={notice} />
      <section className={card} aria-labelledby="sa-wps-files">
        <h3 id="sa-wps-files" className="mb-1 text-[14px] font-semibold text-foreground">WPS SIE Extract (SA-025)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Salary Information Extract for Mudad Wage Protection System. Content-addressed (SHA-256), deduped, tracked through UPLOADED → ACCEPTED/REJECTED.
        </p>
        {filesLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : files && (
          <table className="w-full" aria-label="WPS files">
            <thead>
              <tr>{["Run", "Month", "SHA-256", "Employees", "Total Net", "Status", "Observations", "Accepted By", "Rejected By", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {files.length === 0 && <tr><td className={td} colSpan={10}>No WPS files yet.</td></tr>}
              {files.map((f) => (
                <tr key={f.id} className="border-t border-border">
                  <td className={td}>{f.sourceRunId ?? "—"}</td>
                  <td className={td}>{f.periodMonth ? new Date(f.periodMonth).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "—"}</td>
                  <td className={td}><code className="text-[10px] font-mono">{f.fileSha256 ? f.fileSha256.slice(0, 16) + "…" : "—"}</code></td>
                  <td className={td}>{f.employeeCount ?? "—"}</td>
                  <td className={td}>SAR {f.totalAmount ?? "—"}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${f.status === "ACCEPTED" ? "bg-success/10 text-success" : f.status === "REJECTED" ? "bg-error/10 text-error" : "bg-warning/10 text-warning"}`}>{label(f.status)}</span></td>
                  <td className={td}>{f.observationCount ?? 0}</td>
                  <td className={td}>{f.acceptedById ?? "—"}</td>
                  <td className={td}>{f.rejectedById ?? "—"}</td>
                  <td className={td}>
                    {f.status === "UPLOADED" && (
                      <>
                        <button type="button" className={btn} onClick={() => act(() => acceptSaWpsFile(organizationId, f.id), `WPS file accepted.`)}>Accept</button>
                        <button type="button" className={btn} onClick={() => act(() => rejectSaWpsFile(organizationId, f.id, window.prompt("Rejection reason") || ""), `WPS file rejected.`)}>Reject</button>
                      </>
                    )}
                    <button type="button" className={btn} onClick={() => { setObsFileId(f.id); }}>View Obs</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input aria-label="Run ID to build WPS from" placeholder="Run ID" className={`${input} w-28`} value={buildRunId} onChange={(e) => setBuildRunId(e.target.value)} />
          <button type="button" className={btn} disabled={!buildRunId} onClick={() => act(() => buildSaWpsFile(organizationId, Number(buildRunId)), "WPS file built from run.")}>Build from Run</button>
        </div>
      </section>

      {obsFileId && (
        <section className={card} aria-labelledby="sa-wps-obs">
          <div className="flex items-center justify-between mb-2">
            <h3 id="sa-wps-obs" className="text-[14px] font-semibold text-foreground">Observations for file #{obsFileId}</h3>
            <button type="button" className={btn} onClick={() => setObsFileId("")}>Close</button>
          </div>
          {obsLoading ? (
            <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
          ) : obsError ? (
            <p role="alert" className="text-[13px] text-error">{obsError}</p>
          ) : obs.length === 0 ? (
            <p className="text-[12px] text-foreground-muted">No observations.</p>
          ) : (
            <table className="w-full" aria-label="WPS observations">
              <thead><tr>{["Code", "Employee", "Field", "Value", "Severity", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>
                {obs.map((o) => (
                  <tr key={o.id} className="border-t border-border">
                    <td className={td}>{o.observationCode}</td>
                    <td className={td}>{o.employeeName || o.employeeId}</td>
                    <td className={td}>{o.field}</td>
                    <td className={td}>{o.value}</td>
                    <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${o.severity === "ERROR" ? "bg-error/10 text-error" : "bg-warning/10 text-warning"}`}>{label(o.severity)}</span></td>
                    <td className={td}></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}