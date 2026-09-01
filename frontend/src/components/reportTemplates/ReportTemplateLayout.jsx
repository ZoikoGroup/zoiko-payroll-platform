import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Plus, Trash2, History, FileBarChart, ScrollText, ShieldCheck, CalendarClock } from "lucide-react";
import ConfirmDialog from "../ConfirmDialog";
import StatusPill from "../StatusPill";
import Field from "../jurisdiction/Field";
import { useToast } from "../../context/ToastContext";
import {
  getReportTemplates, getReportTemplateDetail, getReportTemplateVersions,
  setReportTemplateStatus, approveReportTemplate, getReportTemplateAudit, hardDeleteReportTemplate,
  getAvailableReportComponents, getAvailableReportDataFields,
} from "../../service/superAdminService";
import { inputClass } from "../jurisdiction/constants";
import { STATUS_OPTIONS, STATUS_PILL_MAP } from "./constants";
import NewReportTemplateModal from "./NewReportTemplateModal";
import ComponentsTab from "./ComponentsTab";
import FilingCalendarTab from "./FilingCalendarTab";

const TABS = [
  { key: "overview", label: "Overview", icon: FileBarChart },
  { key: "components", label: "Components", icon: ScrollText },
  { key: "filing-calendar", label: "Filing Calendar", icon: CalendarClock },
  { key: "versions", label: "Versions", icon: History },
  { key: "audit", label: "Audit", icon: ScrollText },
];

const EDITABLE_STATUSES = ["Draft", "Review", "Approved"];

