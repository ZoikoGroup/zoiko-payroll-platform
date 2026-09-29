import { useEffect, useState } from "react";
import {
  getEmployees, correctSgPayslip, createSgSalaryDeduction, freezeSgAfterRestore, releaseSgBankExportHold,
  listSgIr8a, transitionSgIr8a, generateSgComplianceReport, generateSgIr8a, createSgIr8aModification,
} from "../../../service/payrollService";

// Singapore operator actions for the Compliance Centre (Phase 5.1): the
// append-only correction of a finalized payslip (SG-044), an Employment
// Act salary deduction with its consent / evidence (SG-037), and the
// disaster-recovery freeze of uncertain CPF submissions (SG-047). The server
// computes and validates everything; these cards only submit the operator's
// decision and display the server's answer.

// Display-only mirror of labour.SG_DEDUCTION_CATEGORIES (the server decides).
const CATEGORIES = [
  ["LOAN", "Loan instalment"], ["ADVANCE", "Salary advance"], ["ACCOMMODATION", "Accommodation (accepted)"],
  ["AMENITIES_SERVICES", "Amenities / services (Commissioner-approved)"], ["DAMAGE_LOSS", "Damage / loss (after inquiry)"],
  ["COOPERATIVE", "Co-operative society (written consent)"], ["CONSENTED_OTHER", "Other, with written consent"],
  ["OVERPAID_SALARY", "Overpaid salary / unearned benefit"], ["COURT_ORDER", "Court order / valid authority"],
  ["TAX_AGENT_RECOVERY", "Recovery as tax agent"],
];
const input = "rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const btn = "rounded-lg border border-border bg-surface-muted px-3 py-1.5 text-[12px] font-semibold text-foreground hover:border-primary disabled:opacity-50";
const label = "mb-1 block text-[12px] font-semibold text-foreground-secondary";

function Card({ id, title, intro, children }) {
  return (
    <section className="rounded-[18px] border border-border p-5" aria-labelledby={id}>
      <h3 id={id} className="text-[13px] font-bold text-foreground">{title}</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">{intro}</p>
      {children}
    </section>
  );
}

function useSubmit() {
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn, ok) => {
    setBusy(true);
    setMessage(null);
    try {
      setMessage({ ok: true, text: ok(await fn()) });
    } catch (err) {
      setMessage({ ok: false, text: err?.message || "The request was not accepted." });
    } finally {
      setBusy(false);
    }
  };
  return { message, busy, run };
}

function Message({ message }) {
  if (!message) return null;
  return <p className={`mt-2 text-[12px] ${message.ok ? "text-foreground-muted" : "text-error"}`} role={message.ok ? "status" : "alert"}>{message.text}</p>;
}

export function SGCorrectionCard({ onDone }) {
  const [form, setForm] = useState({ payslipId: "", reason: "" });
  const { message, busy, run } = useSubmit();
  return (
    <Card id="sg-correction-heading" title="Correct a finalized payslip"
          intro="Append-only: the finalized payslip is never changed. Zoiko recalculates it on its own frozen rates with the corrected employee facts and records only the difference as a linked correction (reason, actor and time audited).">
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
        e.preventDefault();
        run(() => correctSgPayslip(Number(form.payslipId), form.reason), (r) => {
          onDone?.();
          return `Correction ${r.sequence} recorded (delta payslip ${r.deltaPayslipId}, correction run ${r.correctionRunId})` +
            (r.cpfRefundRequired ? " — CPF was over-contributed: apply to CPF Board for a refund." : "") +
            (r.employeeRecoveryAmount && r.employeeRecoveryAmount !== "0" ? ` Employee recovery S$${r.employeeRecoveryAmount}.` : "");
        });
      }}>
        <div>
          <label className={label} htmlFor="sg-corr-id">Payslip ID</label>
          <input id="sg-corr-id" required inputMode="numeric" className={`${input} w-28`} value={form.payslipId}
                 onChange={(e) => setForm((f) => ({ ...f, payslipId: e.target.value }))} />
        </div>
        <div className="min-w-[16rem] flex-1">
          <label className={label} htmlFor="sg-corr-reason">Reason</label>
          <input id="sg-corr-reason" required minLength={3} className={`${input} w-full`} value={form.reason}
                 onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
        </div>
        <button type="submit" className={btn} disabled={busy}>Record correction</button>
      </form>
      <Message message={message} />
    </Card>
  );
}

