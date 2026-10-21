import { useState } from "react";
import { createNlEarningClassification, listNlEarningClassifications } from "../../../service/superAdminService";
import { Messages, Field, Table, card, btnPrimary, input, useAction, useLoad, yesNo } from "./nlShared";

// Seven independent classification axes per earning code (NL-047). A new
// row supersedes the open catalog row from its effective date; an
// unclassified earning blocks the payslip. ZP-PRIV: this is the PLATFORM
// catalog only — an organisation's own overrides are tenant configuration
// and are no longer read or written from the Super Admin plane.
const FLAGS = [["wage_tax", "Wage tax"], ["employee_insurance_wage", "EI wage"], ["zvw_wage", "Zvw wage"],
  ["pensionable", "Pensionable"], ["vacation_allowance_basis", "Vacation basis"], ["minimum_wage_reckonable", "Min-wage reckonable"]];
const EMPTY = { earning_code: "", remuneration_type: "REGULAR", wkr_treatment: "WAGE", evidence_policy: "NONE",
  effective_from: "", ...Object.fromEntries(FLAGS.map(([k]) => [k, true])) };

export default function NLEarningClassificationTab() {
  const [rows, loadError, , reload] = useLoad(() => listNlEarningClassifications(), []);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, organization_id: null };
    if (await run(() => createNlEarningClassification(payload), "Classification recorded.")) setForm(null);
  };
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-foreground">Earning classifications — platform catalog</h3>
          {!form && <button type="button" className={btnPrimary} onClick={() => setForm(EMPTY)}>New classification</button>}
        </div>
        {form && (
          <form onSubmit={save} className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Earning code"><input required className={input} value={form.earning_code} onChange={set("earning_code")} /></Field>
            <Field label="Remuneration"><select className={input} value={form.remuneration_type} onChange={set("remuneration_type")}><option>REGULAR</option><option>SPECIAL</option></select></Field>
            <Field label="WKR treatment">
              <select className={input} value={form.wkr_treatment} onChange={set("wkr_treatment")}>
                {["WAGE", "TARGETED_EXEMPTION", "ZERO_VALUATION", "FINAL_LEVY_DESIGNATED", "N_A"].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
            <Field label="Evidence policy">
              <select className={input} value={form.evidence_policy} onChange={set("evidence_policy")}>
                {["NONE", "RECEIPT", "DECLARATION", "BOTH"].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
            <Field label="Effective from"><input type="date" required className={input} value={form.effective_from} onChange={set("effective_from")} /></Field>
            {FLAGS.map(([k, l]) => (
              <label key={k} className="flex items-center gap-2 text-[12px] text-foreground">
                <input type="checkbox" checked={!!form[k]} onChange={set(k)} />{l}
              </label>
            ))}
            <div className="col-span-full flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        <Table rows={rows} columns={[
          { key: "earning_code", label: "Code" },
          { key: "remuneration_type", label: "Type" },
          ...FLAGS.map(([k, l]) => ({ key: k, label: l, render: (r) => yesNo(r[k]) })),
          { key: "wkr_treatment", label: "WKR" }, { key: "effective_from", label: "From" },
          { key: "effective_to", label: "To" }, { key: "status", label: "Status" },
        ]} />
      </div>
    </div>
  );
}
