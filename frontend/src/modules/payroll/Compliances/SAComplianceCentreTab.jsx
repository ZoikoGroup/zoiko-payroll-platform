import { useCallback, useEffect, useState } from "react";
import {
  getEmployees,
  getSaEmployerReadiness,
  getSaRunPreflight,
  getSaRunFingerprint,
  createSaCorrection,
  listSaCorrections,
  previewSaudiArabiaCalculation,
  listSaGosiLiabilities,
  buildSaGosiLiability,
  listSaEosLedger,
  accrueSaEos,
  listSaFinalSettlements,
  createSaFinalSettlement,
  approveSaFinalSettlement,
  paySaFinalSettlement,
  listSaWpsFiles,
  buildSaWpsFile,
  listSaWpsObservations,
  acceptSaWpsFile,
  rejectSaWpsFile,
} from "../../../service/payrollService";
import SAReadinessPanel, { useSaReadiness } from "./SAReadinessPanel";
import SAChecksList, { SAStatusLine } from "../../../components/jurisdiction/saudi_arabia/SAChecksList";

// Saudi Arabia Compliance Centre (ZP-SA-ENG-001 §13/§16/§17) — GOSI Registration
// workspace, GOSI Contributions preview, Labour Compliance (hours/overtime/
// deductions), Corrections, and informational Salaries Tax view. The server
// owns every rule (state machines, four-eyes approvals, deduction caps,
// hours/overtime reports); this tab only shows results and submits the
// operator's step.

const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "mb-1 block text-[12px] font-semibold text-foreground-secondary";
const btn = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60";
const btnGhost = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground";
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";

const SECTIONS = [
  "Readiness",
  "GOSI Registration",
  "GOSI Contributions Preview",
  "Labour Compliance",
  "Corrections",
  "GOSI Liability",
  "EOS Ledger",
  "Final Settlement",
  "WPS SIE Extract",
  "Salaries Tax (information)",
];

function useAction() {
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const run = useCallback(async (fn, ok) => {
    setError(null);
    setNotice(null);
    try {
      const out = await fn();
      if (ok) setNotice(ok);
      return out;
    } catch (err) {
      setError(err?.message || "The step was not accepted.");
      return null;
    }
  }, []);
  const messages = (
    <>
      {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
      {notice && <p role="status" className="text-[12px] font-medium text-success">{notice}</p>}
    </>
  );
  return { run, messages };
}

function Field({ id, text, children }) {
  return (
    <div>
      <label className={labelCls} htmlFor={id}>{text}</label>
      {children}
    </div>
  );
}

function EmployeeSelect({ id, employees, value, onChange }) {
  return (
    <select id={id} className={input} value={value} onChange={onChange}>
      <option value="">Select…</option>
      {employees.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employeeCode})</option>)}
    </select>
  );
}

