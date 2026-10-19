import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { deleteFilingRecord, getComplianceData, upsertFilingRecord } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnDanger, btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { day, display, opt, pick, when } from "./format";

// Statutory filing-status records (NOT_STARTED → IN_PROGRESS → FILED |
// OVERDUE | BLOCKED). The jurisdiction is always your organization's
// compliance country. Recording the same filing type + period again updates
// the existing record.
const STATUSES = ["NOT_STARTED", "IN_PROGRESS", "FILED", "OVERDUE", "BLOCKED"];
const EMPTY = { filingType: "", periodLabel: "", periodStart: "", periodEnd: "", status: "NOT_STARTED", blockedReason: "" };

// Normalise a record from either GET /api/payroll/filings (dict rows) or the
// PUT response (camelCase).
function normalise(r) {
  if (!r || typeof r !== "object") return null;
  const id = r.id;
  const filingType = pick(r, "filingType", "filing_type");
  if (id === undefined || id === null || !filingType) return null;
  return {
    id, filingType,
    jurisdiction: r.jurisdiction,
    periodLabel: pick(r, "periodLabel", "period_label"),
    periodStart: pick(r, "periodStart", "period_start"),
    periodEnd: pick(r, "periodEnd", "period_end"),
    status: r.status,
    blockedReason: pick(r, "blockedReason", "blocked_reason"),
    submittedAt: pick(r, "submittedAt", "submitted_at"),
    updatedAt: pick(r, "updatedAt", "updated_at"),
  };
}

function FilingForm({ record, onCancel, onSaved }) {
  const [form, setForm] = useState(() => (record ? {
    filingType: record.filingType || "", periodLabel: record.periodLabel || "",
    periodStart: record.periodStart ? day(record.periodStart) : "", periodEnd: record.periodEnd ? day(record.periodEnd) : "",
    status: STATUSES.includes(record.status) ? record.status : "NOT_STARTED", blockedReason: record.blockedReason || "",
  } : EMPTY));
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!form.filingType.trim()) return setError("Filing type is required.");
    if (!form.periodLabel.trim()) return setError("Period label is required.");
    if (form.periodStart && form.periodEnd && form.periodEnd < form.periodStart) return setError("Period end cannot be before period start.");
    if (form.status === "BLOCKED" && !form.blockedReason.trim()) return setError("Give a reason when the filing is blocked.");
    const res = await run(() => upsertFilingRecord({
      filingType: form.filingType.trim(), periodLabel: form.periodLabel.trim(),
      periodStart: form.periodStart || null, periodEnd: form.periodEnd || null, status: form.status,
      blockedReason: form.status === "BLOCKED" ? opt(form.blockedReason) : null,
    }));
    if (res.ok) onSaved(res.data, record ? "Filing record updated." : "Filing record saved.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Filing record">
      <Field id="fil-type" label="Filing type" required><input id="fil-type" className={inputCls} value={form.filingType} onChange={set("filingType")} placeholder="e.g. Form 941, DSN, AGI" disabled={!!record} /></Field>
      <Field id="fil-label" label="Period label" required><input id="fil-label" className={inputCls} value={form.periodLabel} onChange={set("periodLabel")} placeholder="e.g. 2026-Q3" disabled={!!record} /></Field>
      <Field id="fil-status" label="Status" required>
        <select id="fil-status" className={inputCls} value={form.status} onChange={set("status")}>
          {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ").toLowerCase()}</option>)}
        </select>
      </Field>
      <Field id="fil-start" label="Period start"><input id="fil-start" type="date" className={inputCls} value={form.periodStart} onChange={set("periodStart")} /></Field>
      <Field id="fil-end" label="Period end"><input id="fil-end" type="date" className={inputCls} value={form.periodEnd} onChange={set("periodEnd")} /></Field>
      {form.status === "BLOCKED" && (
        <Field id="fil-reason" label="Blocked reason" required><input id="fil-reason" className={inputCls} value={form.blockedReason} onChange={set("blockedReason")} /></Field>
      )}
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel={record ? "Save changes" : "Save record"} onCancel={onCancel} />
    </form>
  );
}

