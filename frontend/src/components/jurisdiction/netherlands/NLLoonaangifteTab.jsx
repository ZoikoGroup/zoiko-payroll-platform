import { useState } from "react";
import { buildNlReturn, correctNlReturn, getNlReturn, listNlReturns, reconcileNlReturn } from "../../../service/superAdminService";
import { NeedOrg, Messages, Field, Table, card, btn, btnPrimary, input, useAction, useLoad } from "./nlShared";

// Loonaangifte (spec §13). Returns are built from COMMITTED payroll and
// reconciled against it. Transmission (Digipoort), authority acceptance and
// payment stay locked until gate G3 (official Gegevensspecificaties,
// PKIoverheid certificate, Digipoort test access) — the payload is a
// labelled placeholder until then.
export default function NLLoonaangifteTab({ orgId }) {
  const [rows, loadError, , reload] = useLoad(() => (orgId ? listNlReturns(orgId) : Promise.resolve([])), [orgId]);
  const [form, setForm] = useState({ tax_year: new Date().getFullYear(), period_code: "", return_type: "REGULAR" });
  const [detail, setDetail] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  if (!orgId) return <NeedOrg />;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const open = (r) => run(async () => setDetail(await getNlReturn(orgId, r.id)));
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <p className="mb-3 text-[12px] text-foreground-muted">
          Transmission to the Belastingdienst is locked until gate G3. Returns can be built and reconciled now.
        </p>
        <form className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => { e.preventDefault(); run(() => buildNlReturn(orgId, form), "Return built."); }}>
          <Field label="Tax year"><input type="number" required className={input} value={form.tax_year} onChange={set("tax_year")} /></Field>
          <Field label="Period code (e.g. 202603)"><input required className={input} value={form.period_code} onChange={set("period_code")} /></Field>
          <Field label="Type"><select className={input} value={form.return_type} onChange={set("return_type")}><option>REGULAR</option><option>NIL</option><option>ZERO</option></select></Field>
          <button type="submit" className={btnPrimary} disabled={busy}>Build return</button>
        </form>
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Returns</h3>
        <Table rows={rows} columns={[
          { key: "period_code", label: "Period" }, { key: "version", label: "Ver" }, { key: "return_type", label: "Type" },
          { key: "total_wage_tax", label: "Wage tax" }, { key: "total_payable", label: "Payable" },
          { key: "due_date", label: "Due" }, { key: "status", label: "Status" },
          { key: "journal_reconciled", label: "Reconciled", render: (r) => (r.journal_reconciled ? "Yes" : "No") },
          { key: "actions", label: "", render: (r) => (
            <div className="flex gap-1">
              <button type="button" className={btn} onClick={() => open(r)}>Lines</button>
              <button type="button" className={btn} disabled={busy}
                onClick={() => run(() => reconcileNlReturn(orgId, r.id), "Return reconciled.")}>Reconcile</button>
              {r.status === "READY" && r.return_type !== "CORRECTION" && (
                <button type="button" className={btn} disabled={busy}
                  onClick={() => run(() => correctNlReturn(orgId, r.id), "Correction return built.")}>Correct</button>)}
            </div>) },
        ]} />
      </div>
      {detail && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Lines — {detail.period_code} v{detail.version}</h3>
          <Table rows={detail.lines} columns={[
            { key: "personnel_number", label: "Personnel no." }, { key: "line_type", label: "Type" },
            { key: "wage_lb_phf", label: "Wage LB/PH" }, { key: "wage_sv", label: "SV wage" }, { key: "wage_zvw", label: "Zvw wage" },
            { key: "hours", label: "Hours" }, { key: "awf_class", label: "AWf" }, { key: "wage_tax", label: "Wage tax" },
            { key: "zvw", label: "Zvw" },
          ]} />
        </div>
      )}
    </div>
  );
}
