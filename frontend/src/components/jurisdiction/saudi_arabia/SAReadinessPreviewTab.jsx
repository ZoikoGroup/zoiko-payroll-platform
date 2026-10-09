import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSaReadiness,
  previewSaudiArabiaCalculation,
} from "../../../service/superAdminService";

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

const TONE = { PASS: "text-success", FAIL: "text-error", BLOCKED: "text-error", PENDING: "text-warning", NOT_APPLICABLE: "text-foreground-muted" };

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

export function SAReadinessPreviewTab({ packId }) {
  const [readiness, readinessError, readinessLoading, reloadReadiness] = useLoad(
    () => getSaReadiness(packId),
    [packId]
  );
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [form, setForm] = useState({
    jurisdictionPackId: packId,
    payDate: new Date().toISOString().slice(0, 10),
    gross: "10000",
    basic: "10000",
    payFrequency: "Monthly",
    organizationId: null,
    employeeId: null,
    workerClass: "SAUDI",
    cohort: "NEW",
    cohortEvidenceRef: "preview",
    contributoryWage: "10000",
    deductionOrders: [],
    overtimeHours: null,
    ramadan: false,
    workHoursRecords: [],
  });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); } catch (e) { setError(e?.message || "Refused."); }
  }

  return (
    <div className="space-y-4">
      <Messages error={error} notice={notice} />
      <div className={card} aria-labelledby="sa-readiness">
        <h3 id="sa-readiness" className="mb-1 text-[14px] font-semibold text-foreground">Production Readiness Gates (SA-016/SA-017)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Read-only: Saudi Arabia release gates for one SA tax pack. Gates that depend on work outside this platform (specialist review, WPS generation, EOS ledger, parallel payroll) stay incomplete until evidenced.
        </p>
        {readinessLoading ? (
          <p className="text-center text-[12px] text-foreground-muted py-4">Loading…</p>
        ) : readiness ? (
          <>
            {readinessError && <p role="alert" className="text-[13px] text-error">{readinessError}</p>}
            <div className="mb-3">
              <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${readiness.ready ? "bg-success/10 text-success" : "bg-error/10 text-error"}`}>
                {readiness.ready ? "READY FOR PRODUCTION" : "BLOCKED"}
              </span>
              <span className="ml-2 text-[12px] text-foreground-muted">As of {readiness.asOf} · Pack {readiness.pack?.packId} v{readiness.pack?.version}</span>
            </div>
            {readiness.blockers && readiness.blockers.length > 0 && (
              <div className="mb-4 p-3 rounded-lg bg-error/5 border border-error/20">
                <p className="text-[12px] font-medium text-error mb-1">Blockers:</p>
                <ul className="list-disc list-inside text-[11px] text-error/80">
                  {readiness.blockers.map((b, i) => <li key={i}>{b}</li>)}
                </ul>
              </div>
            )}
            <table className="w-full" aria-label="Readiness gates">
              <thead><tr>{["Gate", "Status", "Detail"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>
                {readiness.items?.map((item) => (
                  <tr key={item.key} className="border-t border-border">
                    <td className={td}>{item.label}</td>
                    <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${item.complete ? "bg-success/10 text-success" : item.required ? "bg-error/10 text-error" : "bg-warning/10 text-warning"}`}>{item.complete ? "COMPLETE" : item.required ? "BLOCKER" : "PENDING"}</span></td>
                    <td className={td}>{item.detail || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="text-[12px] text-foreground-muted py-4">Select a pack to view readiness.</p>
        )}
      </div>

      <div className={card} aria-labelledby="sa-preview">
        <h3 id="sa-preview" className="mb-1 text-[14px] font-semibold text-foreground">Calculation Preview (ZP-SA-ENG-001 §13)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          Read-only simulation against the active SA pack — writes nothing. Same production engine as a payroll run.
        </p>
        <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-4`} onSubmit={(e) => { e.preventDefault(); setPreviewError(null); act(() => previewSaudiArabiaCalculation(form).then(setPreview).catch((err) => setPreviewError(err?.message || "Preview failed.")), "Preview calculated."); }}>
          <label className="text-[12px] text-foreground-secondary">Worker Class
            <select aria-label="Worker class" className={`${input} ml-1`} value={form.workerClass} onChange={(e) => setForm({ ...form, workerClass: e.target.value })}>
              <option value="SAUDI">Saudi</option>
              <option value="NON_SAUDI">Non-Saudi</option>
              <option value="GCC">GCC</option>
              <option value="DOMESTIC">Domestic</option>
            </select>
          </label>
          <label className="text-[12px] text-foreground-secondary">Cohort
            <select aria-label="Cohort" className={`${input} ml-1`} value={form.cohort} onChange={(e) => setForm({ ...form, cohort: e.target.value })}>
              <option value="NEW">New</option>
              <option value="LEGACY">Legacy</option>
            </select>
          </label>
          <input aria-label="Cohort Evidence Ref" placeholder="Cohort Evidence Ref" className={`${input} w-44`} value={form.cohortEvidenceRef} onChange={(e) => setForm({ ...form, cohortEvidenceRef: e.target.value })} />
          <input aria-label="Contributory Wage" placeholder="Contributory Wage (SAR)" className={`${input} w-36`} value={form.contributoryWage} onChange={(e) => setForm({ ...form, contributoryWage: e.target.value })} />
          <input aria-label="Gross (SAR)" placeholder="Gross (SAR)" className={`${input} w-32`} value={form.gross} onChange={(e) => setForm({ ...form, gross: e.target.value })} />
          <input aria-label="Basic (SAR)" placeholder="Basic (SAR)" className={`${input} w-32`} value={form.basic} onChange={(e) => setForm({ ...form, basic: e.target.value })} />
          <input aria-label="Pay Date" type="date" className={`${input} w-36`} value={form.payDate} onChange={(e) => setForm({ ...form, payDate: e.target.value })} />
          <div className="flex items-end"><button type="submit" className={btn}>Run Preview</button></div>
        </form>

        {previewError && <p role="alert" className="text-[13px] text-error">{previewError}</p>}
        {preview && !previewError && (
          <div className="mt-4">
            <p className="mb-2 text-[13px] font-semibold text-foreground">Preview result (pack: {preview.pack?.packId} v{preview.pack?.version})</p>
            {preview.blocked ? (
              <p className="text-[12px] text-error">Blocked: {preview.blockedKey} — {preview.blockedReason}</p>
            ) : (
              <>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-4 mb-4">
                  <dt className="text-foreground-muted">Gross</dt><dd>SAR {preview.result?.gross}</dd>
                  <dt className="text-foreground-muted">Total Deductions</dt><dd>SAR {preview.result?.totalDeductions}</dd>
                  <dt className="text-foreground-muted">Net Pay</dt><dd>SAR {preview.result?.netPay}</dd>
                  <dt className="text-foreground-muted">Worker Class</dt><dd>{preview.saudiArabia?.gosi?.workerClass || "—"}</dd>
                  <dt className="text-foreground-muted">Cohort</dt><dd>{preview.saudiArabia?.gosi?.cohort || "—"}</dd>
                  <dt className="text-foreground-muted">Emp. Pension</dt><dd>SAR {preview.saudiArabia?.gosi?.employeePension || "—"}</dd>
                  <dt className="text-foreground-muted">Er. Pension</dt><dd>SAR {preview.saudiArabia?.gosi?.employerPension || "—"}</dd>
                  <dt className="text-foreground-muted">Emp. SANED</dt><dd>SAR {preview.saudiArabia?.gosi?.employeeSocialSecurity || "—"}</dd>
                  <dt className="text-foreground-muted">Er. SANED</dt><dd>SAR {preview.saudiArabia?.gosi?.employerSocialSecurity || "—"}</dd>
                  <dt className="text-foreground-muted">Er. OH</dt><dd>SAR {preview.saudiArabia?.gosi?.employerOccupationalHazard || "—"}</dd>
                  <dt className="text-foreground-muted">Emp. Total</dt><dd>SAR {preview.saudiArabia?.gosi?.employeeTotal || "—"}</dd>
                  <dt className="text-foreground-muted">Er. Total</dt><dd>SAR {preview.saudiArabia?.gosi?.employerTotal || "—"}</dd>
                </dl>
                {preview.saudiArabia?.labour && (
                  <div className="mt-4 space-y-2">
                    <p className="text-[13px] font-semibold text-foreground">Labour reports</p>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] sm:grid-cols-3">
                      <dt className="text-foreground-muted">Deductions</dt><dd colSpan={2}><pre className="text-[10px] text-foreground-secondary">{JSON.stringify(preview.saudiArabia.labour.deductions || {}, null, 2)}</pre></dd>
                      <dt className="text-foreground-muted">Overtime</dt><dd colSpan={2}><pre className="text-[10px] text-foreground-secondary">{JSON.stringify(preview.saudiArabia.labour.overtime || {}, null, 2)}</pre></dd>
                      <dt className="text-foreground-muted">Hours Check</dt><dd colSpan={2}><pre className="text-[10px] text-foreground-secondary">{JSON.stringify(preview.saudiArabia.labour.hoursCheck || {}, null, 2)}</pre></dd>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}