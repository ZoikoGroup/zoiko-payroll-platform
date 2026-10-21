import { useState } from "react";
import { Plus } from "lucide-react";
import {
  createNlEarningClassification, createNlPensionScheme, listNlEarningClassifications, listNlPensionSchemes,
} from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls, LoadingState, Messages,
  SectionHeader, StatusBadge,
} from "./ui";
import { display, isNumber, opt, period, today } from "./format";

// The organization's own Netherlands overrides on top of the platform
// catalog: earning classifications (seven independent axes per earning code)
// and pension schemes. Lists show the platform catalog read-only next to
// your own rows. Bodies are snake_case.
const scopeOf = (r) => (r.organization_id ? "Your organization" : "Platform catalog");

const FLAGS = [
  ["wage_tax", "Wage tax"], ["employee_insurance_wage", "Employee-insurance wage"], ["zvw_wage", "Zvw wage"],
  ["pensionable", "Pensionable"], ["vacation_allowance_basis", "Vacation-allowance basis"],
  ["minimum_wage_reckonable", "Counts toward minimum wage"],
];
const WKR = ["WAGE", "TARGETED_EXEMPTION", "ZERO_VALUATION", "FINAL_LEVY_DESIGNATED", "N_A"];
const EVIDENCE = ["NONE", "RECEIPT", "DECLARATION", "BOTH"];
const EMPTY_CLASS = {
  earning_code: "", remuneration_type: "REGULAR", wkr_treatment: "WAGE", evidence_policy: "NONE",
  effective_from: today(), ...Object.fromEntries(FLAGS.map(([k]) => [k, true])),
};
const EMPTY_SCHEME = {
  fund_name: "", scheme_code: "", basis_rule: "GROSS_MINUS_FRANCHISE", franchise_amount: "0", max_pensionable_salary: "",
  employee_pct: "", employer_pct: "", mandatory_sector: false, collective_agreement_id: "", evidence_artifact_id: "",
  effective_from: today(),
};

function useForm(initial) {
  const [form, setForm] = useState(initial);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  return [form, set];
}

