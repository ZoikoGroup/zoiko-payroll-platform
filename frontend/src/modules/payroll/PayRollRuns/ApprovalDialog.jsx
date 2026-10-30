import { useState, useEffect, useCallback } from "react";
import { Loader2, CheckCircle2, Download, AlertCircle, ShieldCheck, Banknote } from "lucide-react";
import { approveRun, getBankTransferSummary, downloadBankTransferFile } from "../../../service/payrollService";
import { formatCurrency, getCountryNameFromCode } from "../../../utils/currency";
import CountryTotalsTable from "../../../components/payroll/CountryTotalsTable";

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

// Mixed-country run: totals per country, each in its own currency.
const COUNTRY_TOTAL_COLUMNS = [
  { key: "employeeCount", label: "Employees" },
  { key: "totalGross", label: "Gross", money: true },
  { key: "totalDeductions", label: "Deductions", money: true, accent: "text-error" },
  { key: "totalNet", label: "Net", money: true, accent: "text-primary" },
];

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
  // Keyed by country code for a mixed-country run ("" for a single file).
  const [downloadResults, setDownloadResults] = useState({});
  const [downloadingCountry, setDownloadingCountry] = useState(null);
  // The summary's top-level gross/net add currencies together when the run
  // pays more than one country — then only the per-country rows are shown,
  // and the bank file is downloaded once per country.
  const countries = summary?.countries || [];
  const isMultiCountry = countries.length > 1;

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

  const handleDownload = async (country = "") => {
    setDownloadingCountry(country);
    setError("");
    try {
      const result = await downloadBankTransferFile(run.id, undefined, country || undefined);
      setDownloadResults((prev) => ({ ...prev, [country]: result }));
    } catch (err) {
      setError(err?.message || "Failed to generate the bank transfer file. Please try again.");
    } finally {
      setDownloadingCountry(null);
    }
  };

  return (
    <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className={`bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full ${isMultiCountry ? "max-w-xl" : "max-w-md"} max-h-[85vh] overflow-y-auto`}
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
              {isMultiCountry ? (
                <SummaryRow label="Countries" value={`${countries.length} — totals by country below`} />
              ) : (
                <>
                  <SummaryRow label="Gross Payroll" value={fmtCurrencyLocal(summary?.grossPayroll, fmtCurrency)} />
                  <SummaryRow label="Total Deductions" value={fmtCurrencyLocal(summary?.totalDeductions, fmtCurrency)} accent="text-error" />
                  <SummaryRow label="Net Payroll" value={fmtCurrencyLocal(summary?.netPayroll, fmtCurrency)} accent="text-primary" />
                </>
              )}
              <SummaryRow label="Payment Date" value={fmtDate(summary?.paymentDate)} />
              {isApprovedStep && (
                <SummaryRow
                  label="Bank File Format"
                  value={FORMAT_LABELS[summary?.bankFormat] || (summary?.bankFormat || "CSV").toUpperCase()}
                />
              )}
            </div>

            {isMultiCountry && (
              <div className="mb-4">
                <p className="text-[12px] text-foreground-muted mb-2">
                  This run pays employees in {countries.length} countries. Each total is in that country&apos;s own currency.
                </p>
                <CountryTotalsTable rows={countries} columns={COUNTRY_TOTAL_COLUMNS} dense />
              </div>
            )}

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
                      {isMultiCountry
                        ? "Generate one bank transfer file per country (each in that country’s currency) in this run’s Banking Policy format "
                        : "Generate the bank transfer file for this run’s Banking Policy format "}
                      ({FORMAT_LABELS[summary?.bankFormat] || "CSV"}) and download it.
                    </p>
                    {Object.entries(downloadResults).map(([country, result]) => (
                      <p key={country || "all"} className="text-[12px] text-foreground mb-3">
                        Downloaded <span className="font-bold">{result.filename}</span> ({(result.size / 1024).toFixed(1)} KB)
                      </p>
                    ))}
                    {isMultiCountry ? (
                      <>
                        <div className="flex flex-col gap-2 mb-3">
                          {countries.map((c) => {
                            const busy = downloadingCountry === c.country;
                            return (
                              <button
                                key={c.country}
                                onClick={() => handleDownload(c.country)}
                                disabled={downloadingCountry !== null}
                                className="flex items-center justify-center gap-2 rounded-[10px] px-4 py-2 text-[13px] font-bold text-white bg-info hover:bg-info transition-colors disabled:opacity-60"
                              >
                                {busy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                                {busy
                                  ? "Generating…"
                                  : `${downloadResults[c.country] ? "Re-download" : "Download"} ${getCountryNameFromCode(c.country) || c.country} bank file (${c.currency})`}
                              </button>
                            );
                          })}
                        </div>
                        <div className="flex justify-end">
                          <button
                            onClick={onClose}
                            className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors"
                          >
                            Close
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="flex justify-end gap-3">
                        <button
                          onClick={onClose}
                          className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors"
                        >
                          Close
                        </button>
                        <button
                          onClick={() => handleDownload()}
                          disabled={downloadingCountry !== null}
                          className="flex items-center gap-2 rounded-[10px] px-4 py-2 text-[13px] font-bold text-white bg-info hover:bg-info transition-colors disabled:opacity-60"
                        >
                          {downloadingCountry !== null ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                          {downloadingCountry !== null ? "Generating…" : downloadResults[""] ? "Download Again" : "Generate & Download File"}
                        </button>
                      </div>
                    )}
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
