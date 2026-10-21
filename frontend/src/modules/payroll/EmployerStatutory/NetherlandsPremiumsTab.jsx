import { useState } from "react";
import { Plus } from "lucide-react";
import { activateNlPremiumDecision, createNlPremiumDecision, listNlPremiumDecisions } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { day, isNumber, opt, period } from "./format";

// Employer premium decisions (Aof size class, Whk WGA / ZW-flex). The
// request and response bodies are snake_case. A decision is recorded as
// DRAFT with its Belastingdienst reference; a different colleague activates
// it (four-eyes), superseding the active one. There is no universal Whk rate.
const thisYear = new Date().getFullYear();
const EMPTY = {
  tax_year: String(thisYear), aof_size_class: "SMALL", aof_basis_year: String(thisYear - 2), aof_basis_premium_wage: "",
  whk_wga_pct: "", whk_wga_employee_recoverable_pct: "", whk_zw_flex_pct: "", sector_code: "",
  decision_reference: "", decision_date: "", effective_from: `${thisYear}-01-01`,
};
const PCT_FIELDS = [
  ["whk_wga_pct", "Whk WGA %", true],
  ["whk_wga_employee_recoverable_pct", "Whk WGA employee-recoverable %", false],
  ["whk_zw_flex_pct", "Whk ZW-flex %", true],
];

function DecisionForm({ onCancel, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!/^\d{4}$/.test(form.tax_year)) return setError("Tax year must be a 4-digit year.");
    if (!/^\d{4}$/.test(form.aof_basis_year)) return setError("Aof basis year must be a 4-digit year.");
    if (!isNumber(form.aof_basis_premium_wage) || Number(form.aof_basis_premium_wage) < 0) return setError("Aof basis premium wage must be an amount of 0 or more.");
    for (const [key, label, required] of PCT_FIELDS) {
      if (required && form[key] === "") return setError(`${label} is required.`);
      if (form[key] !== "" && (!isNumber(form[key]) || Number(form[key]) < 0 || Number(form[key]) > 100)) return setError(`${label} must be between 0 and 100.`);
    }
    if (!form.decision_reference.trim()) return setError("The decision reference is required.");
    if (!form.decision_date) return setError("The decision date is required.");
    if (!form.effective_from) return setError("Effective from is required.");
    const payload = {
      tax_year: Number(form.tax_year), aof_size_class: form.aof_size_class, aof_basis_year: Number(form.aof_basis_year),
      aof_basis_premium_wage: String(form.aof_basis_premium_wage).trim(),
      whk_wga_pct: opt(form.whk_wga_pct), whk_wga_employee_recoverable_pct: opt(form.whk_wga_employee_recoverable_pct),
      whk_zw_flex_pct: opt(form.whk_zw_flex_pct), sector_code: opt(form.sector_code),
      decision_reference: form.decision_reference.trim(), decision_date: form.decision_date, effective_from: form.effective_from,
    };
    const res = await run(() => createNlPremiumDecision(payload));
    if (res.ok) onSaved("Draft decision recorded — a different colleague must activate it.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="New premium decision">
      <Field id="nl-year" label="Tax year" required><input id="nl-year" type="number" className={inputCls} value={form.tax_year} onChange={set("tax_year")} /></Field>
      <Field id="nl-aof" label="Aof size class" required>
        <select id="nl-aof" className={inputCls} value={form.aof_size_class} onChange={set("aof_size_class")}>
          <option value="SMALL">SMALL</option><option value="LARGE">LARGE</option>
        </select>
      </Field>
      <Field id="nl-basis-year" label="Aof basis year" required><input id="nl-basis-year" type="number" className={inputCls} value={form.aof_basis_year} onChange={set("aof_basis_year")} /></Field>
      <Field id="nl-basis-wage" label="Aof basis premium wage (€)" required><input id="nl-basis-wage" inputMode="decimal" className={inputCls} value={form.aof_basis_premium_wage} onChange={set("aof_basis_premium_wage")} /></Field>
      {PCT_FIELDS.map(([key, label, required]) => (
        <Field key={key} id={`nl-${key}`} label={label} required={required}>
          <input id={`nl-${key}`} inputMode="decimal" className={inputCls} value={form[key]} onChange={set(key)} />
        </Field>
      ))}
      <Field id="nl-sector" label="Sector code"><input id="nl-sector" className={inputCls} value={form.sector_code} onChange={set("sector_code")} /></Field>
      <Field id="nl-ref" label="Decision reference" required><input id="nl-ref" className={inputCls} value={form.decision_reference} onChange={set("decision_reference")} /></Field>
      <Field id="nl-date" label="Decision date" required><input id="nl-date" type="date" className={inputCls} value={form.decision_date} onChange={set("decision_date")} /></Field>
      <Field id="nl-from" label="Effective from" required><input id="nl-from" type="date" className={inputCls} value={form.effective_from} onChange={set("effective_from")} /></Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save draft" onCancel={onCancel} />
    </form>
  );
}

export default function NetherlandsPremiumsTab({ readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(listNlPremiumDecisions);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState(null);
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];

  async function activate(id) {
    setNotice(null);
    const res = await action.run(() => activateNlPremiumDecision(id), "Decision activated — it supersedes the previously active one.");
    if (res.ok) reload();
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="Employer premium decisions (Aof / Whk)"
        description="Record each Belastingdienst premium decision with its reference. A different colleague activates it (four-eyes).">
        {!readOnly && !creating && (
          <button type="button" className={btnPrimary} onClick={() => { setCreating(true); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> Record decision
          </button>
        )}
      </SectionHeader>
      {creating && <DecisionForm onCancel={() => setCreating(false)} onSaved={(msg) => { setCreating(false); setNotice(msg); reload(); }} />}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No premium decisions recorded yet" text="Record the Aof size class and Whk percentages from your latest decision." />
      ) : (
        <DataTable label="Premium decisions" rows={rows} columns={[
          { key: "tax_year", label: "Year" },
          { key: "aof_size_class", label: "Aof class" },
          { key: "whk_wga_pct", label: "WGA %" },
          { key: "whk_zw_flex_pct", label: "ZW-flex %" },
          { key: "sector_code", label: "Sector" },
          { key: "decision_reference", label: "Decision" },
          { key: "decision_date", label: "Decided", render: (r) => day(r.decision_date) },
          { key: "period", label: "Effective", render: (r) => period(r.effective_from, r.effective_to) },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "actions", label: "", render: (r) => (!readOnly && r.status === "DRAFT" ? (
            <button type="button" className={btnSecondary} disabled={action.busy} onClick={() => activate(r.id)}>Activate</button>
          ) : null) },
        ]} />
      )}
    </div>
  );
}
