import { useState, useEffect, useCallback, useMemo } from "react";
import { BarChart3, FileText, History, Download, TrendingUp, Banknote } from "lucide-react";
import { useToast } from "../ToastContext";
import { getPayrollReports, downloadReport, downloadBankTransferFile } from "../../../service/payrollService";
import ReportGenerationPanel from "./ReportGenerationPanel";
import GeneratedReportPreview from "./GeneratedReportPreview";
import GeneratedReportsHistoryTable from "./GeneratedReportsHistoryTable";
import { usePayrollSetup } from "../PayrollSetupContext";

const tabs = [
  { id: "payroll-reports", label: "Payroll Reports", icon: BarChart3 },
  { id: "generate-report",  label: "Generate Report", icon: FileText },
  { id: "report-history",   label: "Report History",  icon: History },
];

export default function ReportsPage() {
  const { addToast } = useToast();
  const [activeTab, setActiveTab] = useState("payroll-reports");
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadCount, setDownloadCount] = useState(0);
  const [bankFileFormat, setBankFileFormat] = useState({});
  const [downloadingBankFileId, setDownloadingBankFileId] = useState(null);
  const { currencyCode } = usePayrollSetup();

  // The most recently generated statutory report (Generate Report tab) —
  // shown as a preview until the user generates another one or leaves
  // the tab. History of every past generation lives in Report History,
  // driven independently by GeneratedReportsHistoryTable's own fetch.
  const [latestGenerated, setLatestGenerated] = useState(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  const latestReport = useMemo(() => {
    if (!reports.length) return null;
    return [...reports].sort((a, b) => {
      const dateA = new Date(a.generatedAt || a.generated || 0);
      const dateB = new Date(b.generatedAt || b.generated || 0);
      return dateB - dateA;
    })[0];
  }, [reports]);

  const handleDownloadReport = useCallback(async (report) => {
    if (!report?.id) return;
    setDownloadingId(report.id);
    try {
      await downloadReport(report.id);
      setDownloadCount((c) => c + 1);
      addToast?.("Report downloaded successfully.", "success");
    } catch {
      addToast?.("Failed to download report.", "error");
    } finally {
      setDownloadingId(null);
    }
  }, [addToast]);

  const handleDownloadBankFile = useCallback(async (report) => {
    if (!report?.id) return;
    const format = bankFileFormat[report.id] || "csv";
    setDownloadingBankFileId(report.id);
    try {
      await downloadBankTransferFile(report.id, format);
      setDownloadCount((c) => c + 1);
      addToast?.(`Bank transfer file (${format.toUpperCase()}) downloaded.`, "success");
    } catch {
      addToast?.("Failed to generate bank transfer file.", "error");
    } finally {
      setDownloadingBankFileId(null);
    }
  }, [addToast, bankFileFormat]);

  const thisPeriodLabel = useMemo(() => {
    if (!latestReport) return "--";
    return latestReport.period || "--";
  }, [latestReport]);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPayrollReports();
      setReports(Array.isArray(data) ? data : []);
    } catch {
      addToast?.("Failed to load reports.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  return (
    <div className="bg-background min-h-screen p-6 lg:p-8 space-y-6">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-[12px] bg-primary flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
          <BarChart3 size={20} className="text-white" />
        </div>
        <div>
          <h1 className="text-[28px] font-extrabold tracking-tight text-foreground">Payroll Reports</h1>
          <p className="text-[13px] font-medium text-foreground-muted">Generate and download payroll reports</p>
        </div>
      </div>

      <div className="flex gap-1 bg-surface-muted rounded-[14px] p-1 w-fit flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
              activeTab === t.id ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
            }`}
          >
            <t.icon size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "payroll-reports" && (
        <div className="space-y-6">
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
              <div className="p-2.5 rounded-[12px] bg-primary/10">
                <FileText className="w-5 h-5 text-primary" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-foreground">{reports.length}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Total Reports</p>
              </div>
            </div>
            <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
              <div className="p-2.5 rounded-[12px] bg-info/10">
                <TrendingUp className="w-5 h-5 text-info" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-foreground">{thisPeriodLabel}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">This Period</p>
              </div>
            </div>
            <div className="bg-surface border border-border rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200">
              <div className="p-2.5 rounded-[12px] bg-warning/10">
                <Download className="w-5 h-5 text-warning" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-foreground">{downloadCount}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Downloads</p>
              </div>
            </div>
          </div>

          <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
            {loading ? (
              <div className="text-center py-12 space-y-3">
                <div className="flex justify-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
                  <div className="h-2 w-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
                  <div className="h-2 w-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
                <p className="text-[13px] text-foreground-muted">Loading reports...</p>
              </div>
            ) : reports.length === 0 ? (
              <div className="text-center py-16">
                <BarChart3 size={40} className="mx-auto mb-3 text-foreground-muted" />
                <p className="text-[15px] font-bold text-foreground">No reports yet</p>
                <p className="text-[13px] text-foreground-muted mt-1">Reports will appear here once payroll runs are completed</p>
              </div>
            ) : (
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Report Name</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Period</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Generated</th>
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Status</th>
                    <th className="px-5 py-3.5" />
                    <th className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Bank Transfer File</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {reports.map((r, i) => (
                    <tr key={r.id || i} className="hover:bg-background dark:hover:bg-surface-muted transition-colors duration-150">
                      <td className="px-5 py-4 font-semibold text-foreground">{r.name || "Payroll Report"}</td>
                      <td className="px-5 py-4 text-[13px] text-foreground-muted">{r.period || "-"}</td>
                      <td className="px-5 py-4 text-[13px] text-foreground-muted">{r.generatedAt || r.generated || "-"}</td>
                      <td className="px-5 py-4">
                        <span className="inline-flex items-center gap-1 rounded-full bg-info/10 text-info px-3 py-1 text-[11px] font-bold">
                          {r.status || "available"}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <button
                          onClick={() => handleDownloadReport(r)}
                          disabled={downloadingId === r.id}
                          className="flex items-center gap-1.5 rounded-[12px] bg-primary text-white px-3.5 py-2 text-[13px] font-bold hover:bg-primary-hover transition-all duration-200 shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <Download size={12} /> {downloadingId === r.id ? "Downloading..." : "Download"}
                        </button>
                      </td>
                      <td className="px-5 py-4">
                        {r.status === "available" ? (
                          <div className="flex items-center gap-2">
                            <select
                              value={bankFileFormat[r.id] || "csv"}
                              onChange={(e) => setBankFileFormat((prev) => ({ ...prev, [r.id]: e.target.value }))}
                              className="rounded-[10px] border border-border bg-background px-2.5 py-2 text-[12px] font-semibold text-foreground focus:outline-none focus:border-category-teal focus:ring-2 focus:ring-category-teal/20"
                            >
                              <option value="csv">CSV</option>
                              <option value="xlsx">Excel (.xlsx)</option>
                              <option value="txt">TXT</option>
                              <option value="pdf">PDF</option>
                            </select>
                            <button
                              onClick={() => handleDownloadBankFile(r)}
                              disabled={downloadingBankFileId === r.id}
                              title="Generate and download this run's bank transfer file"
                              className="flex items-center gap-1.5 rounded-[12px] bg-category-teal text-white px-3.5 py-2 text-[13px] font-bold hover:bg-category-teal transition-all duration-200 shadow-[0_2px_8px_rgba(157,123,242,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Banknote size={12} /> {downloadingBankFileId === r.id ? "Generating..." : "Download"}
                            </button>
                          </div>
                        ) : (
                          <span className="text-[12px] text-foreground-muted">Available once approved</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {activeTab === "generate-report" && (
        <div className="space-y-6">
          <ReportGenerationPanel
            onGenerated={(report) => {
              setLatestGenerated(report);
              setHistoryRefreshKey((k) => k + 1);
            }}
          />
          {latestGenerated && <GeneratedReportPreview report={latestGenerated} currencyCode={currencyCode} />}
        </div>
      )}

      {activeTab === "report-history" && (
        <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
          <GeneratedReportsHistoryTable
            refreshKey={historyRefreshKey}
            onView={(report) => { setLatestGenerated(report); setActiveTab("generate-report"); }}
          />
        </div>
      )}
    </div>
  );
}
