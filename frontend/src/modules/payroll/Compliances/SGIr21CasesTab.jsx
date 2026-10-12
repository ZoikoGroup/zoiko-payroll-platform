import { useCallback, useEffect, useState } from "react";
import { getEmployees, listSgIr21Cases, createSgIr21Case, transitionSgIr21Case } from "../../../service/payrollService";

// Singapore IR21 tax clearance (IRAS): for a non-citizen employee who ceases
// employment, goes on an overseas posting or leaves Singapore for more than
// three months, the employer files the Form IR21 at least one month before
// and withholds all monies due from the date it became aware. The server
// owns every rule (transitions, distinct approver, held amounts, bank-file
// exclusion); this tab only displays cases and submits the chosen step.

const TRIGGERS = [
  { key: "CESSATION", label: "Cessation of employment" },
  { key: "OVERSEAS_POSTING", label: "Overseas posting" },
  { key: "DEPARTURE", label: "Leaving Singapore > 3 months" },
];
// Mirrors service._SG_IR21_TRANSITIONS (display only — the server decides).
const NEXT = {
  DRAFT: ["FILED", "EXEMPT", "CANCELLED"],
  FILED: ["CLEARED", "EXEMPT", "CANCELLED", "EXCEPTION"],
  CLEARED: ["RELEASED", "EXCEPTION"],
  EXCEPTION: ["FILED", "CANCELLED"],
};
const EXEMPT_CATEGORIES = [
  "SPR_NOT_LEAVING_PERMANENTLY_LOU", "WORKED_60_DAYS_OR_LESS", "UNDER_21000_183_DAYS",
  "UNDER_21000_STRADDLING_TWO_YEARS", "UNDER_21000_THREE_YEARS", "GROUP_TRANSFER",
  "ABSENCE_3_TO_6_MONTHS", "IRAS_NOT_REQUIRED_NOTIFICATION",
];
const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const label = "mb-1 block text-[12px] font-semibold text-foreground-secondary";

function Field({ id, text, children }) {
  return (
    <div>
      <label className={label} htmlFor={id}>{text}</label>
      {children}
    </div>
  );
}

