import { useState, useEffect, useCallback } from "react";
import { Loader2, CheckCircle2, Download, AlertCircle, ShieldCheck, Banknote } from "lucide-react";
import { approveRun, getBankTransferSummary, downloadBankTransferFile } from "../../../service/payrollService";
import { formatCurrency } from "../../../utils/currency";

function fmtCurrencyLocal(n, fmtCurrency) {
  if (fmtCurrency) return fmtCurrency(n);
  if (n == null) return "—";
  return formatCurrency(n);
}

function fmtDate(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return String(v);
  }
}

const FORMAT_LABELS = { csv: "CSV", xlsx: "Excel (.xlsx)", txt: "TXT" };

// Copy + icon per target status — the summary/confirm/success shape stays
// identical across all three; only wording and the Approved-only bank-file
// step change.
const STATUS_META = {
  Approved: {
    verb: "Approve", title: "Approve Payroll Run", confirming: "Approving…",
    confirmedLine: "Run approved successfully.", icon: CheckCircle2, accent: "#19C58A",
  },
  Authorized: {
    verb: "Authorize", title: "Authorize Payroll Run", confirming: "Authorizing…",
    confirmedLine: "Run authorized successfully — ready for payment.", icon: ShieldCheck, accent: "#35B6F5",
  },
  Paid: {
    verb: "Mark as Paid", title: "Mark Payroll Run as Paid", confirming: "Marking as paid…",
    confirmedLine: "Run marked as paid. Payslips have been finalized.", icon: Banknote, accent: "#9D7BF2",
  },
};

function SummaryRow({ label, value, accent }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-[12px] font-medium text-foreground-muted">{label}</span>
      <span className={`text-[13px] font-bold ${accent || "text-foreground"}`}>{value}</span>
    </div>
  );
}

export default function ApprovalDialog({ run, targetStatus = "Approved", onClose, onApproved, fmtCurrency }) {
  const meta = STATUS_META[targetStatus] || STATUS_META.Approved;
  const isApprovedStep = targetStatus === "Approved";
  const Icon = meta.icon;

  // stage: "summary" (pre-confirm) -> "confirming" -> "confirmed" (+ bank file preview/download, Approved step only)
  const [stage, setStage] = useState("summary");
  const [summary, setSummary] = useState(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [error, setError] = useState("");
  const [downloadResult, setDownloadResult] = useState(null);
  const [downloading, setDownloading] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    setError("");
    try {
      const data = await getBankTransferSummary(run.id);
      setSummary(data);
    } catch {
      setError("Could not load the payroll summary for this run.");
    } finally {
      setLoadingSummary(false);
    }
  }, [run.id]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const handleConfirm = async () => {
    setStage("confirming");
    setError("");
    try {
      await approveRun(run.id);
      setStage("confirmed");
      onApproved?.();
    } catch {
      setError(`Failed to ${meta.verb.toLowerCase()} this payroll run. Please try again.`);
      setStage("summary");
    }
  };

  const handleDownload = async () => {
    setDownloading(true);
    setError("");
    try {
      const result = await downloadBankTransferFile(run.id);
      setDownloadResult(result);
    } catch {
      setError("Failed to generate the bank transfer file. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full max-w-md max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 mb-1">
          <Icon size={17} style={{ color: meta.accent }} />
          <h3 className="text-[15px] font-bold text-foreground">
            {stage === "confirmed" ? `Run ${targetStatus}` : meta.title}
          </h3>
        </div>
        <p className="text-[12px] text-foreground-muted mb-4">{run.period}</p>

        {loadingSummary ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 size={20} className="animate-spin" style={{ color: meta.accent }} />
          </div>
        ) : (
          <>
            <div className="rounded-[12px] bg-background px-4 py-1 mb-4 divide-y divide-border">
              <SummaryRow label="Total Employees" value={summary?.totalEmployees ?? "—"} />
              <SummaryRow label="Gross Payroll" value={fmtCurrencyLocal(summary?.grossPayroll, fmtCurrency)} />
              <SummaryRow label="Total Deductions" value={fmtCurrencyLocal(summary?.totalDeductions, fmtCurrency)} accent="text-error" />
              <SummaryRow label="Net Payroll" value={fmtCurrencyLocal(summary?.netPayroll, fmtCurrency)} accent="text-primary" />
              <SummaryRow label="Payment Date" value={fmtDate(summary?.paymentDate)} />
              {isApprovedStep && (
                <SummaryRow
                  label="Bank File Format"
                  value={FORMAT_LABELS[summary?.bankFormat] || (summary?.bankFormat || "CSV").toUpperCase()}
                />
              )}
            </div>

            {error && (
              <div className="mb-4 flex items-start gap-2 rounded-[10px] bg-error/10 px-3.5 py-2.5 text-[12px] text-error">
                <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
                {error}
              </div>
            )}

            {stage !== "confirmed" ? (
              <div className="flex justify-end gap-3">
                <button
                  onClick={onClose}
                  className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirm}
                  disabled={stage === "confirming"}
                  className="flex items-center gap-2 rounded-[10px] px-4 py-2 text-[13px] font-bold text-white transition-colors disabled:opacity-60"
                  style={{ backgroundColor: meta.accent }}
                >
                  {stage === "confirming" ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
                  {stage === "confirming" ? meta.confirming : `Confirm ${meta.verb}`}
                </button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-4 text-[13px] font-semibold" style={{ color: meta.accent }}>
                  <CheckCircle2 size={16} />
                  {meta.confirmedLine}
                </div>

                {isApprovedStep ? (
                  <>
                    <p className="text-[12px] text-foreground-muted mb-3">
                      Generate the bank transfer file for this run's Banking Policy format
                      ({FORMAT_LABELS[summary?.bankFormat] || "CSV"}) and download it.
                    </p>
                    {downloadResult && (
                      <p className="text-[12px] text-foreground mb-3">
                        Downloaded <span className="font-bold">{downloadResult.filename}</span> ({(downloadResult.size / 1024).toFixed(1)} KB)
                      </p>
                    )}
                    <div className="flex justify-end gap-3">
                      <button
                        onClick={onClose}
                        className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors"
                      >
                        Close
                      </button>
                      <button
                        onClick={handleDownload}
                        disabled={downloading}
                        className="flex items-center gap-2 rounded-[10px] px-4 py-2 text-[13px] font-bold text-white bg-info hover:bg-info transition-colors disabled:opacity-60"
                      >
                        {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                        {downloading ? "Generating…" : downloadResult ? "Download Again" : "Generate & Download File"}
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="flex justify-end">
                    <button
                      onClick={onClose}
                      className="rounded-[10px] px-4 py-2 text-[13px] font-bold text-white transition-colors"
                      style={{ backgroundColor: meta.accent }}
                    >
                      Done
                    </button>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
