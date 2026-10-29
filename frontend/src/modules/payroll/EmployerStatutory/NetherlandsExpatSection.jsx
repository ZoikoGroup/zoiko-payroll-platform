import { useState } from "react";
import { Plus } from "lucide-react";
import { createNlExpatDecision, listNlExpatDecisions, listOrgEmployees, transitionNlExpatDecision } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnDanger, btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { day, display, isNumber, opt, period } from "./format";

// 30% facility (expat) decisions — one per employee, recorded from the
// Belastingdienst decision letter. A decision starts PENDING; payroll only
// applies the facility once it is VERIFIED against the attached document.
// Revoking stops it from now on. Request/response bodies are snake_case.
const EMPTY = {
  employee_id: "", decision_reference: "", decision_date: "", granted_from: "", granted_to: "",
  method: "FACILITY_30PCT", threshold_category: "STANDARD", allowance_pct: "30", evidence_artifact_id: "",
};
const METHODS = [["FACILITY_30PCT", "30% facility"], ["ACTUAL_ET_COSTS", "Actual extraterritorial costs"]];
const THRESHOLDS = [["STANDARD", "Standard"], ["UNDER30_MASTER", "Under 30 with master's degree"], ["RESEARCH_MEDICAL", "Researcher / medical specialist"]];

const employeeLabel = (e) => {
  const name = e.name || e.full_name || [e.first_name, e.last_name].filter(Boolean).join(" ") || `Employee #${e.id}`;
  const code = e.employee_code || e.employeeCode;
  return code ? `${name} (${code})` : name;
};

function ExpatForm({ employees, onCancel, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!form.employee_id) return setError("Choose the employee this decision is for.");
    if (!form.decision_reference.trim()) return setError("The decision reference is required.");
    if (!form.decision_date) return setError("The decision date is required.");
    if (!form.granted_from) return setError("Granted from is required.");
    if (form.granted_to && form.granted_to < form.granted_from) return setError("Granted to must be on or after granted from.");
    if (!isNumber(form.allowance_pct) || Number(form.allowance_pct) < 0 || Number(form.allowance_pct) > 100) return setError("Allowance % must be between 0 and 100.");
    if (form.evidence_artifact_id && !/^\d+$/.test(form.evidence_artifact_id.trim())) return setError("The evidence document id must be a number.");
    const payload = {
      employee_id: Number(form.employee_id), decision_reference: form.decision_reference.trim(),
      decision_date: form.decision_date, granted_from: form.granted_from, granted_to: opt(form.granted_to),
      method: form.method, threshold_category: form.threshold_category, allowance_pct: String(form.allowance_pct).trim(),
      evidence_artifact_id: form.evidence_artifact_id ? Number(form.evidence_artifact_id) : null,
    };
    const res = await run(() => createNlExpatDecision(payload));
    if (res.ok) onSaved("Decision recorded as PENDING — a second person must verify it against the decision letter before payroll applies it.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="New 30% facility decision">
      <Field id="nlx-emp" label="Employee" required className="lg:col-span-2">
        <select id="nlx-emp" className={inputCls} value={form.employee_id} onChange={set("employee_id")}>
          <option value="">Select an employee…</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{employeeLabel(e)}</option>)}
        </select>
      </Field>
      <Field id="nlx-ref" label="Decision reference" required><input id="nlx-ref" className={inputCls} value={form.decision_reference} onChange={set("decision_reference")} /></Field>
      <Field id="nlx-date" label="Decision date" required><input id="nlx-date" type="date" className={inputCls} value={form.decision_date} onChange={set("decision_date")} /></Field>
      <Field id="nlx-from" label="Granted from" required><input id="nlx-from" type="date" className={inputCls} value={form.granted_from} onChange={set("granted_from")} /></Field>
      <Field id="nlx-to" label="Granted to"><input id="nlx-to" type="date" className={inputCls} value={form.granted_to} onChange={set("granted_to")} /></Field>
      <Field id="nlx-method" label="Method" required>
        <select id="nlx-method" className={inputCls} value={form.method} onChange={set("method")}>
          {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </Field>
      <Field id="nlx-threshold" label="Salary threshold category" required>
        <select id="nlx-threshold" className={inputCls} value={form.threshold_category} onChange={set("threshold_category")}>
          {THRESHOLDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </Field>
      <Field id="nlx-pct" label="Allowance %" required><input id="nlx-pct" inputMode="decimal" className={inputCls} value={form.allowance_pct} onChange={set("allowance_pct")} /></Field>
      <Field id="nlx-evidence" label="Evidence document id" hint="The Belastingdienst decision letter, uploaded to your organisation's documents."><input id="nlx-evidence" inputMode="numeric" className={inputCls} value={form.evidence_artifact_id} onChange={set("evidence_artifact_id")} /></Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Record decision" onCancel={onCancel} />
    </form>
  );
}

