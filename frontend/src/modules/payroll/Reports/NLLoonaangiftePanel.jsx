import { useState } from "react";
import { buildNlReturn, getNlReturn, listNlReturns, reconcileNlReturn } from "../../../service/payrollService";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad } from "../../../components/jurisdiction/netherlands/nlShared";

// Netherlands payroll-tax returns (loonaangifte, ZP-NL-ENG-001 §13). Returns
// are BUILT from committed payroll only and reconciled against it; the totals
// are the server's. Filing through Digipoort stays locked until gate G3, so
// there is deliberately no "file" button here.
const money = (v) => (v == null ? "—" : Number(v).toLocaleString("nl-NL", { style: "currency", currency: "EUR" }));

export default function NLLoonaangiftePanel() {
  const year = new Date().getFullYear();
  const [taxYear, setTaxYear] = useState(year);
  const [returns, loadError, , reload] = useLoad(() => listNlReturns(taxYear), [taxYear]);
  const [period, setPeriod] = useState("");
  const [returnType, setReturnType] = useState("REGULAR");
  const [detail, setDetail] = useState(null);
  const [report, setReport] = useState(null);
  const { run, error, notice, busy } = useAction(reload);

  const build = (e) => {
    e.preventDefault();
    run(() => buildNlReturn({ tax_year: Number(taxYear), period_code: period.trim(), return_type: returnType }),
      `Return ${period} built from committed payroll.`);
  };
  const open = (r) => run(async () => setDetail(await getNlReturn(r.id)));
  const reconcile = (r) => run(async () => setReport(await reconcileNlReturn(r.id)), "Reconciliation recorded.");

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-[12px] text-foreground">
        Transmission to the Belastingdienst (Digipoort) is locked until gate G3 is signed — returns can be built and
        reconciled here, not filed.
      </div>
      <Messages error={loadError || error} notice={notice} />
      <form onSubmit={build} className={`${card} flex flex-wrap items-end gap-3`} aria-label="Build a payroll-tax return">
        <Field label="Tax year">
          <input type="number" className={input} value={taxYear} onChange={(e) => setTaxYear(e.target.value)} />
        </Field>
        <Field label="Period code">
          <input required className={input} placeholder={`${year}03`} value={period} onChange={(e) => setPeriod(e.target.value)} />
        </Field>
        <Field label="Return type">
          <select className={input} value={returnType} onChange={(e) => setReturnType(e.target.value)}>
            <option value="REGULAR">REGULAR — from committed payroll</option>
            <option value="NIL">NIL — no payroll this period</option>
            <option value="ZERO">ZERO</option>
          </select>
        </Field>
        <button type="submit" className={btnPrimary} disabled={busy}>Build return</button>
      </form>
      <div className={card}>
        <Table
          rows={returns}
          empty="No returns built for this year."
          columns={[
            { key: "period_code", label: "Period" },
            { key: "return_type", label: "Type" },
            { key: "version", label: "Version" },
            { key: "status", label: "Status" },
            { key: "due_date", label: "Due" },
            { key: "total_wage_tax", label: "Loonheffing", render: (r) => money(r.total_wage_tax) },
            { key: "total_payable", label: "Total payable", render: (r) => money(r.total_payable) },
            { key: "journal_reconciled", label: "Reconciled", render: (r) => (r.journal_reconciled ? "Yes" : "No") },
            {
              key: "actions", label: "", render: (r) => (
                <div className="flex gap-2">
                  <button type="button" className={btn} onClick={() => open(r)} disabled={busy}>Lines</button>
                  <button type="button" className={btn} onClick={() => reconcile(r)} disabled={busy}>Reconcile</button>
                </div>
              ),
            },
          ]}
        />
      </div>
      {report && (
        <div className={card}>
          <h4 className="mb-2 text-[13px] font-semibold text-foreground">Reconciliation</h4>
          <pre className="overflow-x-auto whitespace-pre-wrap text-[11px] text-foreground-muted">{JSON.stringify(report, null, 2)}</pre>
        </div>
      )}
      {detail && (
        <div className={card}>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-[13px] font-semibold text-foreground">Return {detail.period_code} — employee lines</h4>
            <button type="button" className={btn} onClick={() => setDetail(null)}>Close</button>
          </div>
          <Table
            rows={detail.lines}
            columns={[
              { key: "personnel_number", label: "Personnel no." },
              { key: "line_type", label: "Line" },
              { key: "wage_lb_phf", label: "Wage LB/PH", render: (l) => money(l.wage_lb_phf) },
              { key: "wage_sv", label: "Wage SV", render: (l) => money(l.wage_sv) },
              { key: "wage_zvw", label: "Wage Zvw", render: (l) => money(l.wage_zvw) },
              { key: "awf_class", label: "AWf" },
              { key: "wage_tax", label: "Loonheffing", render: (l) => money(l.wage_tax) },
              { key: "zvw", label: "Zvw", render: (l) => money(l.zvw) },
            ]}
          />
        </div>
      )}
    </div>
  );
}
