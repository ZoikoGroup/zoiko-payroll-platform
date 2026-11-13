import { useCallback, useEffect, useMemo, useState } from "react";
import { Archive, CheckCircle2, Eye, FileText, Layers, LayoutTemplate, Pencil, Plus, Upload, X } from "lucide-react";
import {
  getPayslipTemplates,
  createPayslipTemplate,
  archivePayslipTemplate,
  unassignPayslipTemplate,
} from "../../../../service/payrollService";
import { useToast } from "../../ToastContext";
import PayslipTemplateEditorModal from "./PayslipTemplateEditorModal";
import PayslipTemplateImportModal from "./PayslipTemplateImportModal";
import PayslipTemplatePdfImportModal from "./PayslipTemplatePdfImportModal";
import PayslipTemplatePreviewModal from "./PayslipTemplatePreviewModal";
import PayslipTemplateAssignmentModal from "./PayslipTemplateAssignmentModal";
import { countryLabel } from "./templateCountries";

const btn =
  "flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] text-[12px] font-semibold transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const btnGhost = `${btn} border border-border bg-surface text-foreground hover:bg-surface-muted`;
const btnPrimary = `${btn} bg-primary text-white hover:bg-primary/90`;

export default function PayslipTemplateDashboard() {
  const { addToast } = useToast();
  const [data, setData] = useState({ starters: [], templates: [], assignments: [], countries: [], singleCountry: true });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const [previewing, setPreviewing] = useState(null);
  const [assigning, setAssigning] = useState(null); // {templateId?}
  const [importOpen, setImportOpen] = useState(false);
  const [pdfImportKey, setPdfImportKey] = useState(0);   // 0 = closed; a new key remounts a fresh wizard
  const [showArchived, setShowArchived] = useState(false);

  const fetchAll = useCallback(() => getPayslipTemplates()
    .then((res) => setData({
      starters: res?.starters || [],
      templates: res?.templates || [],
      assignments: res?.assignments || [],
      countries: res?.countries || [],
      singleCountry: res?.singleCountry ?? true,
    }))
    .catch((err) => addToast?.(err.message || "Could not load payslip templates.", "error"))
    .finally(() => setLoading(false)), [addToast]);
  const load = fetchAll;

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const startFromLayout = async (starter) => {
    setBusy(true);
    try {
      const created = await createPayslipTemplate({ starter: starter.key });
      addToast?.(`"${created.name}" created as a draft.`, "success");
      await load();
      setEditing(created);
    } catch (err) {
      addToast?.(err.message || "Could not create the template.", "error");
    } finally {
      setBusy(false);
    }
  };

  const label = (code) => (data.singleCountry && (!code || code === "ALL") ? "All payslips" : countryLabel(code, data.countries));

  const archive = async (t) => {
    const where = t.assignedCountries?.length ? ` It is currently used for ${t.assignedCountries.map(label).join(", ")}; those payslips will go back to the standard format.` : "";
    if (!window.confirm(`Archive "${t.name}"?${where} Payslips already issued with it keep it.`)) return;
    setBusy(true);
    try {
      const res = await archivePayslipTemplate(t.id);
      setData((d) => ({ ...d, ...res }));
      addToast?.(`"${t.name}" archived.`, "success");
    } catch (err) {
      addToast?.(err.message || "Could not archive the template.", "error");
    } finally {
      setBusy(false);
    }
  };

  const unassign = async (a) => {
    if (!window.confirm(`Stop using "${a.templateName}" for ${label(a.country)}? New payslips will use the standard format.`)) return;
    setBusy(true);
    try {
      const res = await unassignPayslipTemplate(a.country);
      setData((d) => ({ ...d, ...res }));
      addToast?.(`${label(a.country)} now uses the standard payslip.`, "success");
    } catch (err) {
      addToast?.(err.message || "Could not remove the assignment.", "error");
    } finally {
      setBusy(false);
    }
  };

  const visible = data.templates.filter((t) => showArchived || !t.isArchived);
  const archivedCount = data.templates.filter((t) => t.isArchived).length;
  const publishedTemplates = useMemo(
    () => data.templates.filter((t) => !t.isArchived && t.activeVersion), [data.templates]);

  return (
    <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 mb-5">
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-[12px] bg-primary/10 text-primary"><LayoutTemplate size={18} /></div>
          <div>
            <h3 className="text-[15px] font-bold text-foreground">Payslip templates</h3>
            <p className="text-[12px] text-foreground-muted mt-0.5 max-w-2xl">
              Change how payslips look. Amounts never change: a template shows the same lines as the standard
              payslip. Countries without a template keep the standard statutory payslip, and payslips whose
              breakdown can&apos;t be shown in a template always use the standard format.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button type="button" className={btnGhost} onClick={() => setImportOpen(true)} disabled={busy}>
            <Upload size={13} /> Import Word / HTML
          </button>
          <button type="button" className={btnGhost} onClick={() => setPdfImportKey(Date.now())} disabled={busy}
            title="Build a template from a PDF payslip's design">
            <FileText size={13} /> Import PDF
          </button>
          <button type="button" className={btnPrimary} onClick={() => setAssigning({})}
            disabled={busy || publishedTemplates.length === 0}
            title={publishedTemplates.length === 0 ? "Publish a template first" : undefined}>
            <Layers size={13} /> Assign
          </button>
        </div>
      </div>

      {/* Current assignments */}
      <div className="rounded-[12px] border border-border bg-surface-muted/30 p-4 mb-6">
        <p className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted mb-2">In use</p>
        {data.assignments.length === 0 ? (
          <p className="text-[12px] text-foreground-muted">
            No template assigned. Every payslip uses the standard statutory format.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {data.assignments.map((a) => (
              <span key={a.country}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface pl-3 pr-1 py-1 text-[12px] text-foreground">
                <CheckCircle2 size={12} className="text-success" />
                <strong>{label(a.country)}</strong>
                <span className="text-foreground-muted">{a.templateName} v{a.versionNumber}</span>
                {a.countryInactive && (
                  <span className="rounded bg-surface-muted px-1.5 text-[10px] text-foreground-muted"
                    title="Your organisation no longer runs payroll here. Payslips already issued keep this layout.">
                    country no longer active
                  </span>
                )}
                <button type="button" onClick={() => unassign(a)} disabled={busy} aria-label={`Remove ${label(a.country)}`}
                  className="rounded-full p-1 text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer">
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Organisation templates */}
      <div className="flex items-center justify-between mb-3">
        <p className="text-[13px] font-bold text-foreground">Your templates</p>
        {archivedCount > 0 && (
          <label className="flex items-center gap-1.5 text-[12px] text-foreground-muted cursor-pointer">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
            Show archived ({archivedCount})
          </label>
        )}
      </div>
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {[1, 2].map((i) => <div key={i} className="h-40 rounded-[14px] border border-border bg-surface-muted/40 animate-pulse" />)}
        </div>
      ) : visible.length === 0 ? (
        <p className="text-[12px] text-foreground-muted mb-6">
          No templates yet. Start from a layout below, or import your own HTML.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {visible.map((t) => (
            <div key={t.id} className={`rounded-[14px] border bg-surface p-4 flex flex-col gap-3 ${t.isArchived ? "border-border opacity-60" : "border-border"}`}>
              <div>
                <div className="flex items-center gap-1.5 flex-wrap mb-1">
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-muted text-foreground-muted border border-border">{t.code}</span>
                  {t.isArchived ? (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-surface-muted text-foreground-muted">Archived</span>
                  ) : t.activeVersion ? (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-success/10 text-success">Published v{t.activeVersion.versionNumber}</span>
                  ) : (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-warning/10 text-warning">Draft</span>
                  )}
                  {!t.isArchived && t.activeVersion && t.hasUnpublishedChanges && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-warning/10 text-warning">Unpublished changes</span>
                  )}
                </div>
                <p className="text-[14px] font-bold text-foreground">{t.name}</p>
                {t.description && <p className="text-[12px] text-foreground-muted mt-0.5 line-clamp-2">{t.description}</p>}
                {t.assignedCountries?.length > 0 && (
                  <p className="text-[11px] text-foreground-muted mt-1.5">
                    Used for: <strong className="text-foreground">{t.assignedCountries.map(label).join(", ")}</strong>
                  </p>
                )}
              </div>
              <div className="mt-auto flex items-center gap-1.5 flex-wrap">
                <button type="button" className={btnGhost} onClick={() => setPreviewing(t)}><Eye size={12} /> Preview</button>
                {!t.isArchived && (
                  <>
                    <button type="button" className={btnGhost} onClick={() => setEditing(t)}><Pencil size={12} /> Edit</button>
                    <button type="button" className={btnGhost} disabled={!t.activeVersion || busy}
                      title={!t.activeVersion ? "Publish the template first" : undefined}
                      onClick={() => setAssigning({ templateId: t.id })}><Layers size={12} /> Assign</button>
                    <button type="button" className={btnGhost} disabled={busy} onClick={() => archive(t)}><Archive size={12} /> Archive</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Built-in starters */}
      <p className="text-[13px] font-bold text-foreground mb-3">Start from a layout</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data.starters.map((s) => (
          <div key={s.key} className="rounded-[14px] border border-dashed border-border p-4 flex flex-col gap-3">
            <div>
              <p className="text-[14px] font-bold text-foreground">{s.name}</p>
              <p className="text-[12px] text-foreground-muted mt-0.5">{s.description}</p>
            </div>
            <div className="mt-auto flex items-center gap-1.5">
              <button type="button" className={btnGhost} onClick={() => setPreviewing({ name: s.name, latestVersion: s })}>
                <Eye size={12} /> Preview
              </button>
              <button type="button" className={btnPrimary} disabled={busy} onClick={() => startFromLayout(s)}>
                <Plus size={12} /> Use this layout
              </button>
            </div>
          </div>
        ))}
      </div>

      <PayslipTemplateEditorModal
        key={editing ? `edit-${editing.id}` : "edit-none"}
        template={editing}
        onClose={() => setEditing(null)}
        onSaved={load}
      />
      <PayslipTemplatePreviewModal
        key={previewing ? `preview-${previewing.id ?? previewing.name}` : "preview-none"}
        template={previewing}
        countries={data.countries}
        onClose={() => setPreviewing(null)}
      />
      <PayslipTemplatePdfImportModal
        key={pdfImportKey || "pdf-closed"}
        isOpen={pdfImportKey !== 0}
        onClose={() => setPdfImportKey(0)}
        onCreated={async (created) => { await load(); setEditing(created); }}
      />
      <PayslipTemplateImportModal
        isOpen={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={async (created) => { await load(); setEditing(created); }}
      />
      <PayslipTemplateAssignmentModal
        key={assigning ? `assign-${assigning.templateId ?? "any"}` : "assign-none"}
        request={assigning}
        templates={publishedTemplates}
        countries={data.countries}
        singleCountry={data.singleCountry}
        onClose={() => setAssigning(null)}
        onAssigned={(res) => setData((d) => ({ ...d, ...res }))}
      />
    </div>
  );
}
