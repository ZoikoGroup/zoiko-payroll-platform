import { useState, useEffect, useCallback, useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, Plus, Trash2, History, FileBarChart, FileWarning, ScrollText, ShieldCheck, CalendarClock, X } from "lucide-react";
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
import { filterTemplates } from "./filterTemplates";
import { buildDetailTabs } from "./detailTabs";
import { actorLabel, describeAuditEntry, groupAuditEntries } from "./auditView";
import Collapsible from "../jurisdiction/Collapsible";
import { DisabledReason } from "../jurisdiction/PackRowTables";
import { canApprove, deleteState, missingRequiredFields, toleranceLabel } from "./actions";
import { activationBanner, activeOptionReason, availabilityLabel, listBadge, statusOptions } from "./readiness";
import Notice from "../jurisdiction/Notice";

// Badge beside a status pill: "Not built" / "Blocked · G3", the backend's
// reason as its tooltip (and its accessible description).
function ReadinessBadge({ badge }) {
  if (!badge) return null;
  return (
    <span title={badge.title} aria-label={`${badge.label}: ${badge.title}`} data-testid={`readiness-badge-${badge.key}`}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
        badge.key === "not-built" ? "border-border bg-surface-muted text-foreground-muted" : "border-error/40 bg-error/5 text-error"
      }`}>
      {badge.label}
    </span>
  );
}

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
// `embedded` (Singapore final closure): rendered inside another page (the
// Singapore compliance Report Templates tab) — the page header / Back button
// are left to the host; behaviour is otherwise identical.
//
// Optional, generic extension points (a country page passes nothing and the
// layout renders exactly as before):
//   extraDetailTabs     [{ key, label, icon, render(detail, ctx) }] — tabs
//                       appended after the built-in detail tabs.
//   renderOverviewExtra (detail, ctx) => node — a block shown at the top of the
//                       Overview tab for the selected template.
//   pageTools           [{ key, label, icon, render(ctx) }] — page-level views
//                       behind a toolbar toggle, collapsed by default.
//   hiddenDetailTabs    [key] — built-in detail tabs to hide (e.g. a page
//                       whose extra tab supersedes "versions"). "overview" is
//                       always shown: it is the tab a selection opens on.
//   renderComponentsExtra (detail, ctx) => node — a block shown at the top of
//                       the Components tab (e.g. why a report type has none).
// ctx ={ reloadDetail, reloadTemplates, selectTemplate(id) }. Extensions are
// presentation only: every lifecycle rule stays server-side.
const NO_EXTRAS = [];

// A required metadata field: its value, or a "Missing" warning instead of "—".
function RequiredField({ label, value, wide = false }) {
  const missing = value === null || value === undefined || String(value).trim() === "";
  const key = label.toLowerCase().replace(/[^a-z]+/g, "-");
  return (
    <div className={wide ? "sm:col-span-2" : undefined} data-testid={`overview-field-${key}`}>
      <p className="mb-1 text-foreground-muted">{label}</p>
      {missing ? (
        <span data-testid={`overview-missing-${key}`}
          className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-semibold text-warning">
          <FileWarning size={12} aria-hidden="true" /> Missing
        </span>
      ) : <p className="font-medium text-foreground">{value}</p>}
    </div>
  );
}

const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

// One audit row: what happened, by whom (name, else "User #<id>"), when, and
// the fields that changed.
function AuditEntry({ entry: a }) {
  const { summary, rows } = describeAuditEntry(a);
  return (
    <div className="rounded-lg border border-border-light p-2 text-xs" data-testid="audit-entry">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-foreground">
          {a.action} — {a.entityType} <span className="text-foreground-disabled">· by {actorLabel(a)}</span>
        </span>
        <span className="text-foreground-disabled">{when(a.createdAt)}</span>
      </div>
      {summary && <p className="mt-1 font-semibold text-error" data-testid="audit-refused">{summary}</p>}
      {a.reason && <p className="mt-1 text-foreground-secondary">{a.reason}</p>}
      {rows.length > 0 && (
        <div className="mt-1.5 space-y-0.5 border-t border-border-light pt-1.5">
          {rows.map((r) => (
            <div key={r.key} className="flex items-center gap-1.5 font-mono text-[11px]">
              <span className="text-foreground-disabled">{r.key}:</span>
              <span className="text-error line-through">{r.from}</span>
              <span className="text-foreground-disabled">→</span>
              <span className="text-success">{r.to}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Consecutive identical refusals (same actor, same move, same reason) shown
// as one row that expands to every attempt — every audit record is kept.
function RefusalGroup({ group }) {
  const { latest, entries, count } = group;
  const { summary } = describeAuditEntry(latest);
  return (
    <Collapsible
      testId="audit-refusal-group"
      title={`Refused ×${count} — last at ${when(latest.createdAt)}`}
      badge={<span className="text-[11px] text-foreground-muted">by {actorLabel(latest)}</span>}
      summary={[summary, latest.reason].filter(Boolean).join(" · ")}
    >
      <ul className="space-y-1 text-xs" data-testid="audit-refusal-attempts">
        {entries.map((e) => (
          <li key={e.id} className="flex flex-wrap justify-between gap-2 text-foreground-secondary">
            <span>Attempt by {actorLabel(e)}</span>
            <span className="text-foreground-disabled">{when(e.createdAt)}</span>
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}

export default function ReportTemplateLayout({
  country, countryName, initialState = "", onStateChange, embedded = false,
  extraDetailTabs = NO_EXTRAS, renderOverviewExtra = null, pageTools = NO_EXTRAS, hiddenDetailTabs = NO_EXTRAS,
  renderComponentsExtra = null,
}) {
  const { addToast } = useToast() || {};
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [state, setStateRaw] = useState(initialState || "");
  const [filterText, setFilterText] = useState("");
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
  const [openTool, setOpenTool] = useState(null);

  const tabs = useMemo(() => buildDetailTabs(TABS, hiddenDetailTabs, extraDetailTabs), [extraDetailTabs, hiddenDetailTabs]);
  const isShown = (key) => tabs.some((t) => t.key === key);

  function setState(next) {
    setStateRaw(next);
    onStateChange?.(next);
  }

  // One fetch per country (and per state when one arrives from the URL):
  // includeStates returns the country's state-level templates too (AU state
  // payroll-tax returns, MX ISN, ...). Typing in the filter never refetches.
  const loadTemplates = useCallback(() => {
    if (!country) return;
    setLoadingTemplates(true);
    getReportTemplates({ country, state: state || undefined, includeStates: true })
      .then(setTemplates)
      .finally(() => setLoadingTemplates(false));
  }, [country, state]);

  const visibleTemplates = useMemo(() => filterTemplates(templates, filterText), [templates, filterText]);

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
  // Readiness is the backend's dry run of the status change (detail response):
  // presentation only — the status change itself still refuses.
  const activeReason = detail ? activeOptionReason(STATUS_OPTIONS, detail) : null;
  const deletion = deleteState(detail);
  const missingFields = missingRequiredFields(detail);
  const banner = detail ? activationBanner(detail) : null;
  // The compliance page uses the same country slug as this page
  // (/super-admin/report-templates/<slug> -> /super-admin/compliance/<slug>;
  // the two route maps are identical, see report-template-ui-validation). No
  // link when embedded in another page.
  const complianceRoute = (/^\/super-admin\/report-templates\/([a-z-]+)/.exec(pathname) || [])[1] || null;
  const ctx = { reloadDetail: loadDetail, reloadTemplates: loadTemplates, selectTemplate: setSelectedId };
  const activeTool = pageTools.find((t) => t.key === openTool);
  const activeExtraTab = extraDetailTabs.find((t) => t.key === tab);

  return (
    <div>
      {!embedded && (
        <div className="mb-6">
          <button onClick={() => navigate(-1)} className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
            <ArrowLeft size={14} /> Back
          </button>
          <h1 className="text-2xl font-bold text-foreground">{countryName} Report Templates</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Author and publish the statutory report blueprints Organizations generate their actual reports from.
          </p>
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input
          className={inputClass + " w-auto min-w-[240px]"} value={filterText} onChange={(e) => setFilterText(e.target.value)}
          placeholder="Filter by name or report type" aria-label="Filter by name or report type"
        />
        {state && (
          <span className="flex items-center gap-1 rounded-full border border-border bg-surface-muted px-2.5 py-1 text-xs font-medium text-foreground-secondary">
            State: {state}
            <button
              type="button" onClick={() => setState("")} aria-label="Clear state"
              className="rounded-full p-0.5 text-foreground-muted hover:bg-surface hover:text-foreground"
            >
              <X size={12} />
            </button>
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {pageTools.map((t) => (
            <button
              key={t.key} type="button" aria-expanded={openTool === t.key} data-testid={`page-tool-${t.key}`}
              onClick={() => setOpenTool(openTool === t.key ? null : t.key)}
              className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold ${
                openTool === t.key ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground-secondary hover:bg-surface-muted"
              }`}
            >
              {t.icon && <t.icon size={14} />} {t.label}
            </button>
          ))}
          <button
            onClick={() => setShowNewTemplate(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover"
          >
            <Plus size={14} /> New Report
          </button>
        </div>
      </div>

      {activeTool && (
        <div className="mb-5 rounded-xl border border-border bg-surface p-4" data-testid={`page-tool-panel-${activeTool.key}`}>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">{activeTool.label}</h3>
            <button type="button" onClick={() => setOpenTool(null)} aria-label={`Close ${activeTool.label}`}
                    className="rounded-full p-1 text-foreground-muted hover:bg-surface-muted hover:text-foreground">
              <X size={14} />
            </button>
          </div>
          {activeTool.render(ctx)}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <div className="rounded-xl border border-border bg-surface p-2">
          {loadingTemplates ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
          ) : templates.length === 0 ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">No report templates for this jurisdiction yet.</p>
          ) : visibleTemplates.length === 0 ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">{`No templates match "${filterText.trim()}"`}</p>
          ) : (
            <div className="space-y-1">
              {visibleTemplates.map((t) => (
                <button
                  key={t.id} onClick={() => setSelectedId(t.id)}
                  className={`flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left text-xs ${
                    selectedId === t.id ? "bg-primary/10 text-primary" : "text-foreground-secondary hover:bg-surface-muted"
                  }`}
                >
                  <span className="font-semibold">{t.name}</span>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-foreground-muted">
                    v{t.version} · {t.reportType}{t.jurisdictionState ? ` · ${t.jurisdictionState}` : ""} · FY {t.reportingYear}
                    <StatusPill status={STATUS_PILL_MAP[t.status] || "pending"} label={t.status} />
                    <ReadinessBadge badge={listBadge(t)} />
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
                    {availabilityLabel(detail) ? (
                      <span data-testid="availability-label"
                        className="inline-flex items-center rounded-full border border-border bg-surface-muted px-2.5 py-0.5 text-xs font-medium text-foreground-muted">
                        {availabilityLabel(detail)}
                      </span>
                    ) : <ReadinessBadge badge={listBadge(detail)} />}
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
                      "I approve this," it doesn't change status itself.
                      Offered only before release (Draft / Review / Approved):
                      the backend refuses to replace a released version's
                      approval (set_report_template_approver). */}
                  {canApprove(detail) && (
                    <button
                      onClick={handleApprove} data-testid="rt-action-approve"
                      title={detail.approvedById ? `Currently approved by user #${detail.approvedById}` : "Not yet approved"}
                      className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                    >
                      <ShieldCheck size={13} /> Approve
                    </button>
                  )}
                  <select className={inputClass + " w-auto"} value={detail.status} onChange={(e) => changeStatus(e.target.value)}
                    aria-describedby={activeReason ? "active-blocked-reason" : undefined} aria-label="Status">
                    {statusOptions(STATUS_OPTIONS, detail).map((o) => (
                      <option key={o.value} value={o.value} disabled={o.disabled} title={o.reason || undefined}>
                        {o.value}{o.disabled && o.value === "Active" ? " (unavailable)" : ""}
                      </option>
                    ))}
                  </select>
                  {deletion.allowed ? (
                    <button onClick={() => setDeletingTemplate(detail)} aria-label="Delete template" data-testid="rt-action-delete"
                      className="rounded-lg border border-border p-2 text-error hover:bg-error-light">
                      <Trash2 size={14} />
                    </button>
                  ) : (
                    <DisabledReason reason={deletion.reason}>
                      <button disabled aria-disabled="true" aria-label={`Delete template — ${deletion.reason}`} data-testid="rt-action-delete"
                        className="pointer-events-none rounded-lg border border-border p-2 text-error opacity-40">
                        <Trash2 size={14} />
                      </button>
                    </DisabledReason>
                  )}
                </div>
              </div>

              {activeReason && activeReason !== banner?.message && (
                <p id="active-blocked-reason" data-testid="active-blocked-reason" className="-mt-2 mb-3 text-xs text-foreground-muted">
                  <span className="font-semibold">Active is unavailable:</span> {activeReason}
                </p>
              )}
              {banner && (
                <div className="mb-4">
                  <Notice tone={banner.tone} title={banner.title} testId="activation-banner"
                    actions={banner.linkToReadiness && complianceRoute ? (
                      <Link to={`/super-admin/compliance/${complianceRoute}?tab=release-readiness`}
                        className="rounded-lg border border-border bg-surface px-2.5 py-1 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                        Release readiness{banner.gate ? ` (${banner.gate})` : ""}
                      </Link>
                    ) : null}>
                    {banner.message}
                    {banner.deferred.length > 0 && (
                      <ul className="mt-1 list-disc pl-4" data-testid="activation-deferred">
                        {banner.deferred.map((d) => <li key={d}>{d}</li>)}
                      </ul>
                    )}
                  </Notice>
                </div>
              )}

              <div className="mb-4 flex items-center gap-1 border-b border-border overflow-x-auto">
                {tabs.map((t) => (
                  <button
                    key={t.key} onClick={() => setTab(t.key)}
                    className={`flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${
                      tab === t.key ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    {t.icon && <t.icon size={13} />} {t.label}
                  </button>
                ))}
              </div>

              {tab === "overview" && renderOverviewExtra && (
                <div className="mb-4">{renderOverviewExtra(detail, ctx)}</div>
              )}

              {tab === "overview" && missingFields.length > 0 && (
                <div className="mb-4 space-y-1 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2.5 text-xs text-warning"
                  data-testid="overview-needs-attention">
                  <p className="flex items-center gap-1.5 font-semibold">
                    <FileWarning size={13} aria-hidden="true" /> Needs attention ({missingFields.length})
                  </p>
                  <p>Not filled in: {missingFields.join(", ")}.</p>
                </div>
              )}

              {tab === "overview" && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                  <RequiredField label="Regulatory Authority" value={detail.regulatoryAuthority} />
                  <div data-testid="overview-field-tolerance">
                    <p className="mb-1 text-foreground-muted">Reconciliation Tolerance</p>
                    <p className="font-medium text-foreground">
                      {toleranceLabel(detail)}
                      {toleranceLabel(detail) === "Exact match" && <span className="font-normal text-foreground-muted"> (no tolerance set)</span>}
                    </p>
                  </div>
                  <Field label="Document Scope" value={detail.documentScope === "PER_EMPLOYEE" ? "Per-Employee (certificate)" : "Aggregate (one document for the run)"} />
                  <Field label="Source Document" value={detail.sourceDocumentId ? `Artifact #${detail.sourceDocumentId}` : "None linked"} />
                  <RequiredField label="Source References" value={detail.sourceReferences} />
                  <Field label="Description" value={detail.description} />
                  <RequiredField label="Change Summary" value={detail.changeSummary} wide />
                </div>
              )}

              {tab === "components" && isShown("components") && renderComponentsExtra && (
                <div className="mb-4">{renderComponentsExtra(detail, ctx)}</div>
              )}

              {tab === "components" && isShown("components") && (
                <ComponentsTab
                  template={detail} components={detail.components || []} availableComponents={availableComponents}
                  availableDataFields={availableDataFields} editable={editable} onChanged={loadDetail}
                />
              )}

              {tab === "filing-calendar" && isShown("filing-calendar") && (
                <FilingCalendarTab template={detail} editable={editable} />
              )}

              {tab === "versions" && isShown("versions") && (
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

              {tab === "audit" && isShown("audit") && (
                <div className="space-y-2">
                  {audit.length === 0 ? (
                    <p className="py-6 text-center text-xs text-foreground-disabled">No audit history yet.</p>
                  ) : groupAuditEntries(audit).map((g) => (g.kind === "refusals" ? (
                    <RefusalGroup key={`g${g.latest.id}`} group={g} />
                  ) : <AuditEntry key={g.entry.id} entry={g.entry} />))}
                </div>
              )}

              {activeExtraTab && activeExtraTab.render(detail, ctx)}
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
          title={deletingTemplate.status === "Approved" ? "Delete Approved Report Template" : "Delete Report Template"}
          message={deleteState(deletingTemplate).confirmMessage}
          onConfirm={handleDelete} onClose={() => setDeletingTemplate(null)}
        />
      )}
    </div>
  );
}