function GOSIRegistration({ employees }) {
  const [profiles, setProfiles] = useState([]);
  const [form, setForm] = useState({ employeeId: "", workerClass: "SAUDI", cohort: "NEW", cohortEvidenceRef: "", contributoryWage: "" });
  const [step, setStep] = useState({});
  const { run, messages } = useAction();
  // `employees` comes from SAComplianceCentreTab (already SA-filtered); this
  // used to re-fetch them into a setEmployees that does not exist here.
  const load = useCallback(() => {
    getSaEmployerReadiness().then((r) => setProfiles(r?.profiles || [])).catch(() => setProfiles([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  const setS = (id, k) => (e) => setStep((s) => ({ ...s, [id]: { ...(s[id] || {}), [k]: e.target.value } }));
  const act = async (fn, ok) => { if (await run(fn, ok)) load(); };

  const CLASSES = ["SAUDI", "NON_SAUDI", "GCC", "DOMESTIC"];
  const COHORTS = ["NEW", "LEGACY"];

  return (
    <div className="space-y-4">
      <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-4`} aria-label="Register GOSI statutory profile"
        onSubmit={(e) => { e.preventDefault(); act(() => previewSaudiArabiaCalculation({
          jurisdictionPackId: null, payDate: new Date().toISOString().slice(0, 10), gross: Number(form.contributoryWage || 10000),
          basic: Number(form.contributoryWage || 10000), payFrequency: "Monthly",
          organizationId: null, employeeId: form.employeeId ? Number(form.employeeId) : null,
          workerClass: form.workerClass, cohort: form.cohort, cohortEvidenceRef: form.cohortEvidenceRef,
          contributoryWage: form.contributoryWage ? Number(form.contributoryWage) : null,
        }), "Statutory profile preview created."); }}>
        <Field id="sa-gosi-emp" text="Employee"><EmployeeSelect id="sa-gosi-emp" employees={employees} value={form.employeeId}
          onChange={(e) => setForm({ ...form, employeeId: e.target.value })} /></Field>
        <Field id="sa-gosi-class" text="Worker class"><select id="sa-gosi-class" className={input} value={form.workerClass}
          onChange={(e) => setForm({ ...form, workerClass: e.target.value })}>{CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}</select></Field>
        <Field id="sa-gosi-cohort" text="Cohort (pension system)"><select id="sa-gosi-cohort" className={input} value={form.cohort}
          onChange={(e) => setForm({ ...form, cohort: e.target.value })}>{COHORTS.map((c) => <option key={c} value={c}>{c}</option>)}</select></Field>
        <Field id="sa-gosi-evidence" text="Cohort evidence ref (required for SAUDI/GCC)"><input id="sa-gosi-evidence" className={input} value={form.cohortEvidenceRef} onChange={(e) => setForm({ ...form, cohortEvidenceRef: e.target.value })} /></Field>
        <Field id="sa-gosi-wage" text="Contributory wage (SAR)"><input id="sa-gosi-wage" inputMode="decimal" className={input} value={form.contributoryWage} onChange={(e) => setForm({ ...form, contributoryWage: e.target.value })} /></Field>
        <div className="flex items-end"><button type="submit" className={btn}>Preview GOSI calculation</button></div>
      </form>
      {messages}
      <p className="text-[11px] text-foreground-muted">NON_SAUDI and DOMESTIC workers are always LEGACY cohort (employer-only pension). SAUDI and GCC workers must have a cohort evidence reference.</p>
      {profiles.length > 0 && (
        <div className={card}>
          <p className="mb-2 text-[13px] font-semibold text-foreground">Existing statutory profiles</p>
          <table className="w-full">
            <thead><tr><th className={th}>Employee</th><th className={th}>Worker class</th><th className={th}>Cohort</th><th className={th}>Evidence</th><th className={th}>Contributory wage</th></tr></thead>
            <tbody>
              {profiles.map((p) => (
                <tr key={p.employeeId} className="border-t border-border">
                  <td className={td}>{p.employeeName} ({p.employeeCode})</td>
                  <td className={td}>{p.workerClass}</td>
                  <td className={td}>{p.cohort}</td>
                  <td className={td}>{p.cohortEvidenceRef || "—"}</td>
                  <td className={td}>SAR {p.contributoryWage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function GOSIContributionsPreview({ employees }) {
  const [form, setForm] = useState({ employeeId: "", gross: "10000", basic: "10000", payDate: new Date().toISOString().slice(0, 10), deductionOrders: [], overtimeHours: null, ramadan: false, workHoursRecords: [] });
  const [result, setResult] = useState(null);
  const { run, messages } = useAction();
  const setVal = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const act = async (fn, ok) => { const out = await run(fn, ok); if (ok && out) setResult(out); };

  return (
    <div className="space-y-4">
      <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-4`} aria-label="GOSI contributions preview"
        onSubmit={(e) => { e.preventDefault(); act(() => previewSaudiArabiaCalculation({
          jurisdictionPackId: null, payDate: form.payDate, gross: Number(form.gross), basic: Number(form.basic),
          payFrequency: "Monthly", organizationId: null, employeeId: form.employeeId ? Number(form.employeeId) : null,
          workerClass: "SAUDI", cohort: "NEW", cohortEvidenceRef: "preview",
          contributoryWage: Number(form.gross), deductionOrders: form.deductionOrders,
          overtimeHours: form.overtimeHours, ramadan: form.ramadan, workHoursRecords: form.workHoursRecords,
        }), "Preview calculated."); }}>
        <Field id="sa-gc-emp" text="Employee (optional)"><EmployeeSelect id="sa-gc-emp" employees={employees} value={form.employeeId}
          onChange={(e) => setForm({ ...form, employeeId: e.target.value })} /></Field>
        <Field id="sa-gc-gross" text="Gross (SAR)"><input id="sa-gc-gross" inputMode="decimal" className={input} value={form.gross} onChange={setVal("gross")} /></Field>
        <Field id="sa-gc-basic" text="Basic (SAR)"><input id="sa-gc-basic" inputMode="decimal" className={input} value={form.basic} onChange={setVal("basic")} /></Field>
        <Field id="sa-gc-date" text="Pay date"><input id="sa-gc-date" type="date" className={input} value={form.payDate} onChange={setVal("payDate")} /></Field>
        <Field id="sa-gc-ot" text="Overtime hours (report only)"><input id="sa-gc-ot" inputMode="decimal" className={input} value={form.overtimeHours || ""} onChange={setVal("overtimeHours")} /></Field>
        <Field id="sa-gc-ramadan" text="Ramadan"><input id="sa-gc-ramadan" type="checkbox" className="w-auto" checked={form.ramadan} onChange={(e) => setForm({ ...form, ramadan: e.target.checked })} /></Field>
        <div className="flex items-end"><button type="submit" className={btn}>Run preview</button></div>
      </form>
      {messages}
      {result && !result.blocked && (
        <div className={card}>
          <p className="mb-2 text-[13px] font-semibold text-foreground">Preview result (pack: {result.pack?.packId} v{result.pack?.version})</p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-4">
            <dt className="text-foreground-muted">Worker class</dt><dd>{result.saudiArabia?.gosi?.workerClass || "—"}</dd>
            <dt className="text-foreground-muted">Cohort</dt><dd>{result.saudiArabia?.gosi?.cohort || "—"}</dd>
            <dt className="text-foreground-muted">Employee pension</dt><dd>SAR {result.saudiArabia?.gosi?.employeePension || "—"}</dd>
            <dt className="text-foreground-muted">Employer pension</dt><dd>SAR {result.saudiArabia?.gosi?.employerPension || "—"}</dd>
            <dt className="text-foreground-muted">Employee SANED</dt><dd>SAR {result.saudiArabia?.gosi?.employeeSocialSecurity || "—"}</dd>
            <dt className="text-foreground-muted">Employer SANED</dt><dd>SAR {result.saudiArabia?.gosi?.employerSocialSecurity || "—"}</dd>
            <dt className="text-foreground-muted">Employer OH</dt><dd>SAR {result.saudiArabia?.gosi?.employerOccupationalHazard || "—"}</dd>
            <dt className="text-foreground-muted">Employee total</dt><dd>SAR {result.saudiArabia?.gosi?.employeeTotal || "—"}</dd>
            <dt className="text-foreground-muted">Employer total</dt><dd>SAR {result.saudiArabia?.gosi?.employerTotal || "—"}</dd>
          </dl>
          {result.saudiArabia?.labour && (
            <div className="mt-4 space-y-2">
              <p className="text-[13px] font-semibold text-foreground">Labour reports</p>
              <SAChecksList checks={[{ severity: "INFO", message: "Deductions: " + JSON.stringify(result.saudiArabia.labour.deductions || {}), source: "Art. 91/92" },
              { severity: "INFO", message: "Overtime: " + JSON.stringify(result.saudiArabia.labour.overtime || {}), source: "Art. 107" },
              { severity: "INFO", message: "Hours check: " + JSON.stringify(result.saudiArabia.labour.hoursCheck || {}), source: "Art. 98/104" }]} empty="" />
            </div>
          )}
        </div>
      )}
      {result && result.blocked && (
        <p className="text-[12px] text-error">Blocked: {result.blockedKey} — {result.blockedReason}</p>
      )}
    </div>
  );
}

function LabourCompliance({ employees }) {
  // This section shows the run preflight findings for the latest SA run
  // and allows the operator to review hours/overtime/deduction reports.
  const [runs, setRuns] = useState([]);
  const [preflight, setPreflight] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const { run, messages } = useAction();
  const act = async (fn, ok) => { if (await run(fn, ok)) setSelectedRun(selectedRun); };

  useEffect(() => {
    getSaEmployerReadiness().then((r) => setRuns(r?.recentRuns || [])).catch(() => setRuns([]));
  }, []);

  const loadPreflight = useCallback(async (runId) => {
    const out = await getSaRunPreflight(runId);
    setPreflight(out);
    setSelectedRun(runId);
  }, []);

  return (
    <div className="space-y-4">
      <div className={`${card} flex flex-wrap items-end gap-3`}>
        <Field id="sa-lc-run" text="Payroll run"><select id="sa-lc-run" className={input} value={selectedRun || ""}
          onChange={(e) => loadPreflight(e.target.value)}><option value="">Select run…</option>{runs.map((r) => <option key={r.id} value={r.id}>{r.periodLabel} · {r.payDate}</option>)}</select></Field>
        <p className="text-[11px] text-foreground-muted">Select a run to view its labour preflight.</p>
      </div>
      {messages}
      {preflight && (
        <div className="space-y-3">
          <p className="text-[12px] text-foreground-muted">{preflight.pack || "no Active pack"} · pay date {preflight.payDate || "—"} · <SAStatusLine data={preflight} /></p>
          {preflight.status === "BLOCKED" && <p className="text-[12px] text-error">Approval is refused until every BLOCK item is resolved.</p>}
          <SAChecksList checks={preflight.checks} empty="No labour findings." />
        </div>
      )}
    </div>
  );
}

function Corrections({ employees }) {
  const [rows, setRows] = useState([]);
  const [issued, setIssued] = useState({});
  const { run, messages } = useAction();
  const act = async (fn, ok) => { const out = await run(fn, ok); if (out) { setRows((prev) => prev.map((r) => r.id === out.payslipId ? out : r)); } };

  useEffect(() => {
    listSaCorrections().then((res) => {
      const data = Array.isArray(res) ? res : res?.data || res?.items || [];
      setRows(data.filter((r) => (r.countryCode || "").toUpperCase() === "SA"));
    }).catch(() => setRows([]));
  }, []);

  return (
    <div className="space-y-4">
      {messages}
      {!rows.length ? (
        <p className="text-[12px] text-foreground-muted">No Saudi Arabia correction chain found.</p>
      ) : (
        <table className="w-full">
          <thead><tr><th className={th}>Payslip</th><th className={th}>Run</th><th className={th}>Deltas</th><th className={th}>Totals (all)</th><th className={th}>Created</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.payslipId} className="border-t border-border">
                <td className={td}>{r.payslipId}</td>
                <td className={td}>{r.runId}</td>
                <td className={td}><pre className="text-[11px] text-foreground-secondary">{JSON.stringify(r.deltas, null, 2)}</pre></td>
                <td className={td}><pre className="text-[11px] text-foreground-secondary">{JSON.stringify(r.totalsAll, null, 2)}</pre></td>
                <td className={td}>{r.createdAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SalariesTaxInfo() {
  const [out, setOut] = useState(null);
  const { run, messages } = useAction();
  return (
    <div className="space-y-3">
      <p className="text-[12px] text-foreground-secondary">
        Informational only — Saudi Arabia has no monthly income-tax withholding (no PAYE). Income tax for the few Saudi/GCC nationals
        it applies to is assessed separately outside the monthly payroll engine. GOSI contributions (pension, SANED, occupational
        hazards) are the only monthly statutory deductions.
      </p>
      <button type="button" className={btn} onClick={() => setOut({ label: "No withholding", estimatedTax: "0.00", basisApplied: "N/A" })}>Show estimate (always zero)</button>
      {messages}
      {out && <p className="text-[13px] text-foreground">{out.label}: SAR {out.estimatedTax} ({out.basisApplied})</p>}
    </div>
  );
}

function GOSILiability() {
  const [rows, setRows] = useState([]);
  const [runId, setRunId] = useState("");
  const { run, messages } = useAction();

  const load = useCallback(() => {
    listSaGosiLiabilities().then((r) => setRows(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setRows([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const build = async () => {
    if (await run(() => buildSaGosiLiability(Number(runId)), "GOSI liability built.")) load();
  };

  return (
    <div className="space-y-4">
      {messages}
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">GOSI Monthly Liability</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">Employer GOSI liability per contribution month (pension, SANED, occupational hazards), built from a payroll run.</p>
        <table className="w-full">
          <thead><tr>{["Month", "Pension (Emp.)", "Pension (Er.)", "SANED (Emp.)", "SANED (Er.)", "Occ. Hazard (Er.)", "Total Due", "Status", "Source Run", "Paid Ref"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={10} className={td}>No GOSI liabilities yet.</td></tr>}
            {rows.map((g) => (
              <tr key={g.id} className="border-t border-border">
                <td className={td}>{g.contributionMonth ? new Date(g.contributionMonth).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "—"}</td>
                <td className={td}>SAR {g.pensionEmployee ?? "—"}</td>
                <td className={td}>SAR {g.pensionEmployer ?? "—"}</td>
                <td className={td}>SAR {g.sanedEmployee ?? "—"}</td>
                <td className={td}>SAR {g.sanedEmployer ?? "—"}</td>
                <td className={td}>SAR {g.occupationalHazardEmployer ?? "—"}</td>
                <td className={td}>SAR {g.totalDue ?? "—"}</td>
                <td className={td}>{g.status || "—"}</td>
                <td className={td}>{g.sourceRunId ?? "—"}</td>
                <td className={td}>{g.paymentReference || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex items-end gap-2">
          <input placeholder="Run ID" aria-label="Run ID" className={input} value={runId} onChange={(e) => setRunId(e.target.value)} style={{ width: "100px" }} />
          <button type="button" className={btn} disabled={!runId} onClick={build}>Build from Run</button>
        </div>
      </div>
    </div>
  );
}

function EOSLedger({ employees }) {
  const [ledger, setLedger] = useState([]);
  const [accrueRunId, setAccrueRunId] = useState("");
  const { run, messages } = useAction();
  const act = (fn, ok) => run(fn, ok);

  useEffect(() => {
    listSaEosLedger().then((r) => setLedger(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setLedger([]));
  }, []);

  const accrue = async () => {
    await act(() => accrueSaEos(Number(accrueRunId)), "EOS accrued.");
    listSaEosLedger().then((r) => setLedger(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setLedger([]));
  };

  return (
    <div className="space-y-4">
      {messages}
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">EOS Accrual Ledger (SA-020/SA-021)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">Incremental EOS accrual per payroll run. Resignation fractions applied at final settlement.</p>
        <table className="w-full">
          <thead><tr>{["Employee", "Period From", "Period To", "Service Years", "Monthly Base", "Award Months", "Status", "Source Run"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody>
            {ledger.length === 0 && <tr><td colSpan={8} className={td}>No EOS ledger entries yet.</td></tr>}
            {ledger.map((e) => (
              <tr key={e.id} className="border-t border-border">
                <td className={td}>{e.employeeName || e.employeeId}</td>
                <td className={td}>{e.periodFrom ? new Date(e.periodFrom).toLocaleDateString() : "—"}</td>
                <td className={td}>{e.periodTo ? new Date(e.periodTo).toLocaleDateString() : "—"}</td>
                <td className={td}>{e.serviceYears?.toFixed(2) ?? "—"}</td>
                <td className={td}>SAR {e.monthlyBase ?? "—"}</td>
                <td className={td}>{e.accrualMonths ?? "—"}</td>
                <td className={td}>{e.status || "—"}</td>
                <td className={td}>{e.sourceRunId ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex items-end gap-2">
          <input placeholder="Run ID" className={input} value={accrueRunId} onChange={(e) => setAccrueRunId(e.target.value)} style={{ width: "100px" }} />
          <button className={btn} disabled={!accrueRunId} onClick={() => accrue()}>Accrue from Run</button>
        </div>
      </div>
    </div>
  );
}

function FinalSettlement({ employees }) {
  const [settlements, setSettlements] = useState([]);
  const [form, setForm] = useState({ employeeId: "", terminationType: "TERMINATION", terminationDate: new Date().toISOString().slice(0, 10), noticeDays: 0, unusedLeaveDays: 0, repatriationAmount: 0, otherDues: 0 });
  const { run, messages } = useAction();
  const act = (fn, ok) => run(fn, ok);

  useEffect(() => {
    listSaFinalSettlements().then((r) => setSettlements(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setSettlements([]));
  }, []);

  const create = async () => {
    await act(() => createSaFinalSettlement(form), "Draft settlement created.");
    listSaFinalSettlements().then((r) => setSettlements(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setSettlements([]));
  };

  const approve = async (id) => {
    await act(() => approveSaFinalSettlement(id), "Settlement approved.");
    listSaFinalSettlements().then((r) => setSettlements(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setSettlements([]));
  };

  const pay = async (id) => {
    const ref = window.prompt("Payment reference");
    if (ref) {
      await act(() => paySaFinalSettlement(id, ref), "Settlement paid.");
      listSaFinalSettlements().then((r) => setSettlements(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setSettlements([]));
    }
  };

  return (
    <div className="space-y-4">
      {messages}
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Final Settlement (SA-026/SA-027)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">EOS award (Art. 84/85/87) plus leave/notice/repatriation dues. Four-eyes: approve then pay.</p>
        <table className="w-full">
          <thead><tr>{["Employee", "Type", "Date", "EOS Award", "Notice Pay", "Leave Pay", "Repatriation", "Other", "Total", "Status", "Approved By", "Paid Ref", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody>
            {settlements.length === 0 && <tr><td colSpan={13} className={td}>No final settlements yet.</td></tr>}
            {settlements.map((s) => (
              <tr key={s.id} className="border-t border-border">
                <td className={td}>{s.employeeName || s.employeeId}</td>
                <td className={td}>{s.terminationType || "—"}</td>
                <td className={td}>{s.terminationDate ? new Date(s.terminationDate).toLocaleDateString() : "—"}</td>
                <td className={td}>SAR {s.eosAward ?? "—"}</td>
                <td className={td}>SAR {s.noticePay ?? "—"}</td>
                <td className={td}>SAR {s.leavePay ?? "—"}</td>
                <td className={td}>SAR {s.repatriationPay ?? "—"}</td>
                <td className={td}>SAR {s.otherDues ?? "—"}</td>
                <td className={td}>SAR {s.totalAmount ?? "—"}</td>
                <td className={td}>{s.status || "—"}</td>
                <td className={td}>{s.approvedById ?? "—"}</td>
                <td className={td}>{s.paymentReference || "—"}</td>
                <td className={td}>
                  {s.status === "DRAFT" && <button className={btn} onClick={() => approve(s.id)}>Approve</button>}
                  {s.status === "APPROVED" && <button className={btn} onClick={() => pay(s.id)}>Pay</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <input placeholder="Employee ID" className={input} value={form.employeeId} onChange={(e) => setForm({ ...form, employeeId: e.target.value })} style={{ width: "100px" }} />
          <select className={input} value={form.terminationType} onChange={(e) => setForm({ ...form, terminationType: e.target.value })}><option value="TERMINATION">TERMINATION</option><option value="RESIGNATION">RESIGNATION</option></select>
          <input type="date" className={input} value={form.terminationDate} onChange={(e) => setForm({ ...form, terminationDate: e.target.value })} style={{ width: "140px" }} />
          <input placeholder="Notice Days" className={input} value={form.noticeDays} onChange={(e) => setForm({ ...form, noticeDays: Number(e.target.value) })} style={{ width: "100px" }} />
          <input placeholder="Leave Days" className={input} value={form.unusedLeaveDays} onChange={(e) => setForm({ ...form, unusedLeaveDays: Number(e.target.value) })} style={{ width: "100px" }} />
          <input placeholder="Repatriation" className={input} value={form.repatriationAmount} onChange={(e) => setForm({ ...form, repatriationAmount: e.target.value })} style={{ width: "120px" }} />
          <button className={btn} disabled={!form.employeeId || !form.terminationDate} onClick={create}>Create Draft</button>
        </div>
      </div>
    </div>
  );
}

function WPSSection({ employees }) {
  const [files, setFiles] = useState([]);
  const [buildRunId, setBuildRunId] = useState("");
  const [obsFileId, setObsFileId] = useState("");
  const [obs, setObs] = useState([]);
  const { run, messages } = useAction();
  const act = (fn, ok) => run(fn, ok);

  useEffect(() => {
    listSaWpsFiles().then((r) => setFiles(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setFiles([]));
  }, []);

  const build = async () => {
    await act(() => buildSaWpsFile(Number(buildRunId)), "WPS file built.");
    listSaWpsFiles().then((r) => setFiles(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setFiles([]));
  };

  const viewObs = async (id) => {
    setObsFileId(id);
    const o = await listSaWpsObservations(id);
    setObs(Array.isArray(o) ? o : o?.data || o?.items || []);
  };

  const accept = async (id) => {
    await act(() => acceptSaWpsFile(id), "Accepted.");
    listSaWpsFiles().then((r) => setFiles(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setFiles([]));
  };

  const reject = async (id) => {
    const reason = window.prompt("Rejection reason");
    if (reason) {
      await act(() => rejectSaWpsFile(id, reason), "Rejected.");
      listSaWpsFiles().then((r) => setFiles(Array.isArray(r) ? r : r?.data || r?.items || [])).catch(() => setFiles([]));
    }
  };

  return (
    <div className="space-y-4">
      {messages}
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">WPS SIE Extract (SA-025)</h3>
        <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">Salary Information Extract for Mudad. Content-addressed (SHA-256), tracked UPLOADED → ACCEPTED/REJECTED.</p>
        <table className="w-full">
          <thead><tr>{["Run", "Month", "SHA-256", "Employees", "Total Net", "Status", "Observations", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody>
            {files.length === 0 && <tr><td colSpan={8} className={td}>No WPS files yet.</td></tr>}
            {files.map((f) => (
              <tr key={f.id} className="border-t border-border">
                <td className={td}>{f.sourceRunId ?? "—"}</td>
                <td className={td}>{f.periodMonth ? new Date(f.periodMonth).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "—"}</td>
                <td className={td}><code className="text-[10px] font-mono">{f.fileSha256 ? f.fileSha256.slice(0, 16) + "…" : "—"}</code></td>
                <td className={td}>{f.employeeCount ?? "—"}</td>
                <td className={td}>SAR {f.totalAmount ?? "—"}</td>
                <td className={td}>{f.status || "—"}</td>
                <td className={td}>{f.observationCount ?? 0}</td>
                <td className={td}>
                  {f.status === "UPLOADED" && (
                    <>
                      <button className={btn} onClick={() => accept(f.id)}>Accept</button>
                      <button className={btn} onClick={() => reject(f.id)}>Reject</button>
                    </>
                  )}
                  <button className={btn} onClick={() => viewObs(f.id)}>View Obs</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex items-end gap-2">
          <input placeholder="Run ID" className={input} value={buildRunId} onChange={(e) => setBuildRunId(e.target.value)} style={{ width: "100px" }} />
          <button className={btn} disabled={!buildRunId} onClick={() => build()}>Build from Run</button>
        </div>
      </div>

      {obsFileId && (
        <div className={card}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-[14px] font-semibold text-foreground">Observations for file #{obsFileId}</h3>
            <button className={btn} onClick={() => setObsFileId("")}>Close</button>
          </div>
          {obs.length === 0 ? <p className="text-[12px] text-foreground-muted">No observations.</p> : (
            <table className="w-full">
              <thead><tr>{["Code", "Employee", "Field", "Value", "Severity"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>{obs.map((o) => (
                <tr key={o.id} className="border-t border-border">
                  <td className={td}>{o.observationCode || o.code}</td>
                  <td className={td}>{o.employeeName || o.employeeId}</td>
                  <td className={td}>{o.field}</td>
                  <td className={td}>{o.value}</td>
                  <td className={td}><span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${o.severity === "ERROR" ? "bg-error/10 text-error" : "bg-warning/10 text-warning"}`}>{o.severity || "—"}</span></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export default function SAComplianceCentreTab() {
  const [section, setSection] = useState(0);
  const [employees, setEmployees] = useState([]);
  useEffect(() => {
    getEmployees().then((res) => {
      const rows = Array.isArray(res) ? res : res?.data || res?.items || [];
      setEmployees(rows.filter((e) => (e.countryCode || "").toUpperCase() === "SA"));
    }).catch(() => setEmployees([]));
  }, []);

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Saudi Arabia compliance workspaces" className="flex flex-wrap gap-2">
        {SECTIONS.map((s, i) => (
          <button key={s} role="tab" aria-selected={section === i} type="button" onClick={() => setSection(i)}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold ${section === i ? "bg-primary text-white" : "border border-border text-foreground"}`}>
            {s}
          </button>
        ))}
      </div>
      {section === 0 && <SAReadinessPanel />}
      {section === 1 && <GOSIRegistration employees={employees} />}
      {section === 2 && <GOSIContributionsPreview employees={employees} />}
      {section === 3 && <LabourCompliance employees={employees} />}
      {section === 4 && <Corrections employees={employees} />}
      {section === 5 && <GOSILiability employees={employees} />}
      {section === 6 && <EOSLedger employees={employees} />}
      {section === 7 && <FinalSettlement employees={employees} />}
      {section === 8 && <WPSSection employees={employees} />}
      {section === 9 && <SalariesTaxInfo />}
    </div>
  );
}