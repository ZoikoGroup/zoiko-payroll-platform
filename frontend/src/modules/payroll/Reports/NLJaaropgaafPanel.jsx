import { useState } from "react";
import { generateNlAnnualStatement, issueNlAnnualStatement, listNlAnnualStatements, getEmployees } from "../../../service/payrollService";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad } from "../../../components/jurisdiction/netherlands/nlShared";

// Netherlands annual statements (jaaropgaaf, ZP-NL-ENG-001 §15). Figures come
// from the committed payroll ledger of the year; a statement is generated as
// a DRAFT, checked, then issued. An issued statement is never edited.
const money = (v) => (v == null ? "—" : Number(v).toLocaleString("nl-NL", { style: "currency", currency: "EUR" }));

export default function NLJaaropgaafPanel() {
  const [taxYear, setTaxYear] = useState(new Date().getFullYear() - 1);
  const [rows, loadError, , reload] = useLoad(() => listNlAnnualStatements({ tax_year: taxYear }), [taxYear]);
  const [employees] = useLoad(async () => {
    const res = await getEmployees();
    const list = Array.isArray(res) ? res : res?.data || res?.items || [];
    return list.filter((e) => (e.countryCode || e.country_code) === "NL");
  }, []);
  const [employeeId, setEmployeeId] = useState("");
  const { run, error, notice, busy } = useAction(reload);
  const names = Object.fromEntries((employees || []).map((e) => [e.id, e.name]));

  const generate = (e) => {
    e.preventDefault();
    run(() => generateNlAnnualStatement({ employee_id: Number(employeeId), tax_year: Number(taxYear) }),
      "Annual statement generated as a DRAFT — check it, then issue it.");
  };

  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <form onSubmit={generate} className={`${card} flex flex-wrap items-end gap-3`} aria-label="Generate an annual statement">
        <Field label="Tax year">
          <input type="number" className={input} value={taxYear} onChange={(e) => setTaxYear(e.target.value)} />
        </Field>
        <Field label="Employee">
          <select required className={input} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">— Netherlands employee —</option>
            {(employees || []).map((emp) => <option key={emp.id} value={emp.id}>{emp.name}</option>)}
          </select>
        </Field>
        <button type="submit" className={btnPrimary} disabled={busy || !employeeId}>Generate</button>
      </form>
      <div className={card}>
        <Table
          rows={rows}
          empty="No annual statements for this year."
          columns={[
            { key: "employee_id", label: "Employee", render: (r) => names[r.employee_id] || `#${r.employee_id}` },
            { key: "version", label: "Version" },
            { key: "status", label: "Status" },
            { key: "fiscal_wage", label: "Fiscal wage", render: (r) => money(r.fiscal_wage) },
            { key: "wage_tax_withheld", label: "Loonheffing withheld", render: (r) => money(r.wage_tax_withheld) },
            // Not derived yet: the engine applies the credit inside the official
            // table and reports no amount (needs the AK/AHK split, gate G1).
            { key: "applied_employment_credit", label: "Arbeidskorting applied", render: () => "Not derived yet" },
            { key: "zvw_contribution", label: "Zvw contribution", render: (r) => money(r.zvw_contribution) },
            { key: "delivered_at", label: "Delivered" },
            {
              key: "actions", label: "", render: (r) => (r.status === "DRAFT" ? (
                <button type="button" className={btn} disabled={busy}
                  onClick={() => run(() => issueNlAnnualStatement(r.id), "Annual statement issued.")}>Issue</button>
              ) : null),
            },
          ]}
        />
      </div>
    </div>
  );
}