export default function FilingRecordsTab({ readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(getComplianceData);
  // Records saved or updated in this visit, keyed by id, merged over the
  // server list (and hidden once deleted).
  const [local, setLocal] = useState({});
  const [removed, setRemoved] = useState(() => new Set());
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [notice, setNotice] = useState(null);
  const action = useAction();

  const serverRows = (Array.isArray(data?.filings) ? data.filings : []).map(normalise).filter(Boolean);
  const merged = new Map(serverRows.map((r) => [r.id, r]));
  Object.values(local).forEach((r) => merged.set(r.id, r));
  const rows = [...merged.values()].filter((r) => !removed.has(r.id));

  function saved(raw, msg) {
    const rec = normalise(raw);
    if (rec) {
      setLocal((l) => ({ ...l, [rec.id]: rec }));
      setRemoved((s) => { const n = new Set(s); n.delete(rec.id); return n; });
    }
    setEditing(null);
    setNotice(msg);
  }

  async function confirmDelete() {
    setNotice(null);
    const id = deleting.id;
    const res = await action.run(() => deleteFilingRecord(id), "Filing record deleted.");
    setDeleting(null);
    if (res.ok) setRemoved((s) => new Set(s).add(id));
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="Statutory filing records"
        description="Track the status of each statutory filing by period. The jurisdiction is your organization's compliance country; saving the same filing type and period again updates it.">
        {!readOnly && !editing && (
          <button type="button" className={btnPrimary} onClick={() => { setEditing({}); setNotice(null); action.clear(); }}>
            <Plus size={13} aria-hidden="true" /> Record filing
          </button>
        )}
      </SectionHeader>
      {editing && <FilingForm record={editing.id ? editing : null} onCancel={() => setEditing(null)} onSaved={saved} />}
      {deleting && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[14px] border border-error/30 bg-error/5 p-4 dark:bg-error/10">
          <p className="text-[12px] text-foreground">Delete the {deleting.filingType} record for {display(deleting.periodLabel)}? This cannot be undone.</p>
          <div className="flex gap-2">
            <button type="button" className={btnSecondary} onClick={() => setDeleting(null)} disabled={action.busy}>Cancel</button>
            <button type="button" className={btnDanger} onClick={confirmDelete} disabled={action.busy}>{action.busy ? "Deleting…" : "Delete"}</button>
          </div>
        </div>
      )}
      <div className="mb-3"><Messages error={action.error} notice={action.notice || notice} /></div>
      {initialLoading ? <LoadingState /> : error ? <ErrorState message={error} onRetry={reload} /> : rows.length === 0 ? (
        <EmptyState title="No filing records to show"
          text="Records you save here appear in this list. Saving a filing type and period that already exists updates that record." />
      ) : (
        <DataTable label="Filing records" rows={rows} columns={[
          { key: "filingType", label: "Filing" },
          { key: "jurisdiction", label: "Jurisdiction" },
          { key: "periodLabel", label: "Period" },
          { key: "dates", label: "Dates", render: (r) => (r.periodStart || r.periodEnd ? `${day(r.periodStart)} → ${day(r.periodEnd)}` : "—") },
          { key: "status", label: "Status", render: (r) => (
            <span>
              <StatusBadge status={r.status} />
              {r.status === "BLOCKED" && r.blockedReason && <span className="mt-1 block text-[11px] text-foreground-muted">{r.blockedReason}</span>}
            </span>
          ) },
          { key: "submittedAt", label: "Submitted", render: (r) => when(r.submittedAt) },
          { key: "updatedAt", label: "Updated", render: (r) => when(r.updatedAt) },
          { key: "actions", label: "", render: (r) => (readOnly ? null : (
            <div className="flex gap-1.5">
              <button type="button" className={btnSecondary} aria-label={`Edit ${r.filingType} ${r.periodLabel}`} onClick={() => { setEditing(r); setDeleting(null); }}><Pencil size={12} aria-hidden="true" /></button>
              <button type="button" className={btnDanger} aria-label={`Delete ${r.filingType} ${r.periodLabel}`} onClick={() => { setDeleting(r); setEditing(null); }}><Trash2 size={12} aria-hidden="true" /></button>
            </div>
          )) },
        ]} />
      )}
    </div>
  );
}
