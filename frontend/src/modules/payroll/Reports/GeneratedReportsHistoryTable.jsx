import { useState, useEffect, useCallback } from "react";
import { Download, Eye, CheckCircle2, AlertTriangle, FileArchive } from "lucide-react";
import { getGeneratedReports, downloadReportCertificatesZip } from "../../../service/payrollService";
import { downloadGeneratedReportAs } from "./templateReportRenderer";
import { useToast } from "../ToastContext";

// Every row's "Template Version" is read verbatim from the stored
// GeneratedReport record — never re-resolved against whatever template
// version is currently Active. A report generated against v1.2 keeps
// showing v1.2 forever, even after Super Admin publishes v1.3 (historical
// immutability — see backend generate_report_from_template's snapshot).
export default function GeneratedReportsHistoryTable({ refreshKey, onView }) {
  const { addToast } = useToast();
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getGeneratedReports();
      setReports(Array.isArray(data) ? data : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  async function handleDownload(report, format) {
    setDownloadingId(`${report.id}-${format}`);
    try {
      downloadGeneratedReportAs(report, format);
    } catch {
      addToast?.("Failed to download report.", "error");
    } finally {
      setDownloadingId(null);
    }
  }

  // PER_EMPLOYEE reports (Form 130/P60-style certificates) have no
  // meaningful single-file table export — each employee gets their own
  // document, so "download" means every employee's certificate as one ZIP.
  async function handleDownloadCertificates(report) {
    setDownloadingId(`${report.id}-zip`);
    try {
      await downloadReportCertificatesZip(report.id);
    } catch {
      addToast?.("Failed to download certificates.", "error");
    } finally {
      setDownloadingId(null);
    }
  }

  if (loading) {
    return <p className="py-8 text-center text-[13px] text-foreground-disabled">Loading generated reports…</p>;
  }

  if (reports.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-[15px] font-bold text-foreground">No reports generated yet</p>
        <p className="text-[13px] text-foreground-muted mt-1">Use the Generate Report panel above to produce your first statutory report.</p>
      </div>
    );
  }

  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-border">
          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Report</th>
          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Period</th>
          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Template Version</th>
          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Status</th>
          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Reconciliation</th>
          <th className="px-4 py-3" />
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {reports.map((r) => {
          const reconciled = r.reconciliation?.status === "MATCH";
          return (
            <tr key={r.id} className="hover:bg-background dark:hover:bg-surface-muted transition-colors duration-150">
              <td className="px-4 py-3 font-semibold text-foreground">{r.reportType}</td>
              <td className="px-4 py-3 text-foreground-muted">{r.reportingPeriod || "—"}</td>
              <td className="px-4 py-3 text-foreground-muted">v{r.templateVersion}</td>
              <td className="px-4 py-3">
                <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-[11px] font-bold ${
                  r.status === "Generated" ? "bg-info/10 text-info" : r.status === "Void" ? "bg-error/10 text-error" : "bg-surface-muted text-foreground-muted"
                }`}>
                  {r.status}
                </span>
              </td>
              <td className="px-4 py-3">
                <span className={`flex items-center gap-1 text-[12px] font-semibold ${reconciled ? "text-success" : "text-warning"}`}>
                  {reconciled ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                  {r.reconciliation?.status || "N/A"}
                </span>
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center justify-end gap-1.5">
                  <button onClick={() => onView?.(r)} title="View" className="rounded-[10px] border border-border p-2 text-foreground-secondary hover:bg-surface-muted">
                    <Eye size={13} />
                  </button>
                  {r.documentScope === "PER_EMPLOYEE" ? (
                    <button
                      onClick={() => handleDownloadCertificates(r)} disabled={downloadingId === `${r.id}-zip`}
                      title="Download all employee certificates (ZIP)" className="rounded-[10px] border border-border p-2 text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
                    >
                      <FileArchive size={13} />
                    </button>
                  ) : (
                    <button
                      onClick={() => handleDownload(r, "pdf")} disabled={downloadingId === `${r.id}-pdf`}
                      title="Download PDF" className="rounded-[10px] border border-border p-2 text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
                    >
                      <Download size={13} />
                    </button>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
