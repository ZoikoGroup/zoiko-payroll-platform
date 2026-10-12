import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  calculateHkAverageWage, calculateHkEntitlement, createHkIrdEventCases, downloadReportCertificate,
  generateHkMpfContributionRecord, getApplicableReportTemplate, getHkContinuousContract, listHkIrdCases,
  listHkTaxClearanceCases, recordHkWorkHours, listHkAverageWageSnapshots, requestHkAverageWageOverride,
  approveHkAverageWageOverride,
} from "../../../service/payrollService";
import { hkLabel } from "../../../components/jurisdiction/hong_kong/hkLabels";

// Hong Kong employee statutory workspace (gap-closure D-10 / D-11). Only Hong
// Kong concepts appear here: Employment Ordinance work hours and continuous
// contract, the 12-month average wage and the entitlements paid from it, MPF
// contribution records, IRD IR56 notifications and IR56G tax clearance. The
// server decides every rule. This modal only submits facts and shows results.
// Filing, rendering and termination live in Compliance → Hong Kong Compliance
// Centre, where the four-eyes approvals are.
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "mb-1 block text-[12px] font-semibold text-foreground-secondary";
const btn = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60";
const card = "rounded-xl border border-border bg-surface p-4 space-y-3";
const h = "text-[13px] font-semibold text-foreground";
const today = () => new Date().toISOString().slice(0, 10);
const BENEFITS = [
  ["HOLIDAY_PAY", "Statutory holiday pay"], ["ANNUAL_LEAVE_PAY", "Annual leave pay"],
  ["SICKNESS_ALLOWANCE", "Sickness allowance"], ["MATERNITY_LEAVE_PAY", "Maternity leave pay"],
  ["PATERNITY_LEAVE_PAY", "Paternity leave pay"],
];

// MPF templates are versioned per CALENDAR year (seed_statutory_report_templates:
// reporting_year "2026" for HK_MPF_CONTRIBUTION_RECORD / HK_EMPF_REMITTANCE),
// unlike the IRD forms, which are keyed by year of assessment.
function mpfReportingYear(period) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(period || "") ? period.slice(0, 4) : null;
}

function Field({ id, text, children }) {
  return <div><label className={labelCls} htmlFor={id}>{text}</label>{children}</div>;
}

