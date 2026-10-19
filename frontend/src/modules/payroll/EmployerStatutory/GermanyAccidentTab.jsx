import { useState } from "react";
import { Plus } from "lucide-react";
import {
  approveGermanyAccidentProfile, createGermanyAccidentProfile, listGermanyAccidentProfiles, setGermanyAccidentProfileStatus,
} from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { isNumber, opt, period, when } from "./format";

const EMPTY = {
  carrierName: "", agencyAccountId: "", riskClassDescription: "", employerRatePct: "",
  effectiveFrom: `${new Date().getFullYear()}-01-01`, effectiveTo: "", authoritySourceId: "",
};
const BACK = { VERIFIED: "DRAFT", APPROVED: "VERIFIED" };

function CreateForm({ organizationId, onCancel, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!form.carrierName.trim()) return setError("Carrier name is required.");
    if (!isNumber(form.employerRatePct) || Number(form.employerRatePct) < 0 || Number(form.employerRatePct) > 100) {
      return setError("Employer rate must be a percentage between 0 and 100.");
    }
    if (!form.effectiveFrom) return setError("Effective from is required.");
    if (form.effectiveTo && form.effectiveTo < form.effectiveFrom) return setError("Effective to cannot be before effective from.");
    if (form.authoritySourceId && !/^\d+$/.test(form.authoritySourceId.trim())) return setError("Source evidence artifact ID must be a number.");
    const res = await run(() => createGermanyAccidentProfile({
      // Required by the request schema; the server always replaces it with
      // the organization from your login.
      organizationId: organizationId ?? 0,
      carrierName: form.carrierName.trim(), agencyAccountId: opt(form.agencyAccountId),
      riskClassDescription: opt(form.riskClassDescription), employerRatePct: Number(form.employerRatePct),
      effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || null,
      authoritySourceId: form.authoritySourceId ? Number(form.authoritySourceId) : null,
    }));
    if (res.ok) onSaved("Draft profile recorded. Verify it, then a different colleague approves it before publishing.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 md:grid-cols-2" aria-label="New accident-insurance profile">
      <Field id="de-carrier" label="Carrier (Berufsgenossenschaft)" required><input id="de-carrier" className={inputCls} value={form.carrierName} onChange={set("carrierName")} required /></Field>
      <Field id="de-account" label="Member / account number (Mitgliedsnummer)"><input id="de-account" className={inputCls} value={form.agencyAccountId} onChange={set("agencyAccountId")} /></Field>
      <Field id="de-risk" label="Risk class (Gefahrtarifstelle)"><input id="de-risk" className={inputCls} value={form.riskClassDescription} onChange={set("riskClassDescription")} /></Field>
      <Field id="de-rate" label="Employer rate % (from the annual notice)" required><input id="de-rate" type="number" step="0.0001" min="0" max="100" className={inputCls} value={form.employerRatePct} onChange={set("employerRatePct")} required /></Field>
      <Field id="de-from" label="Effective from" required><input id="de-from" type="date" className={inputCls} value={form.effectiveFrom} onChange={set("effectiveFrom")} required /></Field>
      <Field id="de-to" label="Effective to (blank if open-ended)"><input id="de-to" type="date" className={inputCls} value={form.effectiveTo} onChange={set("effectiveTo")} /></Field>
      <Field id="de-source" label="Source evidence artifact ID" hint="Your Beitragsbescheid. Required before the profile can be published.">
        <input id="de-source" inputMode="numeric" className={inputCls} value={form.authoritySourceId} onChange={set("authoritySourceId")} />
      </Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save draft" onCancel={onCancel} />
    </form>
  );
}

export default function GermanyAccidentTab({ readOnly, organizationId }) {
  const { data, error, initialLoading, reload } = useLoad(listGermanyAccidentProfiles);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState(null);
  const action = useAction();
  const rows = Array.isArray(data) ? data : [];

  const act = async (fn, msg) => { setNotice(null); const res = await action.run(fn, msg); if (res.ok) reload(); };

  return (
    <div className={cardCls}>
      <SectionHeader title="Accident insurance (Unfallversicherung)"
        description="Your Berufsgenossenschaft-assigned employer rate. Each version goes DRAFT → VERIFIED → APPROVED (by a different colleague) → PUBLISHED. It is assessed annually — no monthly payslip deduction is computed from it.">
        {!readOnly && !creating && (
          <button type="button" className={btnPrimary} onClick={() => { setCreating(true); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> New profile version
          </button>
        )}
      </SectionHeader>
      {creating && (
        <CreateForm organizationId={organizationId} onCancel={() => setCreating(false)}
          onSaved={(msg) => { setCreating(false); setNotice(msg); reload(); }} />
      )}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No accident-insurance profile configured yet" text="Record the rate from your carrier's latest annual notice." />
      ) : (
        <DataTable label="Accident-insurance profiles" rows={rows} columns={[
          { key: "carrierName", label: "Carrier" },
          { key: "agencyAccountId", label: "Member no." },
          { key: "riskClassDescription", label: "Risk class" },
          { key: "employerRatePct", label: "Rate %" },
          { key: "period", label: "Effective", render: (r) => period(r.effectiveFrom, r.effectiveTo) },
          { key: "source", label: "Evidence", render: (r) => (r.authoritySourceId ? `#${r.authoritySourceId}` : <span className="text-warning">missing</span>) },
          { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "createdAt", label: "Recorded", render: (r) => when(r.createdAt) },
          { key: "actions", label: "", render: (r) => {
            if (readOnly) return null;
            const back = BACK[r.status];
            return (
              <div className="flex flex-wrap gap-1.5">
                {r.status === "DRAFT" && (
                  <button type="button" className={btnSecondary} disabled={action.busy}
                    onClick={() => act(() => setGermanyAccidentProfileStatus(r.id, "VERIFIED"), "Profile verified.")}>Verify</button>
                )}
                {r.status === "VERIFIED" && (
                  <button type="button" className={btnSecondary} disabled={action.busy}
                    onClick={() => act(() => approveGermanyAccidentProfile(r.id), "Profile approved.")}>Approve</button>
                )}
                {r.status === "APPROVED" && (
                  <button type="button" className={btnPrimary} disabled={action.busy || !r.authoritySourceId}
                    title={r.authoritySourceId ? undefined : "A source evidence artifact is required to publish"}
                    onClick={() => act(() => setGermanyAccidentProfileStatus(r.id, "PUBLISHED"), "Profile published.")}>Publish</button>
                )}
                {r.status === "PUBLISHED" && (
                  <button type="button" className={btnSecondary} disabled={action.busy}
                    onClick={() => act(() => setGermanyAccidentProfileStatus(r.id, "SUPERSEDED"), "Profile superseded.")}>Supersede</button>
                )}
                {back && (
                  <button type="button" className={btnSecondary} disabled={action.busy}
                    onClick={() => act(() => setGermanyAccidentProfileStatus(r.id, back), `Sent back to ${back}.`)}>Send back</button>
                )}
              </div>
            );
          } },
        ]} />
      )}
    </div>
  );
}
