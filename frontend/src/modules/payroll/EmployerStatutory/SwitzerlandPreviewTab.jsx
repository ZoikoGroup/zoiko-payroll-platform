import { useMemo, useState } from "react";
import { Calculator } from "lucide-react";
import { listOrgEmployees, previewSwissCalculation } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import { btnPrimary, cardCls, EmptyState, ErrorState, Field, inputCls, LoadingState, Messages, SectionHeader } from "./ui";
import { isNumber, today } from "./format";

// Read-only Swiss calculation preview for one of YOUR employees: the same
// resolver and production engine a payroll run uses. The organization comes
// from the login; nothing is saved. A missing fact or rate returns the
// engine's own block, never a guessed figure. Running a preview writes
// nothing, so it stays available on small screens.
const employeeName = (e) => e.name || e.full_name || e.fullName || [e.first_name, e.last_name].filter(Boolean).join(" ") || `Employee #${e.id}`;
const employeeCode = (e) => e.employee_code || e.employeeCode || e.code || "";
const employeeCountry = (e) => String(e.country_code || e.countryCode || e.country || "").toUpperCase();

const money = (v) => (v === null || v === undefined || v === "" ? "—" : `CHF ${v}`);

export default function SwitzerlandPreviewTab() {
  const employees = useLoad(listOrgEmployees);
  const [form, setForm] = useState({ employeeId: "", payDate: today(), periodStart: "", periodEnd: "", baseSalary: "" });
  const [out, setOut] = useState(null);
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  // Prefer the Swiss employees when the list carries a country; otherwise
  // offer everyone (the server refuses non-CH employees with a clear block).
  const options = useMemo(() => {
    const list = Array.isArray(employees.data) ? employees.data : [];
    const swiss = list.filter((e) => employeeCountry(e) === "CH");
    return swiss.length ? swiss : list;
  }, [employees.data]);

  async function submit(e) {
    e.preventDefault();
    if (!form.employeeId) return setError("Choose an employee.");
    if (!form.payDate) return setError("The payment date is required.");
    if (form.periodStart && form.periodEnd && form.periodEnd < form.periodStart) return setError("The period end must be on or after its start.");
    if (form.baseSalary && (!isNumber(form.baseSalary) || Number(form.baseSalary) < 0)) return setError("Monthly base salary must be an amount of 0 or more.");
    const payload = {
      employeeId: Number(form.employeeId), payDate: form.payDate,
      ...(form.periodStart ? { periodStart: form.periodStart } : {}),
      ...(form.periodEnd ? { periodEnd: form.periodEnd } : {}),
      ...(form.baseSalary ? { earnings: { base_salary: String(form.baseSalary).trim() } } : {}),
    };
    setOut(null);
    const res = await run(() => previewSwissCalculation(payload));
    if (res.ok) setOut(res.data || null);
  }

  const totals = out && !out.blocked ? out.switzerland?.totals || {} : null;

  return (
    <div className={cardCls}>
      <SectionHeader
        title="Switzerland — calculation preview"
        description="Runs the Swiss engine for one of your employees on a payment date. Read-only: nothing is saved and no payslip is created."
      />
      {employees.initialLoading ? (
        <LoadingState text="Loading employees…" />
      ) : employees.error ? (
        <ErrorState message={employees.error} onRetry={employees.reload} />
      ) : options.length === 0 ? (
        <EmptyState title="No employees yet" text="Add a Swiss employee first, then come back to preview their payslip." />
      ) : (
        <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Swiss calculation preview">
          <Field id="ch-emp" label="Employee" required className="lg:col-span-2">
            <select id="ch-emp" className={inputCls} value={form.employeeId} onChange={set("employeeId")}>
              <option value="">Select an employee…</option>
              {options.map((e) => (
                <option key={e.id} value={e.id}>{employeeName(e)}{employeeCode(e) ? ` (${employeeCode(e)})` : ""}</option>
              ))}
            </select>
          </Field>
          <Field id="ch-date" label="Payment date" required>
            <input id="ch-date" type="date" className={inputCls} value={form.payDate} onChange={set("payDate")} />
          </Field>
          <Field id="ch-start" label="Period start">
            <input id="ch-start" type="date" className={inputCls} value={form.periodStart} onChange={set("periodStart")} />
          </Field>
          <Field id="ch-end" label="Period end">
            <input id="ch-end" type="date" className={inputCls} value={form.periodEnd} onChange={set("periodEnd")} />
          </Field>
          <Field id="ch-base" label="Monthly base salary" hint="Optional — defaults to the annual salary / 12." className="lg:col-span-2">
            <input id="ch-base" inputMode="decimal" className={inputCls} value={form.baseSalary} onChange={set("baseSalary")} placeholder="e.g. 7500.00" />
          </Field>
          <div className="col-span-full flex justify-end">
            <button type="submit" className={btnPrimary} disabled={busy}>
              <Calculator size={14} aria-hidden="true" /> {busy ? "Calculating…" : "Run preview"}
            </button>
          </div>
        </form>
      )}

      <div className="mt-4 space-y-3">
        <Messages error={error} />
        {out?.blocked && (
          <p role="status" className="rounded-[12px] border border-warning/30 bg-warning/5 px-3 py-2 text-[12px] text-foreground-muted dark:bg-warning/10">
            The engine could not calculate this payslip yet
            {out.blockedKey ? <> — missing <span className="font-mono">{String(out.blockedKey)}</span></> : null}
            {out.blockedReason ? `: ${String(out.blockedReason)}` : "."}
          </p>
        )}
        {totals && (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 rounded-[14px] border border-border p-4 text-[12px] sm:grid-cols-2">
            {[
              ["Gross", out.result?.gross],
              ["Total deductions", out.result?.totalDeductions],
              ["Net pay", out.result?.netPay],
              ["Employee statutory deductions (incl. QST)", totals.ch_employee_total],
              ["QST withheld (source tax)", totals.ch_qst_total],
              ["BVG employee share", totals.ch_bvg_employee],
              ["Employer statutory cost", totals.ch_employer_total],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3 border-b border-border/60 py-1 last:border-0">
                <dt className="text-foreground-muted">{label}</dt>
                <dd className="font-semibold text-foreground">{money(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}