export default function HKStatutoryFormsModal({ employee, onClose }) {
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

  const [ccDate, setCcDate] = useState(today());
  const [cc, setCc] = useState(null);
  const [hours, setHours] = useState({ date: today(), hours: "", evidenceRef: "" });
  const [aw, setAw] = useState({ benefitType: "HOLIDAY_PAY", referenceDate: today() });
  const [snapshot, setSnapshot] = useState(null);
  const [ent, setEnt] = useState({ date: today(), days: "", sicknessDays: "", medicallyCertified: false, noticeGiven: false, documentProvided: false });
  const [entOut, setEntOut] = useState(null);
  const [period, setPeriod] = useState("");
  const [mpfReport, setMpfReport] = useState(null);
  const [cases, setCases] = useState([]);
  const [holds, setHolds] = useState([]);
  const [snapshots, setSnapshots] = useState([]);
  const [override, setOverride] = useState({});

  const loadCases = useCallback(() => {
    listHkIrdCases().then((rows) => setCases(rows.filter((c) => c.employeeId === employee.id))).catch(() => setCases([]));
    listHkTaxClearanceCases().then((rows) => setHolds(rows.filter((c) => c.employeeId === employee.id))).catch(() => setHolds([]));
    listHkAverageWageSnapshots(employee.id).then(setSnapshots).catch(() => setSnapshots([]));
  }, [employee.id]);
  useEffect(() => { loadCases(); }, [loadCases]);

  async function generateMpfRecord() {
    const year = mpfReportingYear(period);
    if (!year) { setError("Enter the contribution period as YYYY-MM."); return; }
    const resolved = await run(() => getApplicableReportTemplate({ reportingYear: year, reportType: "HK_MPF_CONTRIBUTION_RECORD" }));
    if (!resolved) return;
    if (!resolved.template?.id) { setError(`No Active MPF contribution record template is published for ${year}.`); return; }
    const out = await run(() => generateHkMpfContributionRecord(resolved.template.id, employee.id, period), "MPF contribution record generated.");
    if (out) setMpfReport(out);
  }

  const entPayload = () => ({
    averageWageSnapshotId: snapshot?.id, date: ent.date || undefined,
    days: ent.days || undefined, sicknessDays: ent.sicknessDays ? Number(ent.sicknessDays) : undefined,
    consecutiveDays: ent.sicknessDays ? Number(ent.sicknessDays) : undefined,
    medicallyCertified: ent.medicallyCertified, noticeGiven: ent.noticeGiven, documentProvided: ent.documentProvided,
  });

  return (
    // Same click-containment as HKStatutoryProfilePanel: this renders inside
    // EmployeeDetailPanel, whose backdrop closes on click, so a click inside
    // the workspace must not bubble up to it.
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="h-full w-full max-w-2xl overflow-y-auto bg-surface-muted p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="hk-forms-title">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 id="hk-forms-title" className="text-[15px] font-bold text-foreground">Hong Kong statutory workspace</h2>
            <p className="text-[12px] text-foreground-muted">{employee.name} ({employee.employeeCode})</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close panel" className="rounded-lg p-1 text-foreground-muted hover:text-foreground"><X size={18} /></button>
        </div>
        <div aria-live="polite" className="mb-3">
          {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
          {notice && <p role="status" className="text-[12px] font-medium text-success">{notice}</p>}
        </div>

        <div className="space-y-4">
          <section className={card} aria-labelledby="hk-cc">
            <h3 id="hk-cc" className={h}>Continuous contract (Employment Ordinance)</h3>
            <div className="flex flex-wrap items-end gap-2">
              <Field id="hk-cc-date" text="As of"><input id="hk-cc-date" type="date" className={input} value={ccDate} onChange={(e) => setCcDate(e.target.value)} /></Field>
              <button type="button" className={btn} onClick={async () => setCc(await run(() => getHkContinuousContract(employee.id, ccDate)))}>Check</button>
            </div>
            {cc && (
              <p className="text-[12px] text-foreground">
                {hkLabel(cc.status)}{cc.continuousSince ? ` since ${cc.continuousSince}` : ""} · {cc.weeksOfContinuity} week(s) · thresholds {cc.rules?.weeklyHours} h/week, {cc.rules?.fourWeekHours} h over 4 weeks
              </p>
            )}
          </section>

          <form className={card} aria-labelledby="hk-hours" onSubmit={async (e) => {
            e.preventDefault();
            await run(() => recordHkWorkHours(employee.id, { entries: [{ date: hours.date, hours: hours.hours, evidenceRef: hours.evidenceRef || null }] }), "Hours recorded.");
          }}>
            <h3 id="hk-hours" className={h}>Work hours (verified timesheet)</h3>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              <Field id="hk-h-date" text="Date"><input id="hk-h-date" type="date" className={input} value={hours.date} onChange={(e) => setHours({ ...hours, date: e.target.value })} /></Field>
              <Field id="hk-h-hours" text="Hours"><input id="hk-h-hours" inputMode="decimal" className={input} value={hours.hours} onChange={(e) => setHours({ ...hours, hours: e.target.value })} /></Field>
              <Field id="hk-h-ev" text="Evidence reference"><input id="hk-h-ev" className={input} value={hours.evidenceRef} onChange={(e) => setHours({ ...hours, evidenceRef: e.target.value })} /></Field>
              <div className="flex items-end"><button type="submit" className={btn}>Record</button></div>
            </div>
          </form>

          <section className={card} aria-labelledby="hk-aw">
            <h3 id="hk-aw" className={h}>Average wage and entitlements</h3>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <Field id="hk-aw-b" text="Benefit"><select id="hk-aw-b" className={input} value={aw.benefitType} onChange={(e) => setAw({ ...aw, benefitType: e.target.value })}>
                {BENEFITS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
              <Field id="hk-aw-d" text="Reference date"><input id="hk-aw-d" type="date" className={input} value={aw.referenceDate} onChange={(e) => setAw({ ...aw, referenceDate: e.target.value })} /></Field>
              <div className="flex items-end"><button type="button" className={btn} onClick={async () => {
                const out = await run(() => calculateHkAverageWage(employee.id, { benefitType: aw.benefitType, referenceDate: aw.referenceDate }), "Average wage snapshot recorded.");
                if (out) { setSnapshot(out); setEntOut(null); loadCases(); }
              }}>Calculate average wage</button></div>
            </div>
            {snapshot && (
              <p className="text-[12px] text-foreground">
                Snapshot #{snapshot.id}: HK$ {snapshot.averageDailyWage}/day (4/5: HK$ {snapshot.fourFifthsDailyWage}) over {snapshot.lookbackStart} – {snapshot.lookbackEnd}
              </p>
            )}
            {snapshot && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <Field id="hk-e-date" text="Benefit date"><input id="hk-e-date" type="date" className={input} value={ent.date} onChange={(e) => setEnt({ ...ent, date: e.target.value })} /></Field>
                {["ANNUAL_LEAVE_PAY", "PATERNITY_LEAVE_PAY"].includes(aw.benefitType) && (
                  <Field id="hk-e-days" text="Days"><input id="hk-e-days" inputMode="decimal" className={input} value={ent.days} onChange={(e) => setEnt({ ...ent, days: e.target.value })} /></Field>
                )}
                {aw.benefitType === "SICKNESS_ALLOWANCE" && (
                  <>
                    <Field id="hk-e-sick" text="Consecutive sick days"><input id="hk-e-sick" inputMode="numeric" className={input} value={ent.sicknessDays} onChange={(e) => setEnt({ ...ent, sicknessDays: e.target.value })} /></Field>
                    <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={ent.medicallyCertified} onChange={(e) => setEnt({ ...ent, medicallyCertified: e.target.checked })} /> Medical certificate provided</label>
                  </>
                )}
                {aw.benefitType === "MATERNITY_LEAVE_PAY" && (
                  <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={ent.noticeGiven} onChange={(e) => setEnt({ ...ent, noticeGiven: e.target.checked })} /> Notice of pregnancy given</label>
                )}
                {aw.benefitType === "PATERNITY_LEAVE_PAY" && (
                  <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={ent.documentProvided} onChange={(e) => setEnt({ ...ent, documentProvided: e.target.checked })} /> Birth document provided</label>
                )}
                <div className="flex items-end"><button type="button" className={btn} onClick={async () => setEntOut(await run(() => calculateHkEntitlement(employee.id, { benefit: aw.benefitType, ...entPayload() })))}>Calculate entitlement</button></div>
              </div>
            )}
            {entOut && (
              <p className="text-[12px] text-foreground">
                {hkLabel(entOut.benefit || aw.benefitType)}: {hkLabel(entOut.status)}{entOut.amount != null ? ` · HK$ ${entOut.amount}` : ""}{entOut.dailyRate ? ` (HK$ ${entOut.dailyRate}/day)` : ""} · continuous contract {entOut.continuousContract}
                {entOut.failedConditions?.length ? ` · not met: ${entOut.failedConditions.join(", ")}` : ""}
              </p>
            )}
          </section>

          {snapshots.length > 0 && (
            <section className={card} aria-labelledby="hk-aw-snaps">
              <h3 id="hk-aw-snaps" className={h}>Average-wage snapshots and overrides</h3>
              <ul className="space-y-2 text-[12px] text-foreground">
                {snapshots.map((s) => (
                  <li key={s.id}>
                    #{s.id} · {hkLabel(s.benefitType)} · {s.referenceDate} · HK$ {s.averageDailyWage}/day · {hkLabel(s.status)}
                    {s.overrideRequested && !s.overrideApprovedById && (
                      <span className="ml-2">
                        override HK$ {s.overrideRequested} requested ({s.overrideReason})
                        <button type="button" className="ml-2 rounded-lg border border-border px-2 py-0.5 text-[11px] font-semibold"
                          onClick={async () => { if (await run(() => approveHkAverageWageOverride(s.id), "Override approved.")) loadCases(); }}>
                          Approve override (different operator)
                        </button>
                      </span>
                    )}
                    {!s.overrideRequested && (
                      <span className="ml-2 inline-flex flex-wrap gap-1">
                        <input aria-label={`Override daily wage for snapshot ${s.id}`} placeholder="Daily wage (HK$)" className="rounded border border-border px-2 py-0.5 text-[11px]"
                          onChange={(e) => setOverride({ ...override, [s.id]: { ...(override[s.id] || {}), averageDailyWage: e.target.value } })} />
                        <input aria-label={`Override reason for snapshot ${s.id}`} placeholder="Reason" className="rounded border border-border px-2 py-0.5 text-[11px]"
                          onChange={(e) => setOverride({ ...override, [s.id]: { ...(override[s.id] || {}), reason: e.target.value } })} />
                        <input aria-label={`Override evidence for snapshot ${s.id}`} placeholder="Evidence reference" className="rounded border border-border px-2 py-0.5 text-[11px]"
                          onChange={(e) => setOverride({ ...override, [s.id]: { ...(override[s.id] || {}), evidenceRef: e.target.value } })} />
                        <button type="button" className="rounded-lg border border-border px-2 py-0.5 text-[11px] font-semibold"
                          onClick={async () => { if (await run(() => requestHkAverageWageOverride(s.id, override[s.id] || {}), "Override requested — a different operator approves it.")) loadCases(); }}>
                          Request override
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className={card} aria-labelledby="hk-mpf">
            <h3 id="hk-mpf" className={h}>MPF contribution record</h3>
            <div className="flex flex-wrap items-end gap-2">
              <Field id="hk-mpf-p" text="Contribution period (YYYY-MM)"><input id="hk-mpf-p" className={input} placeholder="2026-05" value={period} onChange={(e) => setPeriod(e.target.value)} /></Field>
              <button type="button" className={btn} onClick={generateMpfRecord}>Generate record</button>
              {mpfReport?.id && (
                <button type="button" className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground"
                  onClick={() => run(() => downloadReportCertificate(mpfReport.id, employee.id, `MPF-${period}-${employee.employeeCode}`))}>Download</button>
              )}
            </div>
          </section>

          <section className={card} aria-labelledby="hk-ird">
            <div className="flex items-center justify-between">
              <h3 id="hk-ird" className={h}>IRD notifications and tax clearance</h3>
              <button type="button" className={btn} onClick={async () => { if (await run(() => createHkIrdEventCases(employee.id), "IR56 cases created where an event is due.")) loadCases(); }}>
                Create due IR56 cases
              </button>
            </div>
            <ul className="space-y-1 text-[12px] text-foreground">
              {cases.map((c) => (
                <li key={c.id}>
                  {c.formType} · YA {c.yearOfAssessment} · due {c.dueDate || "—"} · {hkLabel(c.status)}
                  {c.employeeCopyDeliveredAt ? " · employee copy delivered" : ""}
                </li>
              ))}
              {!cases.length && <li className="text-foreground-muted">No IRD cases for this employee.</li>}
            </ul>
            {holds.map((hd) => (
              <p key={hd.id} className="rounded-[12px] border border-warning/30 bg-warning/10 px-3 py-2 text-[12px] text-warning">
                IR56G {hkLabel(hd.state)} · departure {hd.expectedDepartureDate} · file by {hd.filingDeadline} · held HK$ {hd.heldTotal} (legal hold, not a deduction)
              </p>
            ))}
            <p className="text-[11px] text-foreground-muted">
              Render, file and amend IR56 forms, record employee copies and calculate termination payments under Compliance → Hong Kong Compliance Centre.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
