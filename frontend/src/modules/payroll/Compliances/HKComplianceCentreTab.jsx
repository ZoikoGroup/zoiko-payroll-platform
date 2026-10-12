import { useCallback, useEffect, useState } from "react";
import {
  amendHkIrdCase, approveHkHoldRelease, approveHkTermination, calculateHkTermination, changeHkDeparture, closeHkHold,
  estimateHkSalariesTax, generateHkAnnualReturn, getEmployees, identifyHkDeparture, listHkEmpfSubmissions,
  listHkIrdCases, listHkTaxClearanceCases, prepareHkEmpfSubmission, recordHkIr56gFiled, requestHkHoldRelease,
  transitionHkEmpfSubmission, transitionHkIrdCase, getApplicableReportTemplate, generateHkBir56a, generateHkIr56b,
  generateHkIr56Notification, recordHkEmployeeCopy, downloadReportCertificate, generateHkTerminationStatement,
  getHkEmployerReadiness, listHkTerminationResults, getHkIrdCaseHistory,
} from "../../../service/payrollService";
import HKReadinessPanel from "./HKReadinessPanel";
import HKCorrectionsPanel from "./HKCorrectionsPanel";
import HKPrivacyPanel from "./HKPrivacyPanel";
import { hkLabel } from "../../../components/jurisdiction/hong_kong/hkLabels";

// Hong Kong Compliance Centre (ZP-HK-ENG-001 §14) — Tax Clearance workspace,
// IRD Reporting centre, eMPF centre, Termination calculator and the
// informational Salaries Tax view. The server owns every rule (state
// machines, four-eyes approvals, held amounts, bank-file exclusion, caps);
// this tab only shows results and submits the operator's step.
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "mb-1 block text-[12px] font-semibold text-foreground-secondary";
const btn = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60";
const btnGhost = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground";
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const SECTIONS = ["Readiness", "Tax Clearance (IR56G)", "IRD Reporting", "eMPF", "Termination Calculator", "Corrections",
  "Privacy & Legal Holds", "Salaries Tax (information)"];

// Days until a date (negative once it has passed) — for the contribution-day countdown.
function daysUntil(iso) {
  if (!iso) return null;
  const today = new Date(new Date().toISOString().slice(0, 10));
  return Math.round((new Date(iso) - today) / 86400000);
}

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