export function SGDeductionCard() {
  const [employees, setEmployees] = useState([]);
  const [form, setForm] = useState({ employeeId: "", category: "LOAN", startDate: "", evidenceRef: "", evidenceDate: "",
    amount: "", totalToCollect: "" });
  const { message, busy, run } = useSubmit();
  useEffect(() => {
    getEmployees().then((res) => {
      const list = Array.isArray(res) ? res : res?.data || res?.items || [];
      setEmployees(list.filter((e) => (e.countryCode || e.country) === "SG"));
    }).catch(() => setEmployees([]));
  }, []);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Card id="sg-deduction-heading" title="Record a salary deduction"
          intro="Employment Act deductions only, with their consent / evidence. MOM caps (25% / 50% of the salary) are applied at every payroll; work-pass costs such as the levy can never be recovered.">
      <form className="grid gap-2 sm:grid-cols-3" onSubmit={(e) => {
        e.preventDefault();
        run(() => createSgSalaryDeduction(Number(form.employeeId), {
          category: form.category, startDate: form.startDate, evidenceRef: form.evidenceRef, evidenceDate: form.evidenceDate,
          amount: form.amount || null, totalToCollect: form.totalToCollect || null,
        }), (r) => `Deduction ${r.id} recorded (${r.orderType}).`);
      }}>
        <div>
          <label className={label} htmlFor="sg-ded-emp">Employee</label>
          <select id="sg-ded-emp" required className={`${input} w-full`} value={form.employeeId} onChange={set("employeeId")}>
            <option value="">Select…</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.employeeCode || e.id} · {e.name}</option>)}
          </select>
        </div>
        <div>
          <label className={label} htmlFor="sg-ded-cat">Category</label>
          <select id="sg-ded-cat" className={`${input} w-full`} value={form.category} onChange={set("category")}>
            {CATEGORIES.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className={label} htmlFor="sg-ded-start">From</label>
          <input id="sg-ded-start" type="date" required className={`${input} w-full`} value={form.startDate} onChange={set("startDate")} />
        </div>
        <div>
          <label className={label} htmlFor="sg-ded-ref">Consent / evidence reference</label>
          <input id="sg-ded-ref" required className={`${input} w-full`} value={form.evidenceRef} onChange={set("evidenceRef")} />
        </div>
        <div>
          <label className={label} htmlFor="sg-ded-date">Evidence date</label>
          <input id="sg-ded-date" type="date" required className={`${input} w-full`} value={form.evidenceDate} onChange={set("evidenceDate")} />
        </div>
        <div>
          <label className={label} htmlFor="sg-ded-amt">Amount per payroll (S$)</label>
          <input id="sg-ded-amt" required inputMode="decimal" className={`${input} w-full`} value={form.amount} onChange={set("amount")} />
        </div>
        <div>
          <label className={label} htmlFor="sg-ded-total">Total to recover (S$, optional)</label>
          <input id="sg-ded-total" inputMode="decimal" className={`${input} w-full`} value={form.totalToCollect} onChange={set("totalToCollect")} />
        </div>
        <div className="flex items-end"><button type="submit" className={btn} disabled={busy}>Record deduction</button></div>
      </form>
      <Message message={message} />
    </Card>
  );
}

