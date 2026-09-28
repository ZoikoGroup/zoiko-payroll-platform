import { SgStatus } from "./SGStatutorySummaryTab";
import { formatDate } from "./sgComponentConfig";
import useSgStatutorySummary from "./useSgStatutorySummary";

// Singapore report-template overview (Phase 5.6) — the summary endpoint's
// reportTemplates section: the 11 intended templates, whether each exists,
// its lifecycle status and Zoiko's own classification. Authoring and the
// Draft → Active lifecycle stay in the shared Report Templates module.
const CLASSIFICATION_TEXT = {
  EXPORT_READY: "Export ready — the employer submits it",
  SUBMISSION_SUPPORT: "Submission support — figures for reconciliation",
  INTERNAL_REPORT: "Internal report",
  STATUTORY_WORKSPACE: "Statutory workspace — internal compliance view",
};

export default function SGReportTemplatesTab() {
  const { loading, error, data } = useSgStatutorySummary(undefined);
  const section = (data?.sections || []).find((s) => s.key === "reportTemplates");

  return (
    <div className="space-y-3">
      <p className="rounded-lg border border-border bg-surface-muted/50 p-2 text-xs text-foreground-muted">
        None of these templates is certified or approved by CPF Board, IRAS, MOM or PDPC. The classification is Zoiko&apos;s own.
        Lifecycle: Draft → Review → Approved (distinct approver) → Published → Active; only an Active template can be generated,
        and a changed template is a new version — lifecycle actions stay in the Report Templates module.
      </p>
      {loading && <p className="text-sm text-foreground-muted">Loading…</p>}
      {error && <p className="text-sm text-error" role="alert">{error}</p>}
      {section && (
        <>
          <div className="flex items-center gap-2 text-xs">
            <SgStatus status={section.status} />
            <span className="text-foreground-muted">{section.values.present} of {section.values.expected} present · {section.values.active} Active · {section.values.generatorTypes} report types with a generator</span>
            {section.values.unexpectedTemplateKeys.length > 0 && (
              <span className="text-warning">Unexpected SG templates: {section.values.unexpectedTemplateKeys.join(", ")}</span>
            )}
          </div>
          <ul className="flex flex-wrap gap-2 text-[11px]" aria-label="Templates by lifecycle status">
            {Object.entries(section.values.statusCounts || {}).map(([st, n]) => (
              <li key={st} className="rounded-full border border-border px-2 py-0.5 text-foreground-secondary">{st}: <b className="text-foreground">{n}</b></li>
            ))}
            <li className="px-1 text-foreground-muted">No &ldquo;Deprecated&rdquo; state exists here — a retired version is Superseded.</li>
          </ul>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-muted text-foreground-muted">
                <tr>
                  {["Code", "Report", "Classification", "Status", "Next allowed", "Version", "Effective", "Approval", "Audit", "Output", "Generator"].map((h) => (
                    <th key={h} scope="col" className="px-3 py-2 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {section.values.templates.map((t) => (
                  <tr key={t.templateKey} className="border-t border-border">
                    <td className="px-3 py-2 font-mono text-foreground">{t.templateKey}</td>
                    <td className="px-3 py-2 text-foreground">{t.name}{t.description ? <span className="block max-w-md text-[11px] text-foreground-muted">{t.description}</span> : null}</td>
                    <td className="px-3 py-2 text-foreground-secondary" title={t.classification}>{CLASSIFICATION_TEXT[t.classification] || t.classification}</td>
                    <td className="px-3 py-2">{t.present ? t.status : <span className="text-warning">Not seeded</span>}</td>
                    <td className="px-3 py-2 text-foreground-muted">{t.present ? ((t.allowedNextStatuses || []).join(", ") || "Final") : "—"}{t.updatedAt ? <span className="block">updated {formatDate(t.updatedAt.slice(0, 10))}</span> : null}</td>
                    <td className="px-3 py-2">{t.version || "—"}</td>
                    <td className="px-3 py-2">{formatDate(t.effectiveFrom)}</td>
                    <td className="px-3 py-2">{t.approvedById ? <>User #{t.approvedById}{t.approvedAt ? <span className="block text-foreground-muted">{formatDate(t.approvedAt.slice(0, 10))}</span> : null}</> : <span className="text-foreground-disabled">Not approved</span>}</td>
                    <td className="px-3 py-2 text-foreground-muted">{t.present ? `${t.auditEntries} entries · ${t.versionCount} version(s)` : "—"}{t.present && !t.editable ? <span className="block">Locked (not editable)</span> : null}</td>
                    <td className="px-3 py-2">{t.documentScope || "—"}</td>
                    <td className="px-3 py-2 text-foreground-muted">{t.generator === "GENERIC_TEMPLATE" ? "Generic (payslip columns)" : t.generator}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
