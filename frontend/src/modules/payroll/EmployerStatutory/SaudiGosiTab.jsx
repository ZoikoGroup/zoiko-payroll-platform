import { useState } from "react";
import { Plus } from "lucide-react";
import {
  approveSaEmployerProfile, createSaEmployerProfile, listSaEmployerProfiles, listSaGosiLiabilities, markSaGosiLiabilityPaid,
} from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { display, isNumber, opt, period, pick, today, when } from "./format";

// The Saudi endpoints serialize by their snake_case alias
// (effective_from, gosi_employer_code, …) — read fields through pick().

const EMPTY = {
  effectiveFrom: today(), gosiEmployerCode: "", branchCode: "", activityCode: "", riskCategory: "",
  occupationalHazardRatePct: "", sanedEmployerRatePct: "", pensionEmployerRatePct: "",
};
const RATE_FIELDS = [
  ["occupationalHazardRatePct", "Occupational hazard employer rate %"],
  ["sanedEmployerRatePct", "SANED employer rate %"],
  ["pensionEmployerRatePct", "Pension employer rate %"],
];

function ProfileForm({ onCancel, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!form.gosiEmployerCode.trim()) return setError("The GOSI employer code is required.");
    if (!form.effectiveFrom) return setError("Effective from is required.");
    for (const [key, label] of RATE_FIELDS) {
      if (form[key] !== "" && (!isNumber(form[key]) || Number(form[key]) < 0 || Number(form[key]) > 100)) {
        return setError(`${label} must be between 0 and 100.`);
      }
    }
    const payload = {
      effectiveFrom: form.effectiveFrom, gosiEmployerCode: form.gosiEmployerCode.trim(),
      branchCode: opt(form.branchCode), activityCode: opt(form.activityCode), riskCategory: opt(form.riskCategory),
    };
    RATE_FIELDS.forEach(([key]) => { payload[key] = form[key] === "" ? null : Number(form[key]); });
    const res = await run(() => createSaEmployerProfile(payload));
    if (res.ok) onSaved("Draft registration recorded — a different colleague approves it.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 md:grid-cols-3" aria-label="New GOSI employer registration">
      <Field id="sa-code" label="GOSI employer number" required><input id="sa-code" inputMode="numeric" className={inputCls} value={form.gosiEmployerCode} onChange={set("gosiEmployerCode")} required /></Field>
      <Field id="sa-from" label="Effective from" required><input id="sa-from" type="date" className={inputCls} value={form.effectiveFrom} onChange={set("effectiveFrom")} required /></Field>
      <Field id="sa-branch" label="Branch code"><input id="sa-branch" className={inputCls} value={form.branchCode} onChange={set("branchCode")} /></Field>
      <Field id="sa-activity" label="Activity code"><input id="sa-activity" className={inputCls} value={form.activityCode} onChange={set("activityCode")} /></Field>
      <Field id="sa-risk" label="Risk category"><input id="sa-risk" className={inputCls} value={form.riskCategory} onChange={set("riskCategory")} /></Field>
      {RATE_FIELDS.map(([key, label]) => (
        <Field key={key} id={`sa-${key}`} label={label}>
          <input id={`sa-${key}`} type="number" step="0.01" min="0" max="100" className={inputCls} value={form[key]} onChange={set(key)} />
        </Field>
      ))}
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save draft" onCancel={onCancel} />
    </form>
  );
}

function ProfilesCard({ readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(listSaEmployerProfiles);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState(null);
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];

  async function approve(id) {
    setNotice(null);
    const res = await action.run(() => approveSaEmployerProfile(id), "Registration approved.");
    if (res.ok) reload();
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="GOSI employer registration"
        description="Effective-dated GOSI registration versions. Only one DRAFT at a time; a different colleague approves it.">
        {!readOnly && !creating && (
          <button type="button" className={btnPrimary} onClick={() => { setCreating(true); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> New registration version
          </button>
        )}
      </SectionHeader>
      {creating && <ProfileForm onCancel={() => setCreating(false)} onSaved={(msg) => { setCreating(false); setNotice(msg); reload(); }} />}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No GOSI employer registration yet" text="Record your GOSI employer number to start." />
      ) : (
        <DataTable label="GOSI employer registrations" rows={rows} columns={[
          { key: "code", label: "GOSI employer #", render: (r) => display(pick(r, "gosiEmployerCode", "gosi_employer_code")) },
          { key: "branch", label: "Branch", render: (r) => display(pick(r, "branchCode", "branch_code")) },
          { key: "activity", label: "Activity", render: (r) => display(pick(r, "activityCode", "activity_code")) },
          { key: "risk", label: "Risk category", render: (r) => display(pick(r, "riskCategory", "risk_category")) },
          { key: "period", label: "Effective", render: (r) => period(pick(r, "effectiveFrom", "effective_from"), pick(r, "effectiveTo", "effective_to")) },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "created", label: "Recorded", render: (r) => when(pick(r, "createdAt", "created_at")) },
          { key: "actions", label: "", render: (r) => (!readOnly && r.status === "DRAFT" ? (
            <button type="button" className={btnSecondary} disabled={action.busy} onClick={() => approve(r.id)}>Approve</button>
          ) : null) },
        ]} />
      )}
    </div>
  );
}

