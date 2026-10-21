import { useState } from "react";
import { Pencil, Plus } from "lucide-react";
import { listCollectiveAgreements, setCollectiveAgreementStatus, upsertCollectiveAgreement } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls, labelCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { opt, period } from "./format";

// Collective-agreement assignments. Definitions with no organization are the
// platform catalog (read-only here); your own assignments move Draft → In
// Review → Approved → Active, with a distinct approver and activator
// enforced by the server.
const TYPES = ["EMPLOYER_SPECIFIC", "SECTOR", "LOCAL_SUPPLEMENT"];
const MODULES = [
  "wage_scales", "overtime", "unsocial_hours", "sickness_supplements", "parental_pay",
  "vacation_enhancement", "occupational_pension", "insurance", "termination",
];
const NEXT = {
  Draft: [["In Review", "Submit for review"]],
  "In Review": [["Approved", "Approve"], ["Draft", "Return to Draft"]],
  Approved: [["Active", "Activate"], ["Draft", "Return to Draft"]],
  Active: [["Superseded", "Supersede"]],
};
const EMPTY = {
  agreementCode: "", name: "", agreementType: "EMPLOYER_SPECIFIC", employerScope: "", employeeGroup: "",
  occupation: "", grade: "", version: "1.0", effectiveFrom: "", effectiveTo: "", modules: [], sourceDocumentId: "",
  notes: "", reason: "",
};