function TaxClearance({ employees }) {
  const [cases, setCases] = useState([]);
  const [form, setForm] = useState({ employeeId: "", expectedDepartureDate: "" });
  const [step, setStep] = useState({});
  const { run, messages } = useAction();
  const load = useCallback(() => listHkTaxClearanceCases().then(setCases).catch(() => setCases([])), []);
  useEffect(() => { load(); }, [load]);
  const setS = (id, k) => (e) => setStep((s) => ({ ...s, [id]: { ...(s[id] || {}), [k]: e.target.value } }));
  const act = async (fn, ok) => { if (await run(fn, ok)) load(); };

  return (
    <div className="space-y-4">
      <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-3`} aria-label="Identify a departure"
        onSubmit={(e) => { e.preventDefault(); act(() => identifyHkDeparture({ ...form, employeeId: Number(form.employeeId) }), "Departure recorded — IR56G deadline created."); }}>
        <Field id="hk-dep-emp" text="Employee"><EmployeeSelect id="hk-dep-emp" employees={employees} value={form.employeeId}
          onChange={(e) => setForm({ ...form, employeeId: e.target.value })} /></Field>
        <Field id="hk-dep-date" text="Expected departure date"><input id="hk-dep-date" type="date" className={input}
          value={form.expectedDepartureDate} onChange={(e) => setForm({ ...form, expectedDepartureDate: e.target.value })} /></Field>
        <div className="flex items-end"><button type="submit" className={btn}>Identify departure</button></div>
      </form>
      {messages}
      <table className="w-full">
        <thead><tr><th className={th}>Employee</th><th className={th}>State</th><th className={th}>Departure / deadline</th><th className={th}>Held</th><th className={th}>Next step</th></tr></thead>
        <tbody>
          {cases.map((c) => {
            const s = step[c.id] || {};
            const name = employees.find((e) => e.id === c.employeeId)?.name || `#${c.employeeId}`;
            return (
              <tr key={c.id} className="border-t border-border">
                <td className={td}>{name}</td>
                <td className={td}>{hkLabel(c.state)}<div className="text-[11px] text-foreground-muted">{String(c.treatment || "").replace("LEGAL_HOLD", "Legal hold")}</div></td>
                <td className={td}>{c.expectedDepartureDate} · file by {c.filingDeadline}{c.statutoryHoldExpiry ? ` · 1-month period ends ${c.statutoryHoldExpiry}` : ""}</td>
                <td className={td}>HK$ {c.heldTotal} ({c.lines.length} payslip(s))</td>
                <td className={`${td} space-y-1`}>
                  {["DEPARTURE_IDENTIFIED", "IR56G_DUE"].includes(c.state) && (
                    <div className="flex flex-wrap gap-1">
                      <input aria-label="IR56G filed on" type="date" className={input} onChange={setS(c.id, "filedOn")} />
                      <input aria-label="IR56G filing reference" placeholder="Filing reference" className={input} onChange={setS(c.id, "filingReference")} />
                      <button type="button" className={btn} onClick={() => act(() => recordHkIr56gFiled(c.id, { filedOn: s.filedOn, filingReference: s.filingReference }), "IR56G filed — hold active.")}>Record filing</button>
                    </div>
                  )}
                  {["IR56G_FILED_HOLD_ACTIVE", "DEPARTURE_CANCELLED_OR_CHANGED"].includes(c.state) && (
                    <div className="flex flex-wrap gap-1">
                      <select aria-label="Release basis" className={input} onChange={setS(c.id, "basis")} defaultValue="">
                        <option value="">Release basis…</option><option value="LETTER_OF_RELEASE">{hkLabel("LETTER_OF_RELEASE")}</option>
                        <option value="STATUTORY_PERIOD_ELAPSED">One month from filing elapsed</option>
                      </select>
                      <input aria-label="Letter of release reference" placeholder="Letter reference" className={input} onChange={setS(c.id, "reference")} />
                      <input aria-label="Release evidence reference" placeholder="Evidence reference" className={input} onChange={setS(c.id, "evidenceRef")} />
                      <button type="button" className={btnGhost} onClick={() => act(() => requestHkHoldRelease(c.id, { basis: s.basis, reference: s.reference || null, evidenceRef: s.evidenceRef }), "Release requested — a different operator must approve it.")}>Request release</button>
                      <button type="button" className={btn} onClick={() => act(() => approveHkHoldRelease(c.id), "Released.")}>Approve release</button>
                      <input aria-label="Change reason" placeholder="Departure changed — reason" className={input} onChange={setS(c.id, "reason")} />
                      <button type="button" className={btnGhost} onClick={() => act(() => changeHkDeparture(c.id, { reason: s.reason, evidenceRef: s.evidenceRef }), "Recorded — the hold continues until a release is approved.")}>Departure changed</button>
                    </div>
                  )}
                  {["LETTER_OF_RELEASE_RECEIVED", "DEPARTURE_CANCELLED_OR_CHANGED"].includes(c.state) && (
                    <button type="button" className={btnGhost} onClick={() => act(() => closeHkHold(c.id), "Case closed.")}>Close case</button>
                  )}
                </td>
              </tr>
            );
          })}
          {!cases.length && <tr><td className={td} colSpan={5}>No IR56G cases.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function IrdReporting() {
  const [ya, setYa] = useState("2025/26");
  const [cases, setCases] = useState([]);
  const [refs, setRefs] = useState({});
  const [rejections, setRejections] = useState({});
  // FILED needs the external-submission record (how the employer submitted).
  const [subs, setSubs] = useState({});
  const sub = (id) => subs[id] || { submissionMode: "INTERNAL_PREPARATION_ONLY" };
  const setSub = (id, patch) => setSubs({ ...subs, [id]: { ...sub(id), ...patch } });
  const [history, setHistory] = useState({});
  const [summary, setSummary] = useState(null);
  const { run, messages } = useAction();
  const load = useCallback(() => listHkIrdCases().then(setCases).catch(() => setCases([])), []);
  useEffect(() => { load(); }, [load]);
  const act = async (fn, ok) => { const out = await run(fn, ok); if (out) load(); return out; };
  const NEXT = { PREPARED: "VALIDATED", VALIDATED: "FILED", FILED: "ACCEPTED" };
  const COPY_FORMS = ["IR56B", "IR56E", "IR56F", "IR56G"];
  const PER_EMPLOYEE_FORMS = COPY_FORMS;

  // Renders the case on the Active report template for its form and year
  // (GeneratedReport). The server refuses a missing / non-Active template.
  async function generateForm(c) {
    const reportType = `HK_${c.formType}`;
    const resolved = await run(() => getApplicableReportTemplate({ reportingYear: c.yearOfAssessment, reportType }));
    const templateId = resolved?.template?.id;
    if (!resolved) return;
    if (!templateId) {
      await run(() => Promise.reject(new Error(`No Active ${reportType} report template is published for ${c.yearOfAssessment}.`)));
      return;
    }
    const call = c.formType === "BIR56A" ? () => generateHkBir56a(templateId, c.yearOfAssessment)
      : c.formType === "IR56B" ? () => generateHkIr56b(templateId, c.employeeId, c.yearOfAssessment)
        : () => generateHkIr56Notification(templateId, c.id);
    await act(call, `${c.formType} rendered on template ${resolved.template.version || templateId}.`);
  }

  return (
    <div className="space-y-4">
      <div className={`${card} flex flex-wrap items-end gap-3`}>
        <Field id="hk-ya" text="Year of assessment (ends 31 March)"><input id="hk-ya" className={input} value={ya} onChange={(e) => setYa(e.target.value)} /></Field>
        <button type="button" className={btn} onClick={async () => setSummary(await act(() => generateHkAnnualReturn(ya), "BIR56A / IR56B prepared from committed payroll."))}>
          Prepare BIR56A + IR56B
        </button>
        <p className="text-[11px] text-foreground-muted">Internal payload only — the IRD XML schemas are not archived (release gate G2); file through the IRD&apos;s own channel and record the reference here.</p>
      </div>
      {messages}
      {summary && <p className="text-[12px] text-foreground-secondary">Reported HK$ {summary.reportedTotal} · committed payroll HK$ {summary.committedPayrollGross}</p>}
      <table className="w-full">
        <thead><tr><th className={th}>Form</th><th className={th}>YA</th><th className={th}>Employee</th><th className={th}>Due</th><th className={th}>Status</th><th className={th}>Data file</th><th className={th}>Issues</th><th className={th}>Action</th></tr></thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id} className="border-t border-border">
              <td className={td}>{c.formType}{c.amendmentType && c.amendmentType !== "ORIGINAL" ? ` · ${c.amendmentType.toLowerCase()}` : ""}{c.amendsCaseId ? ` (amends #${c.amendsCaseId})` : ""}</td>
              <td className={td}>{c.yearOfAssessment}</td><td className={td}>{c.employeeId ?? "—"}</td>
              <td className={td}>{c.dueDate}</td><td className={td}>{hkLabel(c.status)}</td>
              <td className={td}>{hkLabel(c.xmlLifecycleState)}{c.submissionMode ? <div className="text-[10px] text-foreground-muted">{hkLabel(c.submissionMode)} · signed by {c.authorizedSigner}{c.transactionReference ? ` · eTAX ${c.transactionReference}` : ""}{c.controlListReference ? ` · control list ${c.controlListReference}` : ""}</div> : null}</td>
              <td className={td}>{[...(c.validationErrors || []), c.suppressionReason].filter(Boolean).join("; ") || "—"}</td>
              <td className={`${td} space-y-1`}>
                {c.status === "FILED" && (
                  <div className="flex flex-wrap gap-1">
                    <input aria-label={`Rejection reference for case ${c.id}`} placeholder="IRD rejection reference / reason"
                      className={input} onChange={(e) => setRejections({ ...rejections, [c.id]: e.target.value })} />
                    <button type="button" className={btnGhost} onClick={() => act(() => transitionHkIrdCase(c.id, {
                      target: "REJECTED", receiptReference: rejections[c.id],
                    }), "IRD rejection recorded — the filed evidence is kept; prepare the return again.")}>Record IRD rejection</button>
                  </div>
                )}
                {c.status === "REJECTED" && (
                  <button type="button" className={btn} onClick={() => act(() => transitionHkIrdCase(c.id, { target: "PREPARED" }),
                    "Case prepared again — correct, validate and re-file it.")}>Prepare again</button>
                )}
                {NEXT[c.status] && (
                  <div className="flex flex-wrap gap-1">
                    {NEXT[c.status] === "FILED" && (
                      <>
                        <select aria-label={`Submission mode for case ${c.id}`} className={input} value={sub(c.id).submissionMode}
                          onChange={(e) => setSub(c.id, { submissionMode: e.target.value })}>
                          <option value="INTERNAL_PREPARATION_ONLY">{hkLabel("INTERNAL_PREPARATION_ONLY")}</option>
                          <option value="ONLINE_MODE">{hkLabel("ONLINE_MODE")}</option>
                          <option value="MIXED_MODE">{hkLabel("MIXED_MODE")}</option>
                        </select>
                        <input aria-label={`Authorized signer for case ${c.id}`} placeholder="Authorized signer" className={input}
                          onChange={(e) => setSub(c.id, { authorizedSigner: e.target.value })} />
                        {sub(c.id).submissionMode === "ONLINE_MODE" && (
                          <input aria-label={`eTAX transaction reference for case ${c.id}`} placeholder="eTAX transaction reference" className={input}
                            onChange={(e) => setSub(c.id, { transactionReference: e.target.value })} />
                        )}
                        {sub(c.id).submissionMode === "MIXED_MODE" && (
                          <input aria-label={`Control list reference for case ${c.id}`} placeholder="Signed control list reference" className={input}
                            onChange={(e) => setSub(c.id, { controlListReference: e.target.value })} />
                        )}
                        <input type="date" aria-label={`Submission date for case ${c.id}`} className={input}
                          onChange={(e) => setSub(c.id, { submittedOn: e.target.value || undefined })} />
                      </>
                    )}
                    {NEXT[c.status] !== "VALIDATED" && (
                      <input aria-label={`Reference for case ${c.id}`} placeholder={NEXT[c.status] === "FILED" ? "IRD filing reference" : "IRD acknowledgement"}
                        className={input} onChange={(e) => setRefs({ ...refs, [c.id]: e.target.value })} />
                    )}
                    <button type="button" className={btn} onClick={() => act(() => transitionHkIrdCase(c.id, {
                      target: NEXT[c.status],
                      filingReference: NEXT[c.status] === "FILED" ? refs[c.id] : undefined,
                      ...(NEXT[c.status] === "FILED" ? sub(c.id) : {}),
                      receiptReference: NEXT[c.status] === "ACCEPTED" ? refs[c.id] : undefined,
                    }), `Case ${hkLabel(NEXT[c.status]).toLowerCase()}.`)}>Mark {hkLabel(NEXT[c.status]).toLowerCase()}</button>
                  </div>
                )}
                {!["SUPPRESSED", "CANCELLED"].includes(c.status) && (
                  <div className="flex flex-wrap gap-1">
                    <button type="button" className={btnGhost} onClick={() => generateForm(c)}>
                      {c.generatedReportId ? "Re-render form" : "Render form"}
                    </button>
                    {c.generatedReportId && PER_EMPLOYEE_FORMS.includes(c.formType) && c.employeeId && (
                      <button type="button" className={btnGhost}
                        onClick={() => run(() => downloadReportCertificate(c.generatedReportId, c.employeeId, `${c.formType}-${c.employeeId}`))}>
                        Download {c.formType}
                      </button>
                    )}
                  </div>
                )}
                {COPY_FORMS.includes(c.formType) && !["DUE", "SUPPRESSED", "CANCELLED"].includes(c.status) && (
                  c.employeeCopyDeliveredAt ? (
                    <p className="text-[11px] text-foreground-muted">Employee copy delivered {c.employeeCopyDeliveredAt.slice(0, 10)}</p>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      <input aria-label={`Employee copy evidence for case ${c.id}`} placeholder="How / when the copy was given"
                        className={input} onChange={(e) => setRefs({ ...refs, [`copy-${c.id}`]: e.target.value })} />
                      <button type="button" className={btnGhost}
                        onClick={() => act(() => recordHkEmployeeCopy(c.id, refs[`copy-${c.id}`] || ""), "Employee copy delivery recorded.")}>
                        Record employee copy
                      </button>
                    </div>
                  )
                )}
                {["FILED", "ACCEPTED", "ACKNOWLEDGED"].includes(c.status) && (
                  <button type="button" className={btnGhost} onClick={() => {
                    const reason = window.prompt("Reason for the amendment");
                    if (reason) act(() => amendHkIrdCase(c.id, reason), "Amendment case created — the filed evidence is unchanged.");
                  }}>Amend</button>
                )}
                <button type="button" className={btnGhost} aria-expanded={Boolean(history[c.id])}
                  onClick={async () => {
                    if (history[c.id]) { setHistory({ ...history, [c.id]: null }); return; }
                    const rows = await run(() => getHkIrdCaseHistory(c.id));
                    if (rows) setHistory({ ...history, [c.id]: rows });
                  }}>
                  {history[c.id] ? "Hide filing history" : "Filing history"}
                </button>
                {history[c.id] && (
                  <ol aria-label={`Filing history for case ${c.id}`} className="text-[11px] text-foreground-secondary list-decimal pl-4">
                    {history[c.id].filter((h) => h.to).map((h, i) => (
                      <li key={i}>
                        {(h.at || "").slice(0, 10)} — {hkLabel(h.from)} → {hkLabel(h.to)}
                        {h.filingReference ? ` · filing ${h.filingReference}` : ""}
                        {h.reference ? ` · reference ${h.reference}` : ""}
                        {h.filedEvidence ? " · filed evidence retained" : ""}
                      </li>
                    ))}
                  </ol>
                )}
              </td>
            </tr>
          ))}
          {!cases.length && <tr><td className={td} colSpan={7}>No IRD cases.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function Empf() {
  const [period, setPeriod] = useState("");
  const [subs, setSubs] = useState([]);
  const [ref, setRef] = useState({});
  const { run, messages } = useAction();
  const load = useCallback(() => listHkEmpfSubmissions().then(setSubs).catch(() => setSubs([])), []);
  useEffect(() => { load(); }, [load]);
  const act = async (fn, ok) => { if (await run(fn, ok)) load(); };

  return (
    <div className="space-y-4">
      <div className={`${card} flex flex-wrap items-end gap-3`}>
        <Field id="hk-empf-period" text="Contribution period (YYYY-MM)"><input id="hk-empf-period" className={input} placeholder="2026-05" value={period} onChange={(e) => setPeriod(e.target.value)} /></Field>
        <button type="button" className={btn} onClick={() => act(() => prepareHkEmpfSubmission(period), "Remittance batch prepared.")}>Prepare remittance statement</button>
        <p className="text-[11px] text-foreground-muted">No certified eMPF interface: submit on the eMPF platform, then record the reference and outcome here. Payroll is never rewritten by a rejected row.</p>
      </div>
      {messages}
      <EmpfEnrolment />
      {subs.map((s) => (
        <div key={s.id} className={card}>
          <p className="text-[13px] font-semibold text-foreground">
            #{s.id} · {s.contributionPeriod} · {hkLabel(s.status)}{s.totals?.batchType ? ` · ${hkLabel(s.totals.batchType)}` : ""} · contribution day {s.contributionDay}
            {!["PAID", "RECONCILED", "AMENDED"].includes(s.status) && daysUntil(s.contributionDay) !== null && (
              <span className={daysUntil(s.contributionDay) < 0 ? "ml-2 text-error" : "ml-2 text-foreground-muted"}>
                ({daysUntil(s.contributionDay) < 0 ? `${-daysUntil(s.contributionDay)} day(s) overdue` : `${daysUntil(s.contributionDay)} day(s) left`})
              </span>
            )}
          </p>
          <p className="text-[12px] text-foreground-secondary">{s.totals.employees} employee(s) · relevant income HK$ {s.totals.relevantIncome} · employer HK$ {s.totals.employerMandatory} · employee HK$ {s.totals.employeeMandatory}</p>
          {s.validationErrors.length > 0 && <ul className="mt-1 list-disc pl-5 text-[12px] text-warning">{s.validationErrors.map((e) => <li key={e}>{e}</li>)}</ul>}
          {s.status === "VALIDATED" && (
            <div className="mt-2 flex flex-wrap gap-1">
              <input aria-label="eMPF submission reference" placeholder="eMPF submission reference" className={input} onChange={(e) => setRef({ ...ref, [s.id]: e.target.value })} />
              <button type="button" className={btn} onClick={() => act(() => transitionHkEmpfSubmission(s.id, { target: "SUBMITTED", submissionReference: ref[s.id] }), "Submission recorded.")}>Record submission (approver)</button>
            </div>
          )}
          {s.status === "SUBMITTED" && (
            <div className="mt-2 flex flex-wrap gap-1">
              {["ACCEPTED", "PARTIAL", "REJECTED"].map((t) => (
                <button key={t} type="button" className={btnGhost} onClick={() => act(() => transitionHkEmpfSubmission(s.id, { target: t }), `Outcome recorded: ${hkLabel(t)}.`)}>{hkLabel(t)}</button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// MPF enrolment state (spec §5): enrol within the first 60 days of employment.
// Read from the same readiness checks the server builds (deadline from the pack).
function EmpfEnrolment() {
  const [checks, setChecks] = useState([]);
  useEffect(() => {
    getHkEmployerReadiness().then((r) => setChecks((r?.checks || []).filter((c) => (c.code || "").startsWith("MPF_ENROL"))))
      .catch(() => setChecks([]));
  }, []);
  if (!checks.length) return null;
  return (
    <div className={card}>
      <p className="mb-1 text-[13px] font-semibold text-foreground">MPF enrolment</p>
      <ul className="space-y-1 text-[12px]">
        {checks.map((c, i) => (
          <li key={`${c.code}-${c.employeeId}-${i}`} className={c.code === "MPF_ENROLLED" ? "text-foreground-muted" : "text-warning"}>
            {c.employeeCode ? `${c.employeeCode}: ` : ""}{c.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Every termination calculation of the organisation, so a DIFFERENT operator
// can find and approve it (four-eyes), then issue the employee's statement.
function TerminationResults({ employees, refreshKey }) {
  const [rows, setRows] = useState([]);
  const [issued, setIssued] = useState({});
  const { run, messages } = useAction();
  const load = useCallback(() => listHkTerminationResults().then(setRows).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load, refreshKey]);
  const name = (id) => employees.find((e) => e.id === id)?.name || `#${id}`;

  async function statement(r) {
    const year = String(r.terminationDate).slice(0, 4);
    const resolved = await run(() => getApplicableReportTemplate({ reportingYear: year, reportType: "HK_TERMINATION_STATEMENT" }));
    if (!resolved) return;
    if (!resolved.template?.id) {
      await run(() => Promise.reject(new Error(`No Active termination statement template is published for ${year}.`)));
      return;
    }
    const out = await run(() => generateHkTerminationStatement(resolved.template.id, r.id), "Termination statement generated.");
    if (out) setIssued((s) => ({ ...s, [r.id]: out }));
  }

  if (!rows.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-[13px] font-semibold text-foreground">Termination calculations</h3>
      {messages}
      <table className="w-full">
        <caption className="sr-only">Termination calculations</caption>
        <thead><tr><th scope="col" className={th}>Employee</th><th scope="col" className={th}>Termination</th><th scope="col" className={th}>Payment</th><th scope="col" className={th}>Status</th><th scope="col" className={th}>Action</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border">
              <td className={td}>{name(r.employeeId)}</td>
              <td className={td}>{r.terminationDate} · {hkLabel(r.reason)}</td>
              <td className={td}>{hkLabel(r.paymentType)} · net HK$ {r.netStatutoryPayment} · final HK$ {r.totalFinalPayment ?? "—"}</td>
              <td className={td}>{hkLabel(r.status)}</td>
              <td className={`${td} space-x-1`}>
                {r.status === "CALCULATED" && (
                  <button type="button" className={btnGhost} onClick={async () => { if (await run(() => approveHkTermination(r.id), "Approved.")) load(); }}>
                    Approve (different operator)
                  </button>
                )}
                {r.status === "APPROVED" && (
                  <button type="button" className={btn} onClick={() => statement(r)}>Generate statement</button>
                )}
                {issued[r.id]?.id && (
                  <button type="button" className={btnGhost}
                    onClick={() => run(() => downloadReportCertificate(issued[r.id].id, r.employeeId, `termination-statement-${r.employeeId}`))}>
                    Download statement
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Termination({ employees }) {
  const [form, setForm] = useState({ employeeId: "", terminationDate: "", reason: "REDUNDANCY", postTransitionWage: "", mandatoryOffset: "" });
  const [result, setResult] = useState(null);
  const [statement, setStatement] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { run, messages } = useAction();
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  // The statement renders the APPROVED calculation on the Active template for
  // the termination year (MPF / employee documents are versioned per year).
  async function issueStatement() {
    const year = String(result.terminationDate || form.terminationDate).slice(0, 4);
    const resolved = await run(() => getApplicableReportTemplate({ reportingYear: year, reportType: "HK_TERMINATION_STATEMENT" }));
    if (!resolved) return;
    if (!resolved.template?.id) {
      await run(() => Promise.reject(new Error(`No Active termination statement template is published for ${year}.`)));
      return;
    }
    const out = await run(() => generateHkTerminationStatement(resolved.template.id, result.id), "Termination statement generated.");
    if (out) setStatement(out);
  }
  const REASONS = ["REDUNDANCY", "FIXED_TERM_EXPIRY_REDUNDANCY", "LAY_OFF", "DISMISSAL", "FIXED_TERM_EXPIRY", "DEATH",
    "RESIGNATION_ILL_HEALTH", "RESIGNATION_AGE_65", "SUMMARY_DISMISSAL", "RESIGNATION"];

  async function submit(e) {
    e.preventDefault();
    const out = await run(() => calculateHkTermination(Number(form.employeeId), {
      terminationDate: form.terminationDate, reason: form.reason, postTransitionWage: form.postTransitionWage,
      offsets: form.mandatoryOffset ? [{ type: "EMPLOYER_MANDATORY_MPF", amount: form.mandatoryOffset }] : [],
    }), "Calculated — a different operator must approve it.");
    if (out) { setResult(out); setStatement(null); setRefreshKey((k) => k + 1); }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-3`} aria-label="Termination calculator">
        <Field id="hk-t-emp" text="Employee"><EmployeeSelect id="hk-t-emp" employees={employees} value={form.employeeId} onChange={set("employeeId")} /></Field>
        <Field id="hk-t-date" text="Termination date"><input id="hk-t-date" type="date" className={input} value={form.terminationDate} onChange={set("terminationDate")} /></Field>
        <Field id="hk-t-reason" text="Reason"><select id="hk-t-reason" className={input} value={form.reason} onChange={set("reason")}>{REASONS.map((r) => <option key={r} value={r}>{hkLabel(r)}</option>)}</select></Field>
        <Field id="hk-t-wage" text="Last full month's wages before termination (HK$)"><input id="hk-t-wage" inputMode="decimal" className={input} value={form.postTransitionWage} onChange={set("postTransitionWage")} /></Field>
        <Field id="hk-t-off" text="Employer mandatory-MPF accrued benefits (HK$, pre-transition offset only)"><input id="hk-t-off" inputMode="decimal" className={input} value={form.mandatoryOffset} onChange={set("mandatoryOffset")} /></Field>
        <div className="flex items-end"><button type="submit" className={btn}>Calculate</button></div>
      </form>
      {messages}
      {result && (
        <div className={card}>
          <p className="text-[13px] font-semibold text-foreground">{hkLabel(result.paymentType)} · {result.eligibility.reason}{result.status ? ` · ${hkLabel(result.status)}` : ""}</p>
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-3">
            <dt className="text-foreground-muted">Pre-transition portion</dt><dd>HK$ {result.portions?.preTransition?.amountAfterCap ?? result.portions?.preTransition?.amount ?? "—"}</dd>
            <dt className="text-foreground-muted">Post-transition portion</dt><dd>HK$ {result.portions?.postTransition?.amountAfterCap ?? result.portions?.postTransition?.amount ?? "—"}</dd>
            <dt className="text-foreground-muted">Gross entitlement</dt><dd>HK$ {result.grossEntitlement}</dd>
            <dt className="text-foreground-muted">Permitted offsets</dt><dd>HK$ {result.totalOffsets}</dd>
            <dt className="text-foreground-muted">Net statutory payment</dt><dd>HK$ {result.netStatutoryPayment}</dd>
            <dt className="text-foreground-muted">Evidence hash</dt><dd className="font-mono text-[11px]">{result.evidenceHash?.slice(0, 16)}…</dd>
          </dl>
          {result.paymentHold && <p className="mt-2 text-[12px] font-semibold text-warning">{result.paymentHold}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {result.status !== "APPROVED" && (
              <button type="button" className={btnGhost} onClick={async () => {
                const out = await run(() => approveHkTermination(result.id), "Approved.");
                if (out) { setResult({ ...result, ...out, status: "APPROVED" }); setRefreshKey((k) => k + 1); }
              }}>Approve (different operator)</button>
            )}
            {result.status === "APPROVED" && (
              <button type="button" className={btn} onClick={issueStatement}>Generate termination statement</button>
            )}
            {statement?.id && (
              <button type="button" className={btnGhost}
                onClick={() => run(() => downloadReportCertificate(statement.id, result.employeeId, `termination-statement-${result.employeeId}`))}>
                Download statement
              </button>
            )}
          </div>
        </div>
      )}
      <TerminationResults employees={employees} refreshKey={refreshKey} />
    </div>
  );
}

function SalariesTaxInfo() {
  const [form, setForm] = useState({ yearOfAssessment: "2026/27", income: "", deductions: "0" });
  const [out, setOut] = useState(null);
  const { run, messages } = useAction();
  return (
    <div className="space-y-3">
      <p className="text-[12px] text-foreground-secondary">
        Informational only — Hong Kong Salaries Tax is assessed by the IRD on the employee and is never withheld from payroll.
      </p>
      <form className={`${card} grid grid-cols-1 gap-3 sm:grid-cols-4`} aria-label="Salaries Tax estimate"
        onSubmit={async (e) => { e.preventDefault(); setOut(await run(() => estimateHkSalariesTax({ ...form, allowances: { basic: 1 } }))); }}>
        <Field id="hk-st-ya" text="Year of assessment"><input id="hk-st-ya" className={input} value={form.yearOfAssessment} onChange={(e) => setForm({ ...form, yearOfAssessment: e.target.value })} /></Field>
        <Field id="hk-st-inc" text="Assessable income (HK$)"><input id="hk-st-inc" inputMode="decimal" className={input} value={form.income} onChange={(e) => setForm({ ...form, income: e.target.value })} /></Field>
        <Field id="hk-st-ded" text="Deductions (HK$)"><input id="hk-st-ded" inputMode="decimal" className={input} value={form.deductions} onChange={(e) => setForm({ ...form, deductions: e.target.value })} /></Field>
        <div className="flex items-end"><button type="submit" className={btn}>Estimate (basic allowance)</button></div>
      </form>
      {messages}
      {out && <p className="text-[13px] text-foreground">{out.label}: HK$ {out.estimatedTax} ({out.basisApplied}, net chargeable income HK$ {out.netChargeableIncome})</p>}
    </div>
  );
}

export default function HKComplianceCentreTab() {
  const [section, setSection] = useState(0);
  const [employees, setEmployees] = useState([]);
  useEffect(() => {
    getEmployees().then((res) => {
      const rows = Array.isArray(res) ? res : res?.data || res?.items || [];
      setEmployees(rows.filter((e) => (e.countryCode || "").toUpperCase() === "HK"));
    }).catch(() => setEmployees([]));
  }, []);
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Hong Kong compliance workspaces" className="flex flex-wrap gap-2">
        {SECTIONS.map((s, i) => (
          <button key={s} role="tab" aria-selected={section === i} type="button" onClick={() => setSection(i)}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold ${section === i ? "bg-primary text-white" : "border border-border text-foreground"}`}>
            {s}
          </button>
        ))}
      </div>
      {section === 0 && <HKReadinessPanel />}
      {section === 1 && <TaxClearance employees={employees} />}
      {section === 2 && <IrdReporting />}
      {section === 3 && <Empf />}
      {section === 4 && <Termination employees={employees} />}
      {section === 5 && <HKCorrectionsPanel />}
      {section === 6 && <HKPrivacyPanel employees={employees} />}
      {section === 7 && <SalariesTaxInfo />}
    </div>
  );
}