// The Super Admin Report Template authoring surface — same visual/
// interaction shape as JurisdictionLayout (sidebar list + detail panel +
// status-select + maker-checker Approve + Versions + Audit), but a
// sibling component rather than routed through JurisdictionLayout itself:
// a report template has no rates/slabs/org-assignment, so forcing it
// through that component would mean either faking empty rate/slab tabs
// or growing more country-agnostic conditionals into a file whose own
// comments describe its extension points as deliberately minimal.
export default function ReportTemplateLayout({ country, countryName, initialState = "", onStateChange }) {
  const { addToast } = useToast() || {};
  const navigate = useNavigate();
  const [state, setStateRaw] = useState(initialState || "");
  const [reportType, setReportType] = useState("");
  const [templates, setTemplates] = useState([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState("overview");

  const [availableComponents, setAvailableComponents] = useState([]);
  const [availableDataFields, setAvailableDataFields] = useState([]);
  const [versions, setVersions] = useState([]);
  const [audit, setAudit] = useState([]);

  const [showNewTemplate, setShowNewTemplate] = useState(false);
  const [deletingTemplate, setDeletingTemplate] = useState(null);

  function setState(next) {
    setStateRaw(next);
    onStateChange?.(next);
  }

  const loadTemplates = useCallback(() => {
    if (!country) return;
    setLoadingTemplates(true);
    getReportTemplates({ country, state: state || undefined, reportType: reportType || undefined })
      .then(setTemplates)
      .finally(() => setLoadingTemplates(false));
  }, [country, state, reportType]);

  useEffect(() => { loadTemplates(); setSelectedId(null); setDetail(null); }, [loadTemplates]);

  const loadDetail = useCallback(() => {
    if (!selectedId) { setDetail(null); return; }
    getReportTemplateDetail(selectedId).then((full) => {
      setDetail(full);
      getAvailableReportComponents(full.reportType).then(setAvailableComponents);
      getAvailableReportDataFields(full.jurisdictionCountry).then(setAvailableDataFields);
      getReportTemplateVersions(full.templateKey).then(setVersions);
      getReportTemplateAudit(full.id).then(setAudit);
    });
  }, [selectedId]);

  useEffect(() => { setTab("overview"); loadDetail(); }, [loadDetail]);

  async function changeStatus(newStatus) {
    try {
      await setReportTemplateStatus(detail.id, newStatus);
      addToast?.(`Status set to ${newStatus}.`, "success");
      loadDetail();
      loadTemplates();
    } catch (err) {
      addToast?.(err.message || "Failed to change status.", "error");
    }
  }

  async function handleApprove() {
    try {
      await approveReportTemplate(detail.id);
      addToast?.("You're now recorded as this template's approver.", "success");
      loadDetail();
      loadTemplates();
    } catch (err) {
      addToast?.(err.message || "Failed to record approval.", "error");
    }
  }

  async function handleDelete() {
    try {
      const res = await hardDeleteReportTemplate(deletingTemplate.id);
      addToast?.(res.message || "Deleted.", "success");
      setSelectedId(null);
      loadTemplates();
    } catch (err) {
      addToast?.(err.message || "Failed to delete — it may have generated reports or be Published/Active.", "error");
    } finally {
      setDeletingTemplate(null);
    }
  }

  const editable = Boolean(detail && EDITABLE_STATUSES.includes(detail.status));

  return (
    <div>
      <div className="mb-6">
        <button onClick={() => navigate(-1)} className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
          <ArrowLeft size={14} /> Back
        </button>
        <h1 className="text-2xl font-bold text-foreground">{countryName} Report Templates</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Author and publish the statutory report blueprints Organizations generate their actual reports from.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input
          className={inputClass + " w-auto min-w-[160px]"} value={state} onChange={(e) => setState(e.target.value)}
          placeholder="State (optional)"
        />
        <input
          className={inputClass + " w-auto min-w-[140px]"} value={reportType} onChange={(e) => setReportType(e.target.value)}
          placeholder="Filter by Report Type"
        />
        <button
          onClick={() => setShowNewTemplate(true)}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={14} /> New Report
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <div className="rounded-xl border border-border bg-surface p-2">
          {loadingTemplates ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
          ) : templates.length === 0 ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">No report templates for this jurisdiction yet.</p>
          ) : (
            <div className="space-y-1">
              {templates.map((t) => (
                <button
                  key={t.id} onClick={() => setSelectedId(t.id)}
                  className={`flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left text-xs ${
                    selectedId === t.id ? "bg-primary/10 text-primary" : "text-foreground-secondary hover:bg-surface-muted"
                  }`}
                >
                  <span className="font-semibold">{t.name}</span>
                  <span className="flex items-center gap-2 text-foreground-muted">
                    v{t.version} · {t.reportType} · FY {t.reportingYear}
                    <StatusPill status={STATUS_PILL_MAP[t.status] || "pending"} label={t.status} />
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-border bg-surface p-5">
          {!detail ? (
            <div className="flex h-64 items-center justify-center">
              <p className="text-sm text-foreground-disabled">Select a report template from the list to view/edit it.</p>
            </div>
          ) : (
            <>
              <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-foreground">{detail.name}</h2>
                    <StatusPill status={STATUS_PILL_MAP[detail.status] || "pending"} label={detail.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-foreground-muted">
                    v{detail.version} · {detail.reportType} · {detail.jurisdictionCountry}{detail.jurisdictionState ? ` / ${detail.jurisdictionState}` : ""} · FY {detail.reportingYear}
                    {detail.effectiveFrom ? ` · ${detail.effectiveFrom} → ${detail.effectiveTo || "open"}` : ""}
                    {" · "}{detail.documentScope === "PER_EMPLOYEE" ? "Per-Employee document" : "Aggregate document"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {/* Maker-checker: a distinct Super Admin from whoever last
                      edited this template must approve it before it can go
                      Published/Active — enforced server-side in
                      set_report_template_status; this button just records
                      "I approve this," it doesn't change status itself. */}
                  <button
                    onClick={handleApprove}
                    title={detail.approvedById ? `Currently approved by user #${detail.approvedById}` : "Not yet approved"}
                    className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                  >
                    <ShieldCheck size={13} /> Approve
                  </button>
                  <select className={inputClass + " w-auto"} value={detail.status} onChange={(e) => changeStatus(e.target.value)}>
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <button onClick={() => setDeletingTemplate(detail)} className="rounded-lg border border-border p-2 text-error hover:bg-error-light">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <div className="mb-4 flex items-center gap-1 border-b border-border overflow-x-auto">
                {TABS.map((t) => (
                  <button
                    key={t.key} onClick={() => setTab(t.key)}
                    className={`flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${
                      tab === t.key ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    <t.icon size={13} /> {t.label}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                  <Field label="Regulatory Authority" value={detail.regulatoryAuthority} />
                  <Field label="Reconciliation Tolerance" value={detail.reconciliationTolerance} />
                  <Field label="Document Scope" value={detail.documentScope === "PER_EMPLOYEE" ? "Per-Employee (certificate)" : "Aggregate (one document for the run)"} />
                  <Field label="Source Document" value={detail.sourceDocumentId ? `Artifact #${detail.sourceDocumentId}` : "None linked"} />
                  <Field label="Source References" value={detail.sourceReferences} />
                  <Field label="Description" value={detail.description} />
                  <div className="sm:col-span-2">
                    <p className="text-foreground-muted mb-1">Change Summary</p>
                    <p className="font-medium text-foreground">{detail.changeSummary || "—"}</p>
                  </div>
                </div>
              )}

              {tab === "components" && (
                <ComponentsTab
                  template={detail} components={detail.components || []} availableComponents={availableComponents}
                  availableDataFields={availableDataFields} editable={editable} onChanged={loadDetail}
                />
              )}

              {tab === "filing-calendar" && (
                <FilingCalendarTab template={detail} editable={editable} />
              )}

              {tab === "versions" && (
                <div className="space-y-2">
                  {versions.map((v) => (
                    <button
                      key={v.id} onClick={() => setSelectedId(v.id)}
                      className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-xs text-left ${
                        v.id === detail.id ? "border-primary bg-primary/5" : "border-border-light hover:bg-surface-muted"
                      }`}
                    >
                      <span className="font-medium text-foreground">v{v.version}</span>
                      <span className="flex items-center gap-2 text-foreground-muted">
                        {v.effectiveFrom} → {v.effectiveTo || "open"}
                        <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
                      </span>
                    </button>
                  ))}
                </div>
              )}

              {tab === "audit" && (
                <div className="space-y-2">
                  {audit.length === 0 ? (
                    <p className="py-6 text-center text-xs text-foreground-disabled">No audit history yet.</p>
                  ) : audit.map((a) => {
                    const changedKeys = Object.keys({ ...(a.oldValue || {}), ...(a.newValue || {}) })
                      .filter((k) => JSON.stringify(a.oldValue?.[k]) !== JSON.stringify(a.newValue?.[k]));
                    return (
                      <div key={a.id} className="rounded-lg border border-border-light p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-foreground">
                            {a.action} — {a.entityType} {a.actorId ? <span className="text-foreground-disabled">· by user #{a.actorId}</span> : null}
                          </span>
                          <span className="text-foreground-disabled">{new Date(a.createdAt).toLocaleString()}</span>
                        </div>
                        {a.reason && <p className="mt-1 text-foreground-secondary">{a.reason}</p>}
                        {changedKeys.length > 0 && (
                          <div className="mt-1.5 space-y-0.5 border-t border-border-light pt-1.5">
                            {changedKeys.map((k) => (
                              <div key={k} className="flex items-center gap-1.5 font-mono text-[11px]">
                                <span className="text-foreground-disabled">{k}:</span>
                                <span className="text-error line-through">{a.oldValue?.[k] ?? "—"}</span>
                                <span className="text-foreground-disabled">→</span>
                                <span className="text-success">{a.newValue?.[k] ?? "—"}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {showNewTemplate && (
        <NewReportTemplateModal
          country={country} countryName={countryName} state={state}
          onClose={() => setShowNewTemplate(false)}
          onCreated={(created) => { setShowNewTemplate(false); loadTemplates(); setSelectedId(created.id); }}
        />
      )}
      {deletingTemplate && (
        <ConfirmDialog
          title="Delete Report Template" message={`Permanently delete "${deletingTemplate.name}" v${deletingTemplate.version}? Only allowed with no generated reports and not Published/Active.`}
          onConfirm={handleDelete} onClose={() => setDeletingTemplate(null)}
        />
      )}
    </div>
  );
}