export function SGRestoreFreezeCard({ onDone }) {
  const [restorePoint, setRestorePoint] = useState("");
  const [restoreDate, setRestoreDate] = useState("");
  const [release, setRelease] = useState({ runId: "", reference: "" });
  const { message, busy, run } = useSubmit();
  return (
    <Card id="sg-dr-heading" title="After a database restore (SG-047)"
          intro="Freezes every external action whose outcome may have changed since the restore point: CPF EZPay and IR8A submissions become UNKNOWN, IR21 cases not yet filed must be reconciled with IRAS, and bank exports are held until the bank reconciliation is recorded. Nothing is replayed.">
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
        e.preventDefault();
        run(() => freezeSgAfterRestore(restorePoint, restoreDate), (r) => {
          onDone?.();
          return `${r.frozen.length} submission(s) frozen, ${r.ir21ReconcileFirst.length} IR21 case(s) to reconcile, ` +
            `${r.bankExportHeld.length} run(s) on bank-export hold (restore point ${r.restorePoint}).`;
        });
      }}>
        <div className="min-w-[16rem] flex-1">
          <label className={label} htmlFor="sg-dr-point">Restore point</label>
          <input id="sg-dr-point" required minLength={3} className={`${input} w-full`} placeholder="e.g. backup 2026-10-31 02:00 SGT"
                 value={restorePoint} onChange={(e) => setRestorePoint(e.target.value)} />
        </div>
        <div>
          <label className={label} htmlFor="sg-dr-date">Hold bank exports of runs paid from (optional)</label>
          <input id="sg-dr-date" type="date" className={input} value={restoreDate} onChange={(e) => setRestoreDate(e.target.value)} />
        </div>
        <button type="submit" className={btn} disabled={busy}>Freeze uncertain actions</button>
      </form>
      <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => {
        e.preventDefault();
        run(() => releaseSgBankExportHold(Number(release.runId), release.reference),
          (r) => `Bank-export hold released for run ${r.runId} (reconciliation ${r.reference}).`);
      }}>
        <div>
          <label className={label} htmlFor="sg-dr-run">Held run ID</label>
          <input id="sg-dr-run" required inputMode="numeric" className={`${input} w-28`} value={release.runId}
                 onChange={(e) => setRelease((f) => ({ ...f, runId: e.target.value }))} />
        </div>
        <div className="min-w-[14rem] flex-1">
          <label className={label} htmlFor="sg-dr-ref">Bank reconciliation reference</label>
          <input id="sg-dr-ref" required minLength={3} className={`${input} w-full`} value={release.reference}
                 onChange={(e) => setRelease((f) => ({ ...f, reference: e.target.value }))} />
        </div>
        <button type="submit" className={btn} disabled={busy}>Release bank-export hold</button>
      </form>
      <Message message={message} />
    </Card>
  );
}

// Display-only mirror of service._SG_IR8A_TRANSITIONS (the server decides).
const IR8A_NEXT = { EXPORT_READY: ["SUBMITTED_MANUALLY"], SUBMITTED_MANUALLY: ["ACKNOWLEDGED", "REJECTED", "UNKNOWN"],
  UNKNOWN: ["ACKNOWLEDGED", "REJECTED"] };

// Phase 6.8 (G3): an IRAS-ACKNOWLEDGED original can be revised (full values)
// or amended (differences only); the server computes the position and delta.
function Ir8aModificationForm({ row, onDone }) {
  const [form, setForm] = useState({ method: "AMENDMENT", reason: "" });
  const { message, busy, run } = useSubmit();
  return (
    <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => {
      e.preventDefault();
      run(() => createSgIr8aModification(row.id, form), (r) => {
        onDone?.();
        return `IR8A ${String(r?.method || form.method).toLowerCase()} prepared${r?.reportId ? ` as extract ${r.reportId}` : ""} — file it on myTax Portal, then record it below.`;
      });
    }}>
      <label className="sr-only" htmlFor={`ir8a-${row.id}-method`}>Modification</label>
      <select id={`ir8a-${row.id}-method`} className={input} value={form.method}
              onChange={(e) => setForm((f) => ({ ...f, method: e.target.value }))}>
        <option value="AMENDMENT">Amendment (differences only)</option>
        <option value="REVISION">Revision (full values)</option>
      </select>
      <label className="sr-only" htmlFor={`ir8a-${row.id}-reason`}>Reason</label>
      <input id={`ir8a-${row.id}-reason`} className={input} placeholder="Reason" maxLength={1000} value={form.reason}
             onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
      <button type="submit" className={btn} disabled={busy}>Prepare modification</button>
      <Message message={message} />
    </form>
  );
}

function Ir8aRow({ row, onDone }) {
  const next = IR8A_NEXT[row.submissionStatus] || [];
  const [form, setForm] = useState({ status: next[0] || "", reference: "", note: "" });
  const { message, busy, run } = useSubmit();
  return (
    <li className="rounded-[12px] border border-border p-3 text-[12px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>IR8A {row.reportingYear} · {row.submissionKind === "ORIGINAL" ? "original" : String(row.submissionKind).toLowerCase()} extract {row.id} · {row.employees} employee(s)</span>
        <span className="font-semibold">{row.submissionStatus}</span>
      </div>
      {row.submissionStatus === "ACKNOWLEDGED" && row.submissionKind === "ORIGINAL" && (
        <Ir8aModificationForm row={row} onDone={onDone} />
      )}
      {next.length > 0 && (
        <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => {
          e.preventDefault();
          run(() => transitionSgIr8a(row.id, form), (r) => { onDone?.(); return `IR8A ${r.reportingYear} is now ${r.submissionStatus}.`; });
        }}>
          <label className="sr-only" htmlFor={`ir8a-${row.id}-status`}>Next status</label>
          <select id={`ir8a-${row.id}-status`} className={input} value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
            {next.map((st) => <option key={st} value={st}>{st}</option>)}
          </select>
          <label className="sr-only" htmlFor={`ir8a-${row.id}-ref`}>IRAS reference</label>
          <input id={`ir8a-${row.id}-ref`} className={input} placeholder="IRAS submission / acknowledgement reference"
                 value={form.reference} onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))} />
          <label className="sr-only" htmlFor={`ir8a-${row.id}-note`}>Note</label>
          <input id={`ir8a-${row.id}-note`} className={input} placeholder="Note" value={form.note}
                 onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
          <button type="submit" className={btn} disabled={busy}>Record</button>
        </form>
      )}
      <Message message={message} />
    </li>
  );
}