function AgreementForm({ agreement, country, organizationId, onCancel, onSaved }) {
  const [form, setForm] = useState(() => (agreement ? {
    ...EMPTY, ...agreement,
    employerScope: agreement.employerScope || "", employeeGroup: agreement.employeeGroup || "",
    occupation: agreement.occupation || "", grade: agreement.grade || "", notes: agreement.notes || "",
    effectiveFrom: agreement.effectiveFrom || "", effectiveTo: agreement.effectiveTo || "",
    sourceDocumentId: agreement.sourceDocumentId ?? "", modules: agreement.modules || [], reason: "",
  } : EMPTY));
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const toggle = (m) => setForm((f) => ({ ...f, modules: f.modules.includes(m) ? f.modules.filter((x) => x !== m) : [...f.modules, m] }));

  async function submit(e) {
    e.preventDefault();
    if (!form.agreementCode.trim()) return setError("Agreement code is required.");
    if (!form.name.trim()) return setError("Name is required.");
    if (!String(form.version || "").trim()) return setError("Version is required.");
    if (form.effectiveFrom && form.effectiveTo && form.effectiveTo < form.effectiveFrom) return setError("Effective to cannot be before effective from.");
    if (form.sourceDocumentId !== "" && !/^\d+$/.test(String(form.sourceDocumentId))) return setError("Source evidence artifact ID must be a number.");
    const res = await run(() => upsertCollectiveAgreement({
      id: agreement?.id ?? null, jurisdictionCountry: country, organizationId: organizationId ?? null,
      agreementCode: form.agreementCode.trim(), name: form.name.trim(), agreementType: form.agreementType,
      employerScope: opt(form.employerScope), employeeGroup: opt(form.employeeGroup), occupation: opt(form.occupation),
      grade: opt(form.grade), version: String(form.version).trim(),
      effectiveFrom: form.effectiveFrom || null, effectiveTo: form.effectiveTo || null, modules: form.modules,
      sourceDocumentId: form.sourceDocumentId === "" ? null : Number(form.sourceDocumentId),
      notes: opt(form.notes), reason: opt(form.reason),
    }));
    if (res.ok) onSaved("Agreement saved as Draft.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Collective agreement">
      <Field id="cba-code" label="Agreement code" required><input id="cba-code" className={inputCls} value={form.agreementCode} onChange={set("agreementCode")} disabled={!!agreement} /></Field>
      <Field id="cba-version" label="Version" required><input id="cba-version" className={inputCls} value={form.version} onChange={set("version")} /></Field>
      <Field id="cba-type" label="Type" required>
        <select id="cba-type" className={inputCls} value={form.agreementType} onChange={set("agreementType")}>
          {TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ").toLowerCase()}</option>)}
        </select>
      </Field>
      <Field id="cba-name" label="Name" required className="sm:col-span-2 lg:col-span-3"><input id="cba-name" className={inputCls} value={form.name} onChange={set("name")} /></Field>
      <Field id="cba-scope" label="Employer scope"><input id="cba-scope" className={inputCls} value={form.employerScope} onChange={set("employerScope")} /></Field>
      <Field id="cba-group" label="Employee group"><input id="cba-group" className={inputCls} value={form.employeeGroup} onChange={set("employeeGroup")} /></Field>
      <Field id="cba-occ" label="Occupation"><input id="cba-occ" className={inputCls} value={form.occupation} onChange={set("occupation")} /></Field>
      <Field id="cba-grade" label="Grade"><input id="cba-grade" className={inputCls} value={form.grade} onChange={set("grade")} /></Field>
      <Field id="cba-from" label="Effective from" hint="Required before it can go Active."><input id="cba-from" type="date" className={inputCls} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
      <Field id="cba-to" label="Effective to"><input id="cba-to" type="date" className={inputCls} value={form.effectiveTo} onChange={set("effectiveTo")} /></Field>
      <Field id="cba-src" label="Source evidence artifact ID" hint="Required before it can go Active."><input id="cba-src" inputMode="numeric" className={inputCls} value={form.sourceDocumentId} onChange={set("sourceDocumentId")} /></Field>
      <fieldset className="col-span-full">
        <legend className={labelCls}>Configured modules (an agreement with none has no payroll effect)</legend>
        <div className="flex flex-wrap gap-2">
          {MODULES.map((m) => (
            <label key={m} className="flex items-center gap-1.5 rounded-[10px] border border-border px-2 py-1 text-[12px] text-foreground-secondary">
              <input type="checkbox" checked={form.modules.includes(m)} onChange={() => toggle(m)} /> {m.replace(/_/g, " ")}
            </label>
          ))}
        </div>
      </fieldset>
      <Field id="cba-notes" label="Notes" className="col-span-full"><textarea id="cba-notes" rows={2} className={inputCls} value={form.notes} onChange={set("notes")} /></Field>
      <Field id="cba-reason" label="Reason (recorded in the audit trail)" className="col-span-full"><input id="cba-reason" className={inputCls} value={form.reason} onChange={set("reason")} /></Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save draft" onCancel={onCancel} />
    </form>
  );
}

function AgreementList({ country, readOnly, organizationId }) {
  const { data, error, initialLoading, reload } = useLoad(() => listCollectiveAgreements(country));
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState(null);
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];
  const own = (r) => r.organizationId !== null && r.organizationId !== undefined;

  async function move(row, status) {
    setNotice(null);
    const res = await action.run(() => setCollectiveAgreementStatus(row.id, status), `${row.agreementCode} v${row.version} → ${status}.`);
    if (res.ok) reload();
  }

  return (
    <>
      {!readOnly && !editing && (
        <div className="mb-3 flex justify-end">
          <button type="button" className={btnPrimary} onClick={() => { setEditing({}); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> New agreement assignment
          </button>
        </div>
      )}
      {editing && (
        <AgreementForm agreement={editing.id ? editing : null} country={country} organizationId={organizationId}
          onCancel={() => setEditing(null)} onSaved={(msg) => { setEditing(null); setNotice(msg); reload(); }} />
      )}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title={`No collective agreements for ${country}`} text="Employers without an agreement resolve to an explicit NONE — this is correct until a certified agreement is added." />
      ) : (
        <DataTable label="Collective agreements" rows={rows} columns={[
          { key: "code", label: "Code", render: (r) => <span className="font-mono">{r.agreementCode} v{r.version}</span> },
          { key: "name", label: "Name" },
          { key: "agreementType", label: "Type", render: (r) => String(r.agreementType || "—").replace(/_/g, " ").toLowerCase() },
          { key: "owner", label: "Owner", render: (r) => (own(r) ? "Your organization" : "Platform catalog") },
          { key: "period", label: "Effective", render: (r) => (r.effectiveFrom ? period(r.effectiveFrom, r.effectiveTo) : "—") },
          { key: "modules", label: "Modules", render: (r) => (Array.isArray(r.modules) && r.modules.length ? r.modules.map((m) => m.replace(/_/g, " ")).join(", ") : "none") },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "actions", label: "", render: (r) => (readOnly || !own(r) ? null : (
            <div className="flex flex-wrap gap-1.5">
              {r.status === "Draft" && (
                <button type="button" className={btnSecondary} onClick={() => setEditing(r)}><Pencil size={12} aria-hidden="true" /> Edit</button>
              )}
              {(NEXT[r.status] || []).map(([status, label]) => (
                <button key={status} type="button" className={btnSecondary} disabled={action.busy} onClick={() => move(r, status)}>{label}</button>
              ))}
            </div>
          )) },
        ]} />
      )}
    </>
  );
}

export default function CollectiveAgreementsTab({ readOnly, country, organizationId }) {
  const [selected, setSelected] = useState(country || "SE");
  const [draft, setDraft] = useState(country || "SE");
  const code = (selected || "").toUpperCase();

  return (
    <div className={cardCls}>
      <SectionHeader title="Collective agreements"
        description="Agreement definitions from the platform catalog plus your organization's own assignments. Wage floors and supplements come only from an Active agreement.">
        {!country && (
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (/^[A-Za-z]{2}$/.test(draft.trim())) setSelected(draft.trim().toUpperCase()); }}>
            <Field id="cba-country" label="Country code">
              <input id="cba-country" className={`${inputCls} w-20 uppercase`} maxLength={2} value={draft} onChange={(e) => setDraft(e.target.value)} />
            </Field>
            <button type="submit" className={btnSecondary}>Show</button>
          </form>
        )}
      </SectionHeader>
      {code === "CH" ? (
        <EmptyState title="Swiss wage floors are governed separately" text="Swiss collective-agreement wage floors are not managed here." />
      ) : (
        <AgreementList key={code} country={code} readOnly={readOnly} organizationId={organizationId} />
      )}
    </div>
  );
}
