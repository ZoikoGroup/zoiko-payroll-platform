import { useState } from "react";
import { Download, CheckCircle2, AlertTriangle, FileArchive } from "lucide-react";
import { currency as formatCurrency } from "./pdfGenerators";
import { buildReportTable, downloadGeneratedReportAs } from "./templateReportRenderer";
import { downloadReportCertificatesZip } from "../../../service/payrollService";
import { useToast } from "../ToastContext";

function Row({ label, value }) {
  return (
    <div>
      <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</p>
      <p className="text-sm font-semibold text-foreground">{value ?? "—"}</p>
    </div>
  );
}

// Shown immediately after a successful "Generate Report" — every field
// here is read directly off the GeneratedReport record the backend
// returned, including templateVersion, which stays whatever version was
// ACTUALLY used at generation time even if a newer one is published later
// (see ReportsPage's history table, which applies the same rule).
export default function GeneratedReportPreview({ report, currencyCode = "INR" }) {
  const { addToast } = useToast() || {};
  const [downloadingZip, setDownloadingZip] = useState(false);
  if (!report) return null;
  const { columns, rows, totals } = buildReportTable(report);
  const reconciliationOk = report.reconciliation?.status === "MATCH";
  const isPerEmployee = report.documentScope === "PER_EMPLOYEE";

  async function handleDownloadZip() {
    setDownloadingZip(true);
    try {
      await downloadReportCertificatesZip(report.id);
    } catch {
      addToast?.("Failed to download certificates.", "error");
    } finally {
      setDownloadingZip(false);
    }
  }

  return (
    <div className="rounded-[18px] border border-border bg-surface p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-[15px] font-bold text-foreground">Report Preview</h3>
        <div className="flex items-center gap-2">
          {isPerEmployee ? (
            <button
              onClick={handleDownloadZip} disabled={downloadingZip}
              className="flex items-center gap-1.5 rounded-[12px] bg-primary text-white px-3.5 py-2 text-[13px] font-bold hover:bg-primary-hover disabled:opacity-50"
            >
              <FileArchive size={12} /> {downloadingZip ? "Preparing…" : "Download All Certificates (ZIP)"}
            </button>
          ) : (
            <>
              <button
                onClick={() => downloadGeneratedReportAs(report, "pdf")}
                className="flex items-center gap-1.5 rounded-[12px] bg-primary text-white px-3.5 py-2 text-[13px] font-bold hover:bg-primary-hover"
              >
                <Download size={12} /> PDF
              </button>
              <button
                onClick={() => downloadGeneratedReportAs(report, "xlsx")}
                className="flex items-center gap-1.5 rounded-[12px] border border-border px-3.5 py-2 text-[13px] font-bold text-foreground-secondary hover:bg-surface-muted"
              >
                <Download size={12} /> Excel
              </button>
              <button
                onClick={() => downloadGeneratedReportAs(report, "csv")}
                className="flex items-center gap-1.5 rounded-[12px] border border-border px-3.5 py-2 text-[13px] font-bold text-foreground-secondary hover:bg-surface-muted"
              >
                <Download size={12} /> CSV
              </button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Row label="Jurisdiction" value={`${report.jurisdictionCountry}${report.jurisdictionState ? ` / ${report.jurisdictionState}` : ""}`} />
        <Row label="Reporting Year" value={report.reportingYear} />
        <Row label="Reporting Period" value={report.reportingPeriod} />
        <Row label="Payroll Run" value={`#${report.payrollRunId}`} />
        <Row label="Template Version" value={`v${report.templateVersion}`} />
        <Row label="Generated" value={report.generatedAt ? new Date(report.generatedAt).toLocaleString() : "—"} />
        <Row label="Status" value={report.status} />
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Reconciliation</p>
          <p className={`flex items-center gap-1.5 text-sm font-semibold ${reconciliationOk ? "text-success" : "text-warning"}`}>
            {reconciliationOk ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {report.reconciliation?.status || "N/A"}
          </p>
        </div>
      </div>

      {report.reconciliation?.fieldDiffs && (
        <div className="rounded-[12px] border border-border-light overflow-hidden">
          <table className="w-full text-[12px]">
            <thead className="bg-surface-muted">
              <tr>
                <th className="px-3 py-2 text-left font-bold text-foreground-muted">Value</th>
                <th className="px-3 py-2 text-right font-bold text-foreground-muted">Payroll</th>
                <th className="px-3 py-2 text-right font-bold text-foreground-muted">Report</th>
                <th className="px-3 py-2 text-right font-bold text-foreground-muted">Difference</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {report.reconciliation.fieldDiffs.map((d) => (
                <tr key={d.field}>
                  <td className="px-3 py-2 font-medium text-foreground">{d.field}</td>
                  <td className="px-3 py-2 text-right text-foreground-secondary">{formatCurrency(d.runSum, currencyCode)}</td>
                  <td className="px-3 py-2 text-right text-foreground-secondary">{formatCurrency(d.reportSum, currencyCode)}</td>
                  <td className={`px-3 py-2 text-right font-semibold ${Math.abs(d.delta) > 0.005 ? "text-warning" : "text-success"}`}>
                    {formatCurrency(d.delta, currencyCode)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <div className="rounded-[12px] border border-border-light overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead className="bg-surface-muted">
              <tr>
                {columns.map((c) => (
                  <th key={c.key} className="px-3 py-2 text-left font-bold text-foreground-muted whitespace-nowrap">{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {rows.slice(0, 5).map((row, i) => (
                <tr key={row.payslipItemId ?? row.employeeName ?? i}>
                  {columns.map((c) => {
                    const value = c.accessor(row);
                    return (
                      <td key={c.key} className="px-3 py-2 whitespace-nowrap text-foreground-secondary">
                        {c.fieldType === "currency" ? formatCurrency(value, currencyCode) : (value ?? "—")}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {!isPerEmployee && (
            <p className="px-3 py-2 text-[11px] text-foreground-disabled">Aggregate report — one document covers the whole payroll run.</p>
          )}
          {isPerEmployee && rows.length > 5 && (
            <p className="px-3 py-2 text-[11px] text-foreground-disabled">+ {rows.length - 5} more employee{rows.length - 5 === 1 ? "" : "s"} — download for the full report.</p>
          )}
        </div>
      )}
    </div>
  );
}