function ClassificationForm({ onCancel, onSaved }) {
  const [form, set] = useForm(EMPTY_CLASS);
  const { run, busy, error, setError } = useAction();

  async function submit(e) {
    e.preventDefault();
    if (!form.earning_code.trim()) return setError("The earning code is required.");
    if (!form.effective_from) return setError("Effective from is required.");
    const res = await run(() => createNlEarningClassification({ ...form, earning_code: form.earning_code.trim() }));
    if (res.ok) onSaved("Classification override recorded — it supersedes your open row for that code from its effective date.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="New earning classification override">
      <Field id="nlc-code" label="Earning code" required><input id="nlc-code" className={inputCls} value={form.earning_code} onChange={set("earning_code")} /></Field>
      <Field id="nlc-rem" label="Remuneration" required>
        <select id="nlc-rem" className={inputCls} value={form.remuneration_type} onChange={set("remuneration_type")}>
          <option value="REGULAR">Regular</option><option value="SPECIAL">Special</option>
        </select>
      </Field>
      <Field id="nlc-wkr" label="WKR treatment" required>
        <select id="nlc-wkr" className={inputCls} value={form.wkr_treatment} onChange={set("wkr_treatment")}>
          {WKR.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
        </select>
      </Field>
      <Field id="nlc-ev" label="Evidence policy">
        <select id="nlc-ev" className={inputCls} value={form.evidence_policy} onChange={set("evidence_policy")}>
          {EVIDENCE.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </Field>
      <Field id="nlc-from" label="Effective from" required><input id="nlc-from" type="date" className={inputCls} value={form.effective_from} onChange={set("effective_from")} /></Field>
      <fieldset className="col-span-full grid grid-cols-1 gap-2 sm:grid-cols-3">
        <legend className="mb-1 text-[12px] font-semibold text-foreground-secondary">Counts as</legend>
        {FLAGS.map(([k, l]) => (
          <label key={k} className="flex items-center gap-2 text-[12px] text-foreground">
            <input type="checkbox" checked={!!form[k]} onChange={set(k)} /> {l}
          </label>
        ))}
      </fieldset>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save override" onCancel={onCancel} />
    </form>
  );
}

function SchemeForm({ onCancel, onSaved }) {
  const [form, set] = useForm(EMPTY_SCHEME);
  const { run, busy, error, setError } = useAction();

  async function submit(e) {
    e.preventDefault();
    if (!form.fund_name.trim() || !form.scheme_code.trim()) return setError("Fund name and scheme code are required.");
    for (const [k, l] of [["employee_pct", "Employee %"], ["employer_pct", "Employer %"]]) {
      if (!isNumber(form[k]) || Number(form[k]) < 0 || Number(form[k]) > 100) return setError(`${l} must be between 0 and 100.`);
    }
    if (form.franchise_amount && !isNumber(form.franchise_amount)) return setError("The franchise must be an amount.");
    if (form.max_pensionable_salary && !isNumber(form.max_pensionable_salary)) return setError("Max pensionable salary must be an amount.");
    if (!form.effective_from) return setError("Effective from is required.");
    for (const k of ["collective_agreement_id", "evidence_artifact_id"]) {
      if (form[k] && !/^\d+$/.test(String(form[k]).trim())) return setError("Ids must be numbers.");
    }
    if (form.mandatory_sector && !form.evidence_artifact_id) return setError("A mandatory sector scheme needs its applicability evidence document.");
    const payload = {
      ...form, fund_name: form.fund_name.trim(), scheme_code: form.scheme_code.trim(),
      franchise_amount: opt(form.franchise_amount) || "0", max_pensionable_salary: opt(form.max_pensionable_salary),
      collective_agreement_id: form.collective_agreement_id ? Number(form.collective_agreement_id) : null,
      evidence_artifact_id: form.evidence_artifact_id ? Number(form.evidence_artifact_id) : null,
    };
    const res = await run(() => createNlPensionScheme(payload));
    if (res.ok) onSaved("Pension scheme recorded for your organization.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="New pension scheme">
      <Field id="nlp-fund" label="Fund name" required><input id="nlp-fund" className={inputCls} value={form.fund_name} onChange={set("fund_name")} /></Field>
      <Field id="nlp-code" label="Scheme code" required><input id="nlp-code" className={inputCls} value={form.scheme_code} onChange={set("scheme_code")} /></Field>
      <Field id="nlp-basis" label="Basis rule" required>
        <select id="nlp-basis" className={inputCls} value={form.basis_rule} onChange={set("basis_rule")}>
          <option value="GROSS_MINUS_FRANCHISE">Gross minus franchise</option><option value="CAPPED_PENSIONABLE">Capped pensionable</option>
        </select>
      </Field>
      <Field id="nlp-fr" label="Franchise (annual, €)"><input id="nlp-fr" inputMode="decimal" className={inputCls} value={form.franchise_amount} onChange={set("franchise_amount")} /></Field>
      <Field id="nlp-max" label="Max pensionable salary (€)"><input id="nlp-max" inputMode="decimal" className={inputCls} value={form.max_pensionable_salary} onChange={set("max_pensionable_salary")} /></Field>
      <Field id="nlp-ee" label="Employee %" required><input id="nlp-ee" inputMode="decimal" className={inputCls} value={form.employee_pct} onChange={set("employee_pct")} /></Field>
      <Field id="nlp-er" label="Employer %" required><input id="nlp-er" inputMode="decimal" className={inputCls} value={form.employer_pct} onChange={set("employer_pct")} /></Field>
      <Field id="nlp-from" label="Effective from" required><input id="nlp-from" type="date" className={inputCls} value={form.effective_from} onChange={set("effective_from")} /></Field>
      <Field id="nlp-cao" label="CAO id"><input id="nlp-cao" inputMode="numeric" className={inputCls} value={form.collective_agreement_id} onChange={set("collective_agreement_id")} /></Field>
      <Field id="nlp-ev" label="Evidence document id"><input id="nlp-ev" inputMode="numeric" className={inputCls} value={form.evidence_artifact_id} onChange={set("evidence_artifact_id")} /></Field>
      <label className="flex items-center gap-2 self-end pb-2 text-[12px] text-foreground">
        <input type="checkbox" checked={form.mandatory_sector} onChange={set("mandatory_sector")} /> Mandatory sector scheme
      </label>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save scheme" onCancel={onCancel} />
    </form>
  );
}

function CatalogCard({ title, description, addLabel, emptyTitle, emptyText, loader, Form, columns, readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(loader);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState(null);
  const rows = Array.isArray(data) ? data : [];
  return (
    <div className={cardCls}>
      <SectionHeader title={title} description={description}>
        {!readOnly && !creating && (
          <button type="button" className={btnPrimary} onClick={() => { setCreating(true); setNotice(null); }}>
            <Plus size={13} aria-hidden="true" /> {addLabel}
          </button>
        )}
      </SectionHeader>
      {creating && <Form onCancel={() => setCreating(false)} onSaved={(msg) => { setCreating(false); setNotice(msg); reload(); }} />}
      <div className="mb-3"><Messages notice={notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title={emptyTitle} text={emptyText} />
      ) : (
        <DataTable label={title} rows={rows} columns={columns} />
      )}
    </div>
  );
}

const yes = (v) => (v ? "Yes" : "No");

export default function NetherlandsCatalogSection({ readOnly }) {
  return (
    <div className="space-y-6">
      <CatalogCard
        readOnly={readOnly}
        title="Earning classifications"
        description="The platform catalog plus your own overrides. An override supersedes your open row for the same code from its effective date; an unclassified earning blocks the payslip."
        addLabel="Add override"
        emptyTitle="No earning classifications yet"
        emptyText="The platform catalog has no rows yet. Add an override for any earning code you pay."
        loader={listNlEarningClassifications}
        Form={ClassificationForm}
        columns={[
          { key: "earning_code", label: "Code" },
          { key: "scope", label: "Scope", render: scopeOf },
          { key: "remuneration_type", label: "Type" },
          ...FLAGS.map(([k, l]) => ({ key: k, label: l, render: (r) => yes(r[k]) })),
          { key: "wkr_treatment", label: "WKR", render: (r) => display(r.wkr_treatment).replace(/_/g, " ") },
          { key: "period", label: "Effective", render: (r) => period(r.effective_from, r.effective_to) },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
        ]}
      />
      <CatalogCard
        readOnly={readOnly}
        title="Pension schemes"
        description="Platform catalog schemes plus your organization's own. A mandatory sector scheme needs its applicability evidence."
        addLabel="Add scheme"
        emptyTitle="No pension schemes yet"
        emptyText="Record your pension fund's scheme with its contribution percentages."
        loader={listNlPensionSchemes}
        Form={SchemeForm}
        columns={[
          { key: "fund_name", label: "Fund" },
          { key: "scheme_code", label: "Code" },
          { key: "scope", label: "Scope", render: scopeOf },
          { key: "basis_rule", label: "Basis", render: (r) => display(r.basis_rule).replace(/_/g, " ") },
          { key: "employee_pct", label: "Employee %" },
          { key: "employer_pct", label: "Employer %" },
          { key: "mandatory_sector", label: "Mandatory", render: (r) => yes(r.mandatory_sector) },
          { key: "period", label: "Effective", render: (r) => period(r.effective_from, r.effective_to) },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
        ]}
      />
    </div>
  );
}
