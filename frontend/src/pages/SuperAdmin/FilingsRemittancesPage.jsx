import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, RefreshCcw, Info, AlertTriangle, Plus, Pencil, Trash2 } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import Modal from "../../components/Modal";
import { useToast } from "../../context/ToastContext";
import {
  listFilingsRemittances,
  upsertStatutoryFiling,
  deleteStatutoryFiling,
} from "../../service/commandCenterService";

// Germany ELSTER transport states + the manual StatutoryFiling workflow
// states (NOT_STARTED -> IN_PROGRESS -> FILED | OVERDUE | BLOCKED). Both
// vocabularies render through the same pill map.
const STATUS_PILL_MAP = {
  DRAFT: "inactive",
  VALIDATED: "pending",
  BLOCKED_EXTERNAL: "rejected",
  QUEUED: "pending",
  TRANSMITTED: "approved",
  ACKNOWLEDGED: "active",
  REJECTED: "rejected",
  NOT_STARTED: "inactive",
  IN_PROGRESS: "pending",
  FILED: "approved",
  OVERDUE: "rejected",
  BLOCKED: "rejected",
};

// Rows that genuinely need a human: blocked/rejected (either source) or
// overdue. This is what the red accent + "needs attention" count badge flag,
// and it is deliberately disjoint from the muted "no filing records yet"
// empty-state — informational is never styled as actionable.
const ACTIONABLE_STATUSES = new Set(["BLOCKED_EXTERNAL", "REJECTED", "BLOCKED", "OVERDUE"]);

// Sentinel for an org that is under a jurisdiction but has no filing records
// at all — rendered muted/informational, never as "filed", never as a gap.
const NO_FILINGS_STATUS = "NO_FILINGS";

// Manual StatutoryFiling workflow statuses the dashboard can record. Germany
// ELSTER states are transport-lived and stay on that side of the UI.
const RECORDABLE_STATUSES = ["NOT_STARTED", "IN_PROGRESS", "FILED", "OVERDUE", "BLOCKED"];

const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";
const TH_CLS = "px-4 py-3";
const TD_CLS = "px-4 py-3";
const TABLE_WRAP_CLS = "bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto";
const EMPTY_CLS = "flex flex-col items-center justify-center gap-2 px-4 py-10 text-center";

function flattenJurisdictionRows(section) {
  const orgs = section.organizations || (section.filings ? null : []);
  if (orgs === null) {
    // Legacy backend shape (flat `filings`) — keep rendering rather than blank out.
    return (section.filings || []).map((f) => ({ ...f, key: `fil-${f.filing_id ?? f.transmission_id}` }));
  }
  const rows = [];
  for (const org of orgs) {
    if (org.filings?.length > 0) {
      for (const f of org.filings) {
        rows.push({
          ...f,
          org_id: org.org_id,
          org_name: org.org_name,
          orgId: f.organization_id ?? org.org_id,
          key: `fil-${f.filing_id ?? f.transmission_id}`,
        });
      }
    } else {
      rows.push({
        org_name: org.org_name,
        org_id: org.org_id,
        orgId: org.org_id,
        status: NO_FILINGS_STATUS,
        is_empty_state: true,
        key: `org-${org.org_id}`,
      });
    }
  }
  return rows;
}

function filingType(f) {
  return f.filing_type || f.transmission_type || "—";
}

function filingPeriod(f) {
  if (f.period_label) return f.period_label;
  return f.period_start ? `${f.period_start} – ${f.period_end}` : "—";
}

const EMPTY_FORM = {
  orgId: "",
  orgName: "",
  filingType: "",
  periodLabel: "",
  periodStart: "",
  periodEnd: "",
  status: "NOT_STARTED",
  blockedReason: "",
};

