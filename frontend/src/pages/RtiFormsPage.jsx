import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, FileText } from "lucide-react";
import { getRtiFormsSummary } from "../service/superAdminService";

// Super Admin > Compliance > RTI & Forms (§19 gap-closure Part 11,
// 2026-09-09) — cross-org view of every UK FPS/EPS/P45/P60 generated,
// with its schema version and submission-tracking status. Read-only:
// generation itself happens from the org's own Reports screen / the
// employee-level P45/P60 flow, not here.
//
// Widened 2026-09-10 to also list India's Form 130/138/123 (gap-closure
// Phase E follow-up) — Super Admin previously had no cross-org view of
// India form generation at all. India rows always show "Not tracked" in
// the Submission column: RTI electronic-filing tracking is a UK-only
// concept, not something India forms have (or need) today.
const STATUS_COLORS = {
  Generated: "bg-info/10 text-info", Superseded: "bg-foreground-disabled/10 text-foreground-disabled", Void: "bg-error/10 text-error",
};
const SUBMISSION_COLORS = {
  DRAFT: "bg-foreground-disabled/10 text-foreground-disabled", READY: "bg-warning/10 text-warning",
  SUBMITTED: "bg-info/10 text-info", ACKNOWLEDGED: "bg-success/10 text-success", REJECTED: "bg-error/10 text-error",
};

export default function RtiFormsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reportTypeFilter, setReportTypeFilter] = useState("");

  useEffect(() => {
    getRtiFormsSummary().then(setRows).finally(() => setLoading(false));
  }, []);

  const filtered = reportTypeFilter ? rows.filter((r) => r.reportType === reportTypeFilter) : rows;

  return (
    <div>
      <Link to="/super-admin/compliance" className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
        <ArrowLeft size={14} /> Back to Compliance
      </Link>
      <div className="mb-6 flex items-center gap-2">
        <FileText size={20} className="text-primary" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">RTI & Statutory Forms</h1>
          <p className="text-sm text-foreground-muted mt-0.5">Every UK FPS/EPS/P45/P60 and India Form 130/138/123 generated, across all organizations, with submission tracking status where it applies.</p>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit flex-wrap">
        {["", "FPS", "EPS", "P45", "P60", "FORM_130", "FORM_138", "FORM_123"].map((t) => (
          <button
            key={t || "all"} onClick={() => setReportTypeFilter(t)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${reportTypeFilter === t ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {t ? (t.startsWith("FORM_") ? `Form ${t.replace("FORM_", "")}` : t) : "All"}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-sm text-foreground-disabled">
          No filings generated yet for this filter. A report's template needs to be authored and activated first
          (Super Admin &gt; Report Templates &gt; the relevant jurisdiction) before any organization can generate against it.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead className="bg-surface-muted text-foreground-muted">
              <tr>
                <th className="px-4 py-3 text-left">Org</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Template Version</th>
                <th className="px-4 py-3 text-left">Tax Year / Period</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Reconciliation</th>
                <th className="px-4 py-3 text-left">Generated</th>
                <th className="px-4 py-3 text-left">Submission</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.generatedReportId} className="border-t border-border">
                  <td className="px-4 py-3">Org #{r.organizationId}</td>
                  <td className="px-4 py-3 font-semibold">{r.reportType.startsWith("FORM_") ? `Form ${r.reportType.replace("FORM_", "")}` : r.reportType}</td>
                  <td className="px-4 py-3">v{r.templateVersion}</td>
                  <td className="px-4 py-3">{r.reportingYear}{r.reportingPeriod ? ` · ${r.reportingPeriod}` : ""}</td>
                  <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_COLORS[r.status] || ""}`}>{r.status}</span></td>
                  <td className="px-4 py-3">{r.reconciliationStatus || "—"}</td>
                  <td className="px-4 py-3">{r.generatedAt ? new Date(r.generatedAt).toLocaleDateString() : "—"}</td>
                  <td className="px-4 py-3">
                    {r.submissions.length === 0 ? (
                      <span className="text-foreground-disabled">Not tracked</span>
                    ) : (
                      r.submissions.map((s) => (
                        <span key={s.id} className={`mr-1 rounded-full px-2 py-0.5 font-semibold ${SUBMISSION_COLORS[s.status] || ""}`}>{s.status}</span>
                      ))
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