export function SGIr8aSubmissionCard() {
  const [rows, setRows] = useState([]);
  const [version, setVersion] = useState(0);
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [loadError, setLoadError] = useState(null);
  const { message, busy, run } = useSubmit();
  useEffect(() => {
    let active = true;
    listSgIr8a()
      .then((r) => { if (active) { setRows(r); setLoadError(null); } })
      .catch((e) => { if (active) { setRows([]); setLoadError(e?.message || "IR8A extracts could not be loaded."); } });
    return () => { active = false; };
  }, [version]);
  return (
    <Card id="sg-ir8a-heading" title="IR8A manual submission (SG-023)"
          intro="AIS-API direct submission is NOT READY. Record the employer's manual filing on myTax Portal and IRAS's outcome against each extract — a different operator from the preparer records the submission, and IRAS's reference is required.">
      <form className="mb-3 flex flex-wrap items-end gap-2" onSubmit={(e) => {
        e.preventDefault();
        run(() => generateSgIr8a(year), (r) => {
          setVersion((v) => v + 1);
          return `IR8A extract ${r?.id ?? ""} prepared for ${year} (EXPORT_READY) — not submitted to IRAS.`;
        });
      }}>
        <label className={label} htmlFor="sg-ir8a-year">Income year
          <input id="sg-ir8a-year" type="number" className={`${input} block w-28`} min={2026} value={year}
                 onChange={(e) => setYear(Number(e.target.value))} />
        </label>
        <button type="submit" className={btn} disabled={busy}>Prepare IR8A extract</button>
      </form>
      <Message message={message} />
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      {rows.length ? <ul className="space-y-2">{rows.map((r) => (
        <Ir8aRow key={`${r.id}-${r.submissionStatus}`} row={r} onDone={() => setVersion((v) => v + 1)} />
      ))}</ul> : <p className="text-[12px] text-foreground-muted">No IR8A extracts yet.</p>}
    </Card>
  );
}

// Phase 5.7 — PWM / LQS (CPF wage month) and IR21 register (year), all
// computed server-side from the existing evaluators; this card only picks
// the period and shows the server's counts. Internal reports only.
const SG_REPORTS = [
  ["SG_PWM_COMPLIANCE", "PWM compliance", true],
  ["SG_LQS_COMPLIANCE", "LQS compliance", true],
  ["SG_IR21_REGISTER", "IR21 register", false],
];

export function SGComplianceReportsCard() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const { message, busy, run } = useSubmit();
  const summarize = (r) => {
    const d = r?.renderedData || {};
    const counts = Object.entries(d.counts || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "no rows";
    return `${r?.reportType} generated for ${r?.reportingPeriod}: ${counts}. Internal report — not an MOM / IRAS submission.`;
  };
  return (
    <Card id="sg-reports-heading" title="Compliance reports (PWM · LQS · IR21)"
      intro="Internal Singapore reports from the payroll's own PWM, LQS and IR21 evaluations; anything that cannot be evaluated is listed as NOT_EVALUATED. Needs an Active template.">
      <div className="flex flex-wrap items-end gap-2">
        <label className={label}>Year
          <input type="number" className={input} value={year} min={2026} onChange={(e) => setYear(Number(e.target.value))} />
        </label>
        <label className={label}>Wage month
          <input type="number" className={input} value={month} min={1} max={12} onChange={(e) => setMonth(Number(e.target.value))} />
        </label>
        {SG_REPORTS.map(([type, text, monthly]) => (
          <button key={type} type="button" className={btn} disabled={busy}
            onClick={() => run(() => generateSgComplianceReport(type, monthly ? { year, month } : { year }), summarize)}>
            {text}
          </button>
        ))}
      </div>
      <Message message={message} />
    </Card>
  );
}