export default function FilingsRemittancesPage() {
  const { addToast } = useToast() || {};
  const [data, setData] = useState({ jurisdictions: {}, unconfigured: [], known_gaps: [] });
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [orgOptions, setOrgOptions] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listFilingsRemittances();
      setData(res);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  function openAdd(section) {
    const orgs = section.organizations || [];
    setOrgOptions(orgs.map((o) => ({ id: o.org_id, name: o.org_name })));
    setEditing(false);
    setForm(EMPTY_FORM);
    setShowForm(true);
  }

  function openRecord(org) {
    setOrgOptions([{ id: org.orgId, name: org.org_name }]);
    setEditing(false);
    setForm({ ...EMPTY_FORM, orgId: org.orgId, orgName: org.org_name });
    setShowForm(true);
  }

  function openEdit(row) {
    setOrgOptions([{ id: row.orgId, name: row.org_name }]);
    setEditing(true);
    setForm({
      orgId: row.orgId,
      orgName: row.org_name,
      filingType: row.filing_type || "",
      periodLabel: row.period_label || "",
      periodStart: row.period_start || "",
      periodEnd: row.period_end || "",
      status: RECORDABLE_STATUSES.includes(row.status) ? row.status : "NOT_STARTED",
      blockedReason: row.blocked_reason || "",
    });
    setShowForm(true);
  }

  async function handleSave() {
    if (!form.orgId) {
      addToast?.("Select an organization.", "error");
      return;
    }
    if (!form.filingType.trim() || !form.periodLabel.trim()) {
      addToast?.("Filing Type and Period Label are required.", "error");
      return;
    }
    if (form.periodStart && form.periodEnd && form.periodEnd < form.periodStart) {
      addToast?.("Period End must not be before Period Start.", "error");
      return;
    }
    if (form.status === "BLOCKED" && !form.blockedReason.trim()) {
      addToast?.("A blocked filing needs a reason.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertStatutoryFiling(form.orgId, {
        filingType: form.filingType.trim(),
        periodLabel: form.periodLabel.trim(),
        periodStart: form.periodStart || null,
        periodEnd: form.periodEnd || null,
        status: form.status,
        blockedReason: form.status === "BLOCKED" ? form.blockedReason.trim() : null,
      });
      addToast?.(editing ? "Filing record updated." : "Filing record saved.", "success");
      setShowForm(false);
      await load();
    } catch (err) {
      addToast?.(err.message || "Failed to save filing record.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(row) {
    if (!window.confirm(`Delete the ${filingType(row)} filing record for ${row.org_name}?`)) return;
    try {
      await deleteStatutoryFiling(row.orgId, row.filing_id);
      addToast?.("Filing record deleted.", "success");
      await load();
    } catch (err) {
      addToast?.(err.message || "Failed to delete filing record.", "error");
    }
  }

  const jurisdictionEntries = Object.entries(data.jurisdictions || {});
  const hasAnySection = jurisdictionEntries.length > 0 || (data.unconfigured || []).length > 0;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FileText size={22} className="text-primary" /> Filings & Remittances
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Cross-organization statutory filing status, by jurisdiction.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {data.known_gaps?.length > 0 && (
        <div className="mb-6 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
          <Info size={16} className="mt-0.5 shrink-0" />
          <ul className="list-disc pl-4 space-y-1">
            {data.known_gaps.map((gap, i) => <li key={i}>{gap}</li>)}
          </ul>
        </div>
      )}

      {jurisdictionEntries.map(([code, section]) => {
        const rows = flattenJurisdictionRows(section);
        const actionableCount = rows.filter((r) => ACTIONABLE_STATUSES.has(r.status)).length;
        const hasRecords = rows.some((r) => !r.is_empty_state);
        const orgCount = section.total_orgs ?? section.organizations?.length ?? 0;
        return (
          <div key={code} className="mb-6">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
              <h2 className={`${SECTION_LABEL_CLS} flex flex-wrap items-center gap-2`}>
                {section.label || code} — {section.total ?? rows.length} filing{section.total === 1 ? "" : "s"} · {orgCount} org{orgCount === 1 ? "" : "s"}
                {actionableCount > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <AlertTriangle size={12} className="text-error" />
                    <StatusPill status="rejected" label={`${actionableCount} need attention`} />
                  </span>
                )}
              </h2>
              <button
                onClick={() => openAdd(section)}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
              >
                <Plus size={13} /> Record Filing
              </button>
            </div>
            <p className="text-xs text-foreground-muted mb-3">
              {hasRecords
                ? "Recorded status updates here apply immediately across the platform."
                : "No filing records entered yet — record the first status, or orgs below keep showing an empty state."}
            </p>
            <div className={TABLE_WRAP_CLS}>
              <table className="w-full text-sm min-w-[900px]">
                <thead className="bg-background text-left text-xs text-foreground-muted">
                  <tr>
                    <th className={TH_CLS}>Organization</th>
                    <th className={TH_CLS}>Type</th>
                    <th className={TH_CLS}>Period</th>
                    <th className={TH_CLS}>Status</th>
                    <th className={TH_CLS}>Blocked Reason</th>
                    <th className={TH_CLS}>Updated</th>
                    <th className={TH_CLS}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((f) => {
                    const actionable = ACTIONABLE_STATUSES.has(f.status);
                    const emptyState = f.is_empty_state;
                    return (
                      <tr
                        key={f.key}
                        className={`border-t border-border-light ${actionable ? "border-l-4 border-l-error bg-error-light/30" : ""}`}
                      >
                        <td className={`${TD_CLS} font-medium text-foreground`}>{f.org_name}</td>
                        <td className={`${TD_CLS} text-foreground-secondary`}>{emptyState ? "—" : filingType(f)}</td>
                        <td className={`${TD_CLS} text-foreground-muted`}>{emptyState ? "—" : filingPeriod(f)}</td>
                        <td className={TD_CLS}>
                          <span className="inline-flex items-center gap-1.5">
                            {actionable && <AlertTriangle size={13} className="shrink-0 text-error" />}
                            {emptyState ? (
                              <span className="text-foreground-muted italic">No filing records yet</span>
                            ) : (
                              <StatusPill status={STATUS_PILL_MAP[f.status] || "inactive"} label={f.status} />
                            )}
                          </span>
                        </td>
                        <td className={`${TD_CLS} text-foreground-muted`}>{emptyState ? "—" : (f.blocked_reason || "—")}</td>
                        <td className={`${TD_CLS} text-foreground-muted`}>
                          {emptyState ? "—" : (f.updated_at ? new Date(f.updated_at).toLocaleString() : "—")}
                        </td>
                        <td className={TD_CLS}>
                          {emptyState ? (
                            <button
                              onClick={() => openRecord(f)}
                              className="rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-primary hover:bg-surface-muted"
                            >
                              + Record
                            </button>
                          ) : (
                            <span className="inline-flex items-center gap-1">
                              <button
                                onClick={() => openEdit(f)}
                                title="Edit"
                                className="rounded-md border border-border p-1.5 text-foreground-secondary hover:bg-surface-muted"
                              >
                                <Pencil size={13} />
                              </button>
                              {f.filing_id && (
                                <button
                                  onClick={() => handleDelete(f)}
                                  title="Delete"
                                  className="rounded-md border border-border p-1.5 text-error hover:bg-error-light/30"
                                >
                                  <Trash2 size={13} />
                                </button>
                              )}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {rows.length === 0 && (
                <div className={EMPTY_CLS}>
                  <p className="text-sm text-foreground-disabled">No organizations configured with this jurisdiction.</p>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {data.unconfigured?.length > 0 && (
        <div className="mb-6">
          <h2 className={`${SECTION_LABEL_CLS} mb-1 flex flex-wrap items-center gap-2`}>
            Unconfigured — {data.unconfigured.length} org{data.unconfigured.length === 1 ? "" : "s"}
          </h2>
          <p className="text-xs text-foreground-muted mb-3">
            No compliance jurisdiction set, so none of these orgs can have filing records. Open{" "}
            <Link to="/super-admin/organizations" className="text-primary underline hover:text-primary/80">Organization Settings</Link>{" "}
            to assign a jurisdiction — until then every row stays in this bucket, not hidden.
          </p>
          <div className={TABLE_WRAP_CLS}>
            <table className="w-full text-sm min-w-[900px]">
              <thead className="bg-background text-left text-xs text-foreground-muted">
                <tr>
                  <th className={TH_CLS}>Organization</th>
                  <th className={TH_CLS}>Type</th>
                  <th className={TH_CLS}>Period</th>
                  <th className={TH_CLS}>Status</th>
                  <th className={TH_CLS}>Blocked Reason</th>
                  <th className={TH_CLS}>Updated</th>
                  <th className={TH_CLS}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.unconfigured.map((org) => (
                  <tr key={org.org_id} className="border-t border-border-light">
                    <td className={`${TD_CLS} font-medium text-foreground`}>{org.org_name}</td>
                    <td className={`${TD_CLS} text-foreground-muted`}>—</td>
                    <td className={`${TD_CLS} text-foreground-muted`}>—</td>
                    <td className={TD_CLS}>
                      <span className="text-foreground-muted">
                        No jurisdiction set{" "}
                        <Link to="/super-admin/organizations" className="text-primary underline hover:text-primary/80">Set one</Link>
                      </span>
                    </td>
                    <td className={`${TD_CLS} text-foreground-muted`}>—</td>
                    <td className={`${TD_CLS} text-foreground-muted`}>—</td>
                    <td className={`${TD_CLS} text-foreground-muted`}>—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!hasAnySection && !loading && (
        <p className="text-sm text-foreground-disabled">No organizations or filing data yet.</p>
      )}

      {showForm && (
        <Modal
          title={editing ? "Edit Filing Record" : "Record Filing"}
          onClose={() => setShowForm(false)}
          maxWidth="max-w-md"
        >
          <div className="grid grid-cols-2 gap-3">
            {!editing && (
              <div className="col-span-2">
                <label className="block text-xs font-semibold text-foreground-secondary mb-1">Organization</label>
                <select
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                  value={form.orgId}
                  onChange={(e) => setForm((f) => ({ ...f, orgId: Number(e.target.value) }))}
                >
                  <option value="">Select organization…</option>
                  {orgOptions.map((o) => (
                    <option key={o.id} value={o.id}>{o.name}</option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <label className="block text-xs font-semibold text-foreground-secondary mb-1">Filing Type</label>
              <input
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.filingType}
                onChange={(e) => setForm((f) => ({ ...f, filingType: e.target.value }))}
                placeholder="e.g. TDS, BAS, GST"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground-secondary mb-1">Period Label</label>
              <input
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.periodLabel}
                onChange={(e) => setForm((f) => ({ ...f, periodLabel: e.target.value }))}
                placeholder="e.g. Q2 2026 (Apr–Jun)"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground-secondary mb-1">Period Start</label>
              <input
                type="date"
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.periodStart}
                onChange={(e) => setForm((f) => ({ ...f, periodStart: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground-secondary mb-1">Period End</label>
              <input
                type="date"
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.periodEnd}
                onChange={(e) => setForm((f) => ({ ...f, periodEnd: e.target.value }))}
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-semibold text-foreground-secondary mb-1">Status</label>
              <select
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.status}
                onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
              >
                {RECORDABLE_STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            {form.status === "BLOCKED" && (
              <div className="col-span-2">
                <label className="block text-xs font-semibold text-foreground-secondary mb-1">Blocked Reason</label>
                <textarea
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                  rows={2}
                  value={form.blockedReason}
                  onChange={(e) => setForm((f) => ({ ...f, blockedReason: e.target.value }))}
                  placeholder="Why this filing cannot proceed…"
                />
              </div>
            )}
          </div>
          <p className="mt-3 text-xs text-foreground-muted">
            Saving upserts by jurisdiction + filing type + period, so re-recording an existing period updates its row.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <button
              onClick={() => setShowForm(false)}
              className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}