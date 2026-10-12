import { Link } from "react-router-dom";
import ReportTemplateLayout from "../../reportTemplates/ReportTemplateLayout";
import { SgStatus } from "./SGStatutorySummaryTab";
import { formatDate } from "./sgComponentConfig";
import useSgStatutorySummary from "./useSgStatutorySummary";

// Singapore report-template overview (Phase 5.6) — the summary endpoint's
// reportTemplates section: the 11 intended templates, whether each exists,
// its lifecycle status and Zoiko's own classification. Final closure: the
// lifecycle controls (Approve, status, versions, audit) are the shared
// Report Templates module, embedded below and reachable at
// /super-admin/report-templates/singapore — every rule enforced server-side.
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
        and a changed template is a new version. The lifecycle controls are below (also at{" "}
        <Link to="/super-admin/report-templates/singapore" className="font-semibold text-primary hover:underline">Report Templates → Singapore</Link>);
        every transition, approval and refusal is enforced and audited by the server.
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
                  {["Code", "Report", "Classification", "Status", "Next allowed", "Version", "Effective", "Source", "Approval", "Audit", "Output", "Generator", "Official certification"].map((h) => (
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
                    <td className="px-3 py-2">
                      {t.present ? t.status : <span className="text-warning">Not seeded</span>}
                      {t.present && t.activeVersion && t.activeVersion !== t.version
                        ? <span className="block text-[11px] text-foreground-muted">Active: v{t.activeVersion}</span> : null}
                      {t.present && !t.generatable ? <span className="block text-[11px] text-warning">Not generatable</span> : null}
                    </td>
                    <td className="px-3 py-2 text-foreground-muted">{t.present ? ((t.allowedNextStatuses || []).join(", ") || "Final") : "—"}{t.updatedAt ? <span className="block">updated {formatDate(t.updatedAt.slice(0, 10))}</span> : null}</td>
                    <td className="px-3 py-2">
                      {t.version || "—"}
                      {t.previousVersionId ? <span className="block text-[11px] text-foreground-muted">prev #{t.previousVersionId}</span> : null}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{t.present ? `${formatDate(t.effectiveFrom)} – ${t.effectiveTo ? formatDate(t.effectiveTo) : "open"}` : "—"}</td>
                    <td className="px-3 py-2 text-foreground-muted">
                      {t.source
                        ? <span title={t.source.sha256 ? `sha256 ${t.source.sha256}` : undefined}>{t.source.agency} — {t.source.title}{t.source.reviewed ? "" : " (unreviewed)"}</span>
                        : (t.regulatoryAuthority || t.regulatoryAuthorityCatalog || "—")}
                    </td>
                    <td className="px-3 py-2">{t.approvedById ? <>User #{t.approvedById}{t.approvedAt ? <span className="block text-foreground-muted">{formatDate(t.approvedAt.slice(0, 10))}</span> : null}</> : <span className="text-foreground-disabled">Not approved</span>}</td>
                    <td className="px-3 py-2 text-foreground-muted">{t.present ? `${t.auditEntries} entries · ${t.versionCount} version(s)` : "—"}{t.present && !t.editable ? <span className="block">Locked (not editable)</span> : null}</td>
                    <td className="px-3 py-2">{t.documentScope || "—"}</td>
                    <td className="px-3 py-2 text-foreground-muted">{t.generator === "GENERIC_TEMPLATE" ? "Generic (payslip columns)" : t.generator}</td>
                    <td className="px-3 py-2">
                      {t.officialCertification ? "Yes" : <span className="text-foreground-muted">No</span>}
                      {t.externalValidation ? <span className="block text-[11px] text-warning">{t.externalValidation.replace(/_/g, " ").toLowerCase()}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <section aria-labelledby="sg-template-lifecycle" className="rounded-xl border border-border p-4">
        <h3 id="sg-template-lifecycle" className="mb-2 text-sm font-bold text-foreground">Lifecycle controls — Approve · Review → Approved → Published → Active → Superseded · versions · audit</h3>
        <ReportTemplateLayout country="SG" countryName="Singapore" embedded />
      </section>
    </div>
  );
}