function StepForm({ item, onDone }) {
  const [form, setForm] = useState({ status: NEXT[item.status]?.[0] || "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const id = (k) => `ir21-${item.id}-${k}`;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await transitionSgIr21Case(item.id, { ...form, directiveTaxAmount: form.directiveTaxAmount || undefined });
      onDone();
    } catch (err) {
      setError(err?.message || "The IR21 step was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  if (!NEXT[item.status]) return <p className="text-[12px] text-foreground-muted">No further steps ({item.status}).</p>;
  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label={`Next IR21 step for ${item.employeeName}`}>
      <Field id={id("status")} text="Next step">
        <select id={id("status")} className={input} value={form.status} onChange={set("status")}>
          {NEXT[item.status].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </Field>
      {form.status === "FILED" && (
        <>
          <Field id={id("filed")} text="Form IR21 filed on"><input id={id("filed")} type="date" className={input} value={form.filedDate || ""} onChange={set("filedDate")} /></Field>
          <Field id={id("ref")} text="Filing reference"><input id={id("ref")} className={input} value={form.filingReference || ""} onChange={set("filingReference")} /></Field>
        </>
      )}
      {form.status === "CLEARED" && (
        <>
          <Field id={id("ddate")} text="IRAS directive date"><input id={id("ddate")} type="date" className={input} value={form.directiveDate || ""} onChange={set("directiveDate")} /></Field>
          <Field id={id("dtax")} text="Tax directed by IRAS (S$)"><input id={id("dtax")} inputMode="decimal" className={input} value={form.directiveTaxAmount || ""} onChange={set("directiveTaxAmount")} /></Field>
          <Field id={id("dref")} text="Directive reference"><input id={id("dref")} className={input} value={form.directiveReference || ""} onChange={set("directiveReference")} /></Field>
        </>
      )}
      {form.status === "EXEMPT" && (
        <Field id={id("cat")} text="IRAS 'not required' category">
          <select id={id("cat")} className={input} value={form.exemptionCategory || ""} onChange={set("exemptionCategory")}>
            <option value="">Select&hellip;</option>
            {EXEMPT_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
      )}
      {["CANCELLED", "EXCEPTION", "EXEMPT"].includes(form.status) && (
        <Field id={id("reason")} text="Reason"><input id={id("reason")} className={input} value={form.reason || ""} onChange={set("reason")} /></Field>
      )}
      {["RELEASED", "EXEMPT", "CANCELLED"].includes(form.status) && (
        <p className="text-[12px] text-foreground-muted sm:col-span-3">
          This lifts the hold on the employee&apos;s monies and must be approved by a different payroll operator from whoever prepared the case.
        </p>
      )}
      {error && <p role="alert" className="text-[12px] font-medium text-error sm:col-span-3">{error}</p>}
      <div className="sm:col-span-3">
        <button type="submit" disabled={busy} className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60">
          {busy ? "Saving…" : `Record ${form.status}`}
        </button>
      </div>
    </form>
  );
}

export default function SGIr21CasesTab() {
  const [cases, setCases] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [form, setForm] = useState({ employeeId: "", triggerType: "CESSATION", triggerDate: "", awareDate: "" });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    try {
      setCases(await listSgIr21Cases());
    } catch (err) {
      setError(err?.message || "Could not load IR21 cases.");
    }
  }, []);

  useEffect(() => {
    // State is set only in the promise callbacks (never synchronously here).
    listSgIr21Cases().then(setCases).catch((err) => setError(err?.message || "Could not load IR21 cases."));
    getEmployees().then((list) => setEmployees(list.filter((e) => (e.countryCode || "").toUpperCase() === "SG")));
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function create(e) {
    e.preventDefault();
    setError(null);
    try {
      await createSgIr21Case({ ...form, employeeId: Number(form.employeeId) });
      setNotice("IR21 case opened — the employee's monies are now withheld from the aware date.");
      setForm((f) => ({ ...f, employeeId: "", triggerDate: "", awareDate: "" }));
      load();
    } catch (err) {
      setError(err?.message || "The IR21 case was not opened.");
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-[18px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">IR21 tax clearance</h3>
        <p className="mb-4 text-[12px] text-foreground-muted">
          For a non-Singapore-Citizen employee ceasing employment, posted overseas or leaving Singapore for more than
          three months: file the Form IR21 at least one month before, and withhold all monies due from the date you
          became aware (IRAS). Held pay is left out of bank transfer files until the case is released.
        </p>
        <form onSubmit={create} className="grid grid-cols-1 gap-3 sm:grid-cols-4" aria-label="Open an IR21 case">
          <Field id="ir21-emp" text="Employee">
            <select id="ir21-emp" className={input} value={form.employeeId} onChange={set("employeeId")} required>
              <option value="">Select&hellip;</option>
              {employees.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employeeCode || e.id})</option>)}
            </select>
          </Field>
          <Field id="ir21-trigger" text="Trigger">
            <select id="ir21-trigger" className={input} value={form.triggerType} onChange={set("triggerType")}>
              {TRIGGERS.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </Field>
          <Field id="ir21-date" text="Cessation / departure date">
            <input id="ir21-date" type="date" className={input} value={form.triggerDate} onChange={set("triggerDate")} required />
          </Field>
          <Field id="ir21-aware" text="Date you became aware">
            <input id="ir21-aware" type="date" className={input} value={form.awareDate} onChange={set("awareDate")} required />
          </Field>
          <div className="sm:col-span-4">
            <button type="submit" className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white">Open IR21 case</button>
          </div>
        </form>
        <div aria-live="polite" className="mt-3">
          {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
          {notice && !error && <p role="status" className="text-[12px] font-medium text-success">{notice}</p>}
        </div>
      </div>

      <div className="overflow-x-auto rounded-[18px] border border-border bg-surface">
        <table className="w-full text-left text-[12px]">
          <caption className="sr-only">IR21 tax-clearance cases for this organization</caption>
          <thead className="text-foreground-muted">
            <tr>
              {["Employee", "Trigger", "File by", "Status", "Held (S$)", "Released (S$)", ""].map((h, i) => (
                <th key={i} scope="col" className="px-3 py-2">{h || <span className="sr-only">Actions</span>}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-foreground-muted">No IR21 cases.</td></tr>
            )}
            {cases.map((c) => (
              <tr key={c.id} className="border-t border-border align-top">
                <th scope="row" className="px-3 py-2 font-medium text-foreground">{c.employeeName}</th>
                <td className="px-3 py-2">{c.triggerType} · {c.triggerDate}</td>
                <td className="px-3 py-2">{c.fileByDate}{c.fileByOverdue && <span className="ml-1 font-semibold text-error">(overdue)</span>}</td>
                <td className="px-3 py-2">{c.status}{c.holdInForce && <span className="ml-1 font-semibold text-warning">· pay held</span>}</td>
                <td className="px-3 py-2">{c.holdInForce ? c.currentHeldAmount : c.heldAmount}</td>
                <td className="px-3 py-2">{c.releasedAmount ?? "—"}</td>
                <td className="px-3 py-2">
                  <button type="button" className="text-[12px] font-semibold text-primary hover:underline" aria-expanded={open === c.id}
                    onClick={() => setOpen(open === c.id ? null : c.id)}>
                    {open === c.id ? "Close" : "Next step"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {cases.filter((c) => c.id === open).map((c) => (
          <div key={c.id} className="border-t border-border p-4">
            {c.exceptionReason && <p className="mb-2 text-[12px] text-foreground-muted">Note: {c.exceptionReason}</p>}
            <StepForm item={c} onDone={() => { setOpen(null); load(); }} />
          </div>
        ))}
      </div>
    </div>
  );
}
