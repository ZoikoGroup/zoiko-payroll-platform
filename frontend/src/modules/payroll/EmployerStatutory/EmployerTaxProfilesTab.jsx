import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { deleteEmployerTaxProfile, listEmployerTaxProfiles, upsertEmployerTaxProfile } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnDanger, btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader,
} from "./ui";
import { display, isNumber, opt, period } from "./format";

// Employer-specific, agency-assigned rates (US SUI and similar). Enter them
// from your actual rate notice — never a guessed state default.
const COMPONENTS = {
  US: ["SUI", "ETT", "WF", "JDA", "FAMLI", "PFML", "PAID_LEAVE"],
  CA: ["WCB"],
  AU: ["AU_WORKERS_COMP"],
};
// Headcount-only programs carry no wage base / rate — only covered headcount.
const HEADCOUNT_ONLY = new Set(["FAMLI", "PFML", "PAID_LEAVE"]);
const RATE_SOURCES = { EMPLOYER_NOTICE: "Employer rate notice", NEW_EMPLOYER: "New-employer rate", STATE_DEFAULT: "State default" };
const REIMBURSABLE = { CONTRIBUTORY: "Contributory", REIMBURSING: "Reimbursing" };

function ProfileForm({ profile, country, organizationId, onCancel, onSaved }) {
  const options = COMPONENTS[country] || COMPONENTS.US;
  const [form, setForm] = useState(() => ({
    jurisdictionId: profile?.jurisdictionId || `${country}-`,
    componentCode: profile?.componentCode || options[0],
    taxableWageBase: profile?.taxableWageBase ?? "", employerRatePct: profile?.employerRatePct ?? "",
    assessmentRatePct: profile?.assessmentRatePct ?? "", coveredEmployeeCount: profile?.coveredEmployeeCount ?? "",
    rateSource: profile?.rateSource || "EMPLOYER_NOTICE", effectiveFrom: profile?.effectiveFrom || "",
    effectiveTo: profile?.effectiveTo || "", agencyAccountId: profile?.agencyAccountId || "",
    reimbursableStatus: profile?.reimbursableStatus || "CONTRIBUTORY", sourceDocumentId: profile?.sourceDocumentId ?? "",
  }));
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const headcountOnly = HEADCOUNT_ONLY.has(form.componentCode);

  async function submit(e) {
    e.preventDefault();
    const jurisdiction = form.jurisdictionId.trim().toUpperCase();
    if (!/^[A-Z]{2}-[A-Z0-9]{2,3}$/.test(jurisdiction)) return setError(`Jurisdiction must look like ${country}-CA (country and state/province code).`);
    if (!form.effectiveFrom) return setError("Effective from is required.");
    if (form.effectiveTo && form.effectiveTo < form.effectiveFrom) return setError("Effective to cannot be before effective from.");
    if (headcountOnly) {
      if (form.coveredEmployeeCount === "" || !Number.isInteger(Number(form.coveredEmployeeCount)) || Number(form.coveredEmployeeCount) < 0) {
        return setError("Covered employees is required for this program (a whole number).");
      }
    } else {
      if (!isNumber(form.taxableWageBase) || Number(form.taxableWageBase) < 0) return setError("Taxable wage base is required.");
      if (!isNumber(form.employerRatePct) || Number(form.employerRatePct) < 0 || Number(form.employerRatePct) > 100) return setError("Employer rate % is required (0–100).");
    }
    if (form.assessmentRatePct !== "" && !isNumber(form.assessmentRatePct)) return setError("Assessment rate % must be a number.");
    if (form.sourceDocumentId !== "" && !/^\d+$/.test(String(form.sourceDocumentId))) return setError("Source document ID must be a number.");
    const payload = {
      id: profile?.id ?? null,
      // Required by the request schema; the server always replaces it with
      // the organization from your login.
      organizationId: organizationId ?? 0,
      jurisdictionId: jurisdiction, componentCode: form.componentCode,
      taxableWageBase: headcountOnly ? null : String(form.taxableWageBase),
      employerRatePct: headcountOnly ? null : String(form.employerRatePct),
      assessmentRatePct: form.assessmentRatePct === "" ? null : String(form.assessmentRatePct),
      coveredEmployeeCount: form.coveredEmployeeCount === "" ? null : Number(form.coveredEmployeeCount),
      rateSource: form.rateSource, effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || null,
      agencyAccountId: opt(form.agencyAccountId), reimbursableStatus: form.reimbursableStatus,
      sourceDocumentId: form.sourceDocumentId === "" ? null : Number(form.sourceDocumentId),
    };
    const res = await run(() => upsertEmployerTaxProfile(payload));
    if (res.ok) onSaved(profile ? "Employer tax profile updated." : "Employer tax profile added.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Employer tax profile">
      <Field id="etp-jur" label="Jurisdiction" required><input id="etp-jur" className={inputCls} value={form.jurisdictionId} onChange={set("jurisdictionId")} placeholder={`${country}-CA`} /></Field>
      <Field id="etp-comp" label="Component" required>
        <select id="etp-comp" className={inputCls} value={form.componentCode} onChange={set("componentCode")}>
          {options.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </select>
      </Field>
      {headcountOnly ? (
        <Field id="etp-count" label="Covered employees" required><input id="etp-count" type="number" min="0" className={inputCls} value={form.coveredEmployeeCount} onChange={set("coveredEmployeeCount")} /></Field>
      ) : (
        <>
          <Field id="etp-base" label="Taxable wage base" required><input id="etp-base" inputMode="decimal" className={inputCls} value={form.taxableWageBase} onChange={set("taxableWageBase")} /></Field>
          <Field id="etp-rate" label="Employer rate %" required><input id="etp-rate" inputMode="decimal" className={inputCls} value={form.employerRatePct} onChange={set("employerRatePct")} /></Field>
          <Field id="etp-assess" label="Assessment rate %"><input id="etp-assess" inputMode="decimal" className={inputCls} value={form.assessmentRatePct} onChange={set("assessmentRatePct")} /></Field>
        </>
      )}
      <Field id="etp-src" label="Rate source">
        <select id="etp-src" className={inputCls} value={form.rateSource} onChange={set("rateSource")}>
          {Object.entries(RATE_SOURCES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field id="etp-reimb" label="Reimbursable status">
        <select id="etp-reimb" className={inputCls} value={form.reimbursableStatus} onChange={set("reimbursableStatus")}>
          {Object.entries(REIMBURSABLE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field id="etp-from" label="Effective from" required><input id="etp-from" type="date" className={inputCls} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
      <Field id="etp-to" label="Effective to"><input id="etp-to" type="date" className={inputCls} value={form.effectiveTo} onChange={set("effectiveTo")} /></Field>
      <Field id="etp-acct" label="Agency account ID"><input id="etp-acct" className={inputCls} value={form.agencyAccountId} onChange={set("agencyAccountId")} /></Field>
      <Field id="etp-doc" label="Source document ID"><input id="etp-doc" inputMode="numeric" className={inputCls} value={form.sourceDocumentId} onChange={set("sourceDocumentId")} /></Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel={profile ? "Save changes" : "Add profile"} onCancel={onCancel} />
    </form>
  );
}

export default function EmployerTaxProfilesTab({ readOnly, country = "US", organizationId }) {
  const { data, error, initialLoading, reload } = useLoad(() => listEmployerTaxProfiles());
  const [editing, setEditing] = useState(null);   // null | {} | profile
  const [deleting, setDeleting] = useState(null);
  const [notice, setNotice] = useState(null);
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];
  const done = (msg) => { setEditing(null); setNotice(msg); reload(); };

  async function confirmDelete() {
    setNotice(null);
    const res = await action.run(() => deleteEmployerTaxProfile(deleting.id), "Employer tax profile deleted.");
    setDeleting(null);
    if (res.ok) reload();
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="Employer tax profiles"
        description="Agency-assigned, employer-specific rates (for example State Unemployment Insurance). Enter them from your actual rate notice.">
        {!readOnly && !editing && (
          <button type="button" className={btnPrimary} onClick={() => { setEditing({}); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> Add profile
          </button>
        )}
      </SectionHeader>
      {editing && (
        <ProfileForm profile={editing.id ? editing : null} country={country} organizationId={organizationId}
          onCancel={() => setEditing(null)} onSaved={done} />
      )}
      {deleting && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[14px] border border-error/30 bg-error/5 p-4 dark:bg-error/10">
          <p className="text-[12px] text-foreground">Delete the {deleting.componentCode} profile for {deleting.jurisdictionId}? This cannot be undone.</p>
          <div className="flex gap-2">
            <button type="button" className={btnSecondary} onClick={() => setDeleting(null)} disabled={action.busy}>Cancel</button>
            <button type="button" className={btnDanger} onClick={confirmDelete} disabled={action.busy}>{action.busy ? "Deleting…" : "Delete"}</button>
          </div>
        </div>
      )}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No employer tax profiles configured yet" text="Add your agency-assigned rate for each state you pay in." />
      ) : (
        <DataTable label="Employer tax profiles" rows={rows} columns={[
          { key: "jurisdictionId", label: "Jurisdiction" },
          { key: "componentCode", label: "Component" },
          { key: "taxableWageBase", label: "Wage base" },
          { key: "employerRatePct", label: "Employer rate", render: (p) => (p.employerRatePct != null ? `${p.employerRatePct}%` : "—") },
          { key: "coveredEmployeeCount", label: "Covered employees" },
          { key: "rateSource", label: "Source", render: (p) => RATE_SOURCES[p.rateSource] || display(p.rateSource) },
          { key: "period", label: "Effective", render: (p) => period(p.effectiveFrom, p.effectiveTo) },
          { key: "agencyAccountId", label: "Agency account" },
          { key: "actions", label: "", render: (p) => (readOnly ? null : (
            <div className="flex gap-1.5">
              <button type="button" className={btnSecondary} aria-label={`Edit ${p.componentCode} ${p.jurisdictionId}`} onClick={() => { setEditing(p); setDeleting(null); }}><Pencil size={12} aria-hidden="true" /></button>
              <button type="button" className={btnDanger} aria-label={`Delete ${p.componentCode} ${p.jurisdictionId}`} onClick={() => { setDeleting(p); setEditing(null); }}><Trash2 size={12} aria-hidden="true" /></button>
            </div>
          )) },
        ]} />
      )}
    </div>
  );
}
