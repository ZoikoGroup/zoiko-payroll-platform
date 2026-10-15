import { useState } from "react";
import { createNlExpatDecision, listNlEmployees, listNlExpatDecisions, transitionNlExpatDecision } from "../../../service/superAdminService";
import { NeedOrg, Messages, Field, Table, card, btn, btnPrimary, input, useAction, useLoad } from "./nlShared";

// 30% facility decisions (NL-026). Recorded PENDING; payroll applies the
// facility only once the decision is VERIFIED against the attached
// Belastingdienst document. Revoking stops it from now on.
const EMPTY = { employee_id: "", decision_reference: "", decision_date: "", granted_from: "", granted_to: "",
  method: "FACILITY_30PCT", threshold_category: "STANDARD", allowance_pct: "30", evidence_artifact_id: "" };

export default function NLExpatRulesTab({ orgId }) {
  const [rows, loadError, , reload] = useLoad(() => (orgId ? listNlExpatDecisions(orgId) : Promise.resolve([])), [orgId]);
  const [employees] = useLoad(() => (orgId ? listNlEmployees(orgId) : Promise.resolve([])), [orgId]);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  if (!orgId) return <NeedOrg />;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, granted_to: form.granted_to || null, evidence_artifact_id: form.evidence_artifact_id ? Number(form.evidence_artifact_id) : null };
    if (await run(() => createNlExpatDecision(orgId, payload), "Decision recorded as PENDING.")) setForm(null);
  };
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-foreground">Expat (30%) decisions</h3>
          {!form && <button type="button" className={btnPrimary} onClick={() => setForm(EMPTY)}>Record decision</button>}
        </div>
        {form && (
          <form onSubmit={save} className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Employee">
              <select required className={input} value={form.employee_id} onChange={set("employee_id")}>
                <option value="">—</option>
                {(employees || []).map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employee_code})</option>)}
              </select>
            </Field>
            <Field label="Decision reference"><input required className={input} value={form.decision_reference} onChange={set("decision_reference")} /></Field>
            <Field label="Decision date"><input type="date" required className={input} value={form.decision_date} onChange={set("decision_date")} /></Field>
            <Field label="Granted from"><input type="date" required className={input} value={form.granted_from} onChange={set("granted_from")} /></Field>
            <Field label="Granted to"><input type="date" className={input} value={form.granted_to} onChange={set("granted_to")} /></Field>
            <Field label="Method">
              <select className={input} value={form.method} onChange={set("method")}>
                <option>FACILITY_30PCT</option><option>ACTUAL_ET_COSTS</option>
              </select>
            </Field>
            <Field label="Threshold category">
              <select className={input} value={form.threshold_category} onChange={set("threshold_category")}>
                <option>STANDARD</option><option>UNDER30_MASTER</option><option>RESEARCH_MEDICAL</option>
              </select>
            </Field>
            <Field label="Allowance %"><input required className={input} value={form.allowance_pct} onChange={set("allowance_pct")} /></Field>
            <Field label="Evidence document id"><input className={input} value={form.evidence_artifact_id} onChange={set("evidence_artifact_id")} /></Field>
            <div className="col-span-full flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        <Table rows={rows} columns={[
          { key: "employee_name", label: "Employee" }, { key: "decision_reference", label: "Decision" },
          { key: "method", label: "Method" }, { key: "allowance_pct", label: "%" },
          { key: "granted_from", label: "From" }, { key: "granted_to", label: "To" }, { key: "status", label: "Status" },
          { key: "actions", label: "", render: (r) => (
            <div className="flex gap-1">
              {r.status === "PENDING" && <button type="button" className={btn} disabled={busy}
                onClick={() => run(() => transitionNlExpatDecision(orgId, r.id, "verify"), "Decision verified.")}>Verify</button>}
              {["PENDING", "VERIFIED"].includes(r.status) && <button type="button" className={btn} disabled={busy}
                onClick={() => run(() => transitionNlExpatDecision(orgId, r.id, "revoke"), "Decision revoked.")}>Revoke</button>}
            </div>) },
        ]} />
      </div>
    </div>
  );
}