const money = (v) => (v === null || v === undefined || v === "" ? "—" : `SAR ${v}`);

function LiabilitiesCard({ readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(listSaGosiLiabilities);
  const [paying, setPaying] = useState(null);
  const [reference, setReference] = useState("");
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];

  async function markPaid(e) {
    e.preventDefault();
    if (!reference.trim()) return action.setError("Enter the payment reference from your GOSI payment.");
    const res = await action.run(() => markSaGosiLiabilityPaid(paying.id, reference.trim()), "Liability marked paid.");
    if (res.ok) { setPaying(null); setReference(""); reload(); }
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="Monthly GOSI liabilities"
        description="Pension, SANED and occupational hazard totals built from committed payroll runs. Mark a liability paid once you have settled it with GOSI." />
      {paying && (
        <form onSubmit={markPaid} className="mb-4 flex flex-wrap items-end gap-3 rounded-[14px] border border-border p-4" aria-label="Mark liability paid">
          <Field id="sa-payref" label={`Payment reference for ${String(pick(paying, "contributionMonth", "contribution_month") || "").slice(0, 7)}`} required>
            <input id="sa-payref" className={inputCls} value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <FormActions busy={action.busy} submitLabel="Mark paid" onCancel={() => { setPaying(null); action.clear(); }} />
        </form>
      )}
      <div className="mb-3"><Messages error={action.error} notice={action.notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No GOSI liabilities yet" text="A liability appears here after a payroll run is committed and its GOSI liability is built." />
      ) : (
        <DataTable label="GOSI liabilities" rows={rows} columns={[
          { key: "month", label: "Month", render: (r) => String(pick(r, "contributionMonth", "contribution_month") || "—").slice(0, 7) },
          { key: "pe", label: "Employee pension", render: (r) => money(pick(r, "pensionEmployee", "pension_employee")) },
          { key: "pr", label: "Employer pension", render: (r) => money(pick(r, "pensionEmployer", "pension_employer")) },
          { key: "se", label: "Employee SANED", render: (r) => money(pick(r, "sanedEmployee", "saned_employee")) },
          { key: "sr", label: "Employer SANED", render: (r) => money(pick(r, "sanedEmployer", "saned_employer")) },
          { key: "oh", label: "Occ. hazard", render: (r) => money(pick(r, "occupationalHazardEmployer", "occupational_hazard_employer")) },
          { key: "total", label: "Total due", render: (r) => <span className="font-semibold">{money(pick(r, "totalDue", "total_due"))}</span> },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "paid", label: "Paid", render: (r) => {
            const ref = pick(r, "paymentReference", "payment_reference");
            const at = pick(r, "paidAt", "paid_at");
            return at || ref ? <span>{when(at)}{ref ? <span className="block text-[11px] text-foreground-muted">Ref {ref}</span> : null}</span> : "—";
          } },
          { key: "actions", label: "", render: (r) => (!readOnly && r.status === "DRAFT" ? (
            <button type="button" className={btnSecondary} disabled={action.busy} onClick={() => { setPaying(r); setReference(""); action.clear(); }}>Mark paid</button>
          ) : null) },
        ]} />
      )}
    </div>
  );
}

export default function SaudiGosiTab({ readOnly }) {
  return (
    <div className="space-y-4">
      <ProfilesCard readOnly={readOnly} />
      <LiabilitiesCard readOnly={readOnly} />
    </div>
  );
}
