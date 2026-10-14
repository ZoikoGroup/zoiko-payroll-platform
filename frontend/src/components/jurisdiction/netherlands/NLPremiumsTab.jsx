import { useState } from "react";
import { activateNlPremiumDecision, createNlPremiumDecision, listNlPremiumDecisions } from "../../../service/superAdminService";
import { NeedOrg, Messages, Field, Table, card, btn, btnPrimary, input, useAction, useLoad } from "./nlShared";

// Employer premium decisions (Aof size class, Whk WGA / ZW-flex — NL-017).
// Recorded as DRAFT with the Belastingdienst decision reference; a second
// Super Admin activates it (four-eyes). There is no universal Whk rate.
const EMPTY = { tax_year: new Date().getFullYear(), aof_size_class: "SMALL", aof_basis_year: "", aof_basis_premium_wage: "",
  whk_wga_pct: "", whk_wga_employee_recoverable_pct: "", whk_zw_flex_pct: "", sector_code: "",
  decision_reference: "", decision_date: "", effective_from: "" };

export default function NLPremiumsTab({ orgId }) {
  const [rows, loadError, , reload] = useLoad(() => (orgId ? listNlPremiumDecisions(orgId) : Promise.resolve([])), [orgId]);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  if (!orgId) return <NeedOrg />;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    if (await run(() => createNlPremiumDecision(orgId, form), "Draft decision recorded — a second Super Admin must activate it.")) setForm(null);
  };
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-foreground">Employer premium decisions</h3>
          {!form && <button type="button" className={btnPrimary} onClick={() => setForm(EMPTY)}>Record decision</button>}
        </div>
        {form && (
          <form onSubmit={save} className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Tax year"><input type="number" required className={input} value={form.tax_year} onChange={set("tax_year")} /></Field>
            <Field label="Aof size class">
              <select className={input} value={form.aof_size_class} onChange={set("aof_size_class")}>
                <option>SMALL</option><option>LARGE</option>
              </select>
            </Field>
            <Field label="Aof basis year"><input type="number" required className={input} value={form.aof_basis_year} onChange={set("aof_basis_year")} /></Field>
            <Field label="Aof basis premium wage"><input required className={input} value={form.aof_basis_premium_wage} onChange={set("aof_basis_premium_wage")} /></Field>
            <Field label="Whk WGA %"><input required className={input} value={form.whk_wga_pct} onChange={set("whk_wga_pct")} /></Field>
            <Field label="Whk WGA employee-recoverable %"><input className={input} value={form.whk_wga_employee_recoverable_pct} onChange={set("whk_wga_employee_recoverable_pct")} /></Field>
            <Field label="Whk ZW-flex %"><input required className={input} value={form.whk_zw_flex_pct} onChange={set("whk_zw_flex_pct")} /></Field>
            <Field label="Sector code"><input className={input} value={form.sector_code} onChange={set("sector_code")} /></Field>
            <Field label="Decision reference"><input required className={input} value={form.decision_reference} onChange={set("decision_reference")} /></Field>
            <Field label="Decision date"><input type="date" required className={input} value={form.decision_date} onChange={set("decision_date")} /></Field>
            <Field label="Effective from"><input type="date" required className={input} value={form.effective_from} onChange={set("effective_from")} /></Field>
            <div className="col-span-full flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save draft</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        <Table rows={rows} columns={[
          { key: "tax_year", label: "Year" }, { key: "aof_size_class", label: "Aof" },
          { key: "whk_wga_pct", label: "WGA %" }, { key: "whk_zw_flex_pct", label: "ZW-flex %" },
          { key: "decision_reference", label: "Decision" }, { key: "effective_from", label: "From" },
          { key: "effective_to", label: "To" }, { key: "status", label: "Status" },
          { key: "actions", label: "", render: (r) => r.status === "DRAFT" && (
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => activateNlPremiumDecision(orgId, r.id), "Decision activated.")}>Activate</button>) },
        ]} />
      </div>
    </div>
  );
}