export default function NetherlandsExpatSection({ readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(listNlExpatDecisions);
  const employees = useLoad(listOrgEmployees);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState(null);
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];
  const employeeList = Array.isArray(employees.data) ? employees.data : [];

  async function transition(id, verb, ok) {
    setNotice(null);
    const res = await action.run(() => transitionNlExpatDecision(id, verb), ok);
    if (res.ok) reload();
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="30% facility decisions"
        description="One decision per employee, from the Belastingdienst letter. Payroll applies the facility only after a second person verifies it against the letter — the person who recorded a decision cannot verify it.">
        {!readOnly && !creating && (
          <button type="button" className={btnPrimary} disabled={employees.initialLoading}
            onClick={() => { setCreating(true); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> Record decision
          </button>
        )}
      </SectionHeader>
      {creating && (employeeList.length === 0 ? (
        <div className="mb-4">
          <EmptyState title="No employees to choose from" text={employees.error || "Add the employee first, then record their decision."}>
            <button type="button" className={btnSecondary} onClick={() => setCreating(false)}>Close</button>
          </EmptyState>
        </div>
      ) : (
        <ExpatForm employees={employeeList} onCancel={() => setCreating(false)}
          onSaved={(msg) => { setCreating(false); setNotice(msg); reload(); }} />
      ))}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No 30% facility decisions yet" text="Record a decision when an employee receives one from the Belastingdienst." />
      ) : (
        <DataTable label="30% facility decisions" rows={rows} columns={[
          { key: "employee_name", label: "Employee", render: (r) => display(r.employee_name || `#${r.employee_id}`) },
          { key: "decision_reference", label: "Decision" },
          { key: "decision_date", label: "Decided", render: (r) => day(r.decision_date) },
          { key: "method", label: "Method", render: (r) => (METHODS.find(([v]) => v === r.method)?.[1] || display(r.method)) },
          { key: "allowance_pct", label: "%" },
          { key: "granted", label: "Granted", render: (r) => period(r.granted_from, r.granted_to) },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "recorded_by", label: "Recorded by", render: (r) => (r.recorded_by ? `User #${r.recorded_by}` : "Not recorded — record again") },
          { key: "verified_by", label: "Verified by", render: (r) => (r.verified_by ? `User #${r.verified_by}` : "—") },
          { key: "actions", label: "", render: (r) => (readOnly ? null : (
            <div className="flex flex-wrap gap-1.5">
              {r.status === "PENDING" && (
                <button type="button" className={btnSecondary} disabled={action.busy}
                  onClick={() => transition(r.id, "verify", "Decision verified — payroll will apply it.")}>Verify</button>
              )}
              {["PENDING", "VERIFIED"].includes(r.status) && (
                <button type="button" className={btnDanger} disabled={action.busy}
                  onClick={() => transition(r.id, "revoke", "Decision revoked — it no longer applies from now on.")}>Revoke</button>
              )}
            </div>
          )) },
        ]} />
      )}
    </div>
  );
}
