import { useState } from "react";
import { createNlPensionScheme, listNlCaos, listNlPensionSchemes } from "../../../service/superAdminService";
import { Messages, Field, Table, card, btnPrimary, input, useAction, useLoad, yesNo } from "./nlShared";

// CAOs come from the governed collective-agreement registry (read-only here).
// Pension schemes (NL-043): the PLATFORM catalog; a mandatory sector scheme
// needs its applicability evidence. ZP-PRIV: an organisation's own schemes
// are tenant configuration and are no longer read or written from here.
const EMPTY = { fund_name: "", scheme_code: "", basis_rule: "GROSS_MINUS_FRANCHISE", franchise_amount: "0",
  max_pensionable_salary: "", employee_pct: "", employer_pct: "", mandatory_sector: false, collective_agreement_id: "",
  evidence_artifact_id: "", effective_from: "" };

export default function NLCaoPensionCatalogTab() {
  const [caos, caoError] = useLoad(() => listNlCaos(), []);
  const [schemes, schemeError, , reload] = useLoad(() => listNlPensionSchemes(), []);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    const rest = form;
    const payload = { ...rest, organization_id: null,
      collective_agreement_id: rest.collective_agreement_id ? Number(rest.collective_agreement_id) : null,
      evidence_artifact_id: rest.evidence_artifact_id ? Number(rest.evidence_artifact_id) : null,
      max_pensionable_salary: rest.max_pensionable_salary || null };
    if (await run(() => createNlPensionScheme(payload), "Pension scheme recorded.")) setForm(null);
  };
  return (
    <div className="flex flex-col gap-4">
      <Messages error={caoError || schemeError || error} notice={notice} />
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Collective agreements (CAO) — governed registry</h3>
        <Table rows={caos} columns={[
          { key: "agreement_code", label: "Code" }, { key: "name", label: "Name" }, { key: "agreement_type", label: "Type" },
          { key: "version", label: "Version" }, { key: "effective_from", label: "From" }, { key: "status", label: "Status" },
        ]} />
      </div>
      <div className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-foreground">Pension schemes — platform catalog</h3>
          {!form && <button type="button" className={btnPrimary} onClick={() => setForm(EMPTY)}>New scheme</button>}
        </div>
        {form && (
          <form onSubmit={save} className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Fund name"><input required className={input} value={form.fund_name} onChange={set("fund_name")} /></Field>
            <Field label="Scheme code"><input required className={input} value={form.scheme_code} onChange={set("scheme_code")} /></Field>
            <Field label="Basis rule"><select className={input} value={form.basis_rule} onChange={set("basis_rule")}><option>GROSS_MINUS_FRANCHISE</option><option>CAPPED_PENSIONABLE</option></select></Field>
            <Field label="Franchise (annual)"><input className={input} value={form.franchise_amount} onChange={set("franchise_amount")} /></Field>
            <Field label="Max pensionable salary"><input className={input} value={form.max_pensionable_salary} onChange={set("max_pensionable_salary")} /></Field>
            <Field label="Employee %"><input required className={input} value={form.employee_pct} onChange={set("employee_pct")} /></Field>
            <Field label="Employer %"><input required className={input} value={form.employer_pct} onChange={set("employer_pct")} /></Field>
            <Field label="CAO id"><input className={input} value={form.collective_agreement_id} onChange={set("collective_agreement_id")} /></Field>
            <Field label="Evidence document id"><input className={input} value={form.evidence_artifact_id} onChange={set("evidence_artifact_id")} /></Field>
            <Field label="Effective from"><input type="date" required className={input} value={form.effective_from} onChange={set("effective_from")} /></Field>
            <label className="flex items-center gap-2 text-[12px] text-foreground">
              <input type="checkbox" checked={form.mandatory_sector} onChange={set("mandatory_sector")} />Mandatory sector scheme
            </label>
            <div className="col-span-full flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        <Table rows={schemes} columns={[
          { key: "fund_name", label: "Fund" }, { key: "scheme_code", label: "Code" },
          { key: "basis_rule", label: "Basis" }, { key: "employee_pct", label: "EE %" }, { key: "employer_pct", label: "ER %" },
          { key: "mandatory_sector", label: "Mandatory", render: (r) => yesNo(r.mandatory_sector) },
          { key: "effective_from", label: "From" }, { key: "status", label: "Status" },
        ]} />
      </div>
    </div>
  );
}
