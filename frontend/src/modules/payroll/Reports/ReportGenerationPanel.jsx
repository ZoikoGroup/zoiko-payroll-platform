import { useState, useEffect, useCallback, useMemo } from "react";
import { Loader2, AlertTriangle, CheckCircle2, CalendarClock } from "lucide-react";
import { useToast } from "../ToastContext";
import { usePayrollSetup } from "../PayrollSetupContext";
import {
  fetchRuns, getAvailableReports, getApplicableReportTemplate, generateReport, getUpcomingFilingDates,
} from "../../../service/payrollService";

const inputClass = "w-full rounded-[10px] border border-border bg-background px-3 py-2 text-[13px] font-medium text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";

// Organization Report Generation — the org selects jurisdiction (fixed,
// from its own profile) -> reporting year -> reporting period -> a
// finalized payroll run -> a report, and the system auto-loads whichever
// Published/Active template applies. The org never configures statutory
// report components/fields itself — that only happens in Super Admin's
// Report Templates authoring surface.
//
// Selector ordering: Period is resolved from Year before Run, and Run
// before Report — a Payroll Run always belongs to exactly one period, so
// deriving Period options from Year (not the reverse) is what makes
// "period mismatch" a real, checkable validation state rather than
// something that could never fail.
export default function ReportGenerationPanel({ onGenerated }) {
  const { addToast } = useToast();
  const { company } = usePayrollSetup();
  const jurisdictionCountry = company?.jurisdictionCountry || company?.jurisdiction_country || "IN";

  const [allRuns, setAllRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [upcomingFilings, setUpcomingFilings] = useState([]);

  useEffect(() => { getUpcomingFilingDates(5).then(setUpcomingFilings); }, []);

  const [selectedYear, setSelectedYear] = useState("");
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [reports, setReports] = useState([]);
  const [selectedReportType, setSelectedReportType] = useState("");

  const [applicable, setApplicable] = useState(null); // { template, validation }
  const [loadingApplicable, setLoadingApplicable] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setLoadingRuns(true);
    fetchRuns().then((runs) => setAllRuns(Array.isArray(runs) ? runs : [])).finally(() => setLoadingRuns(false));
  }, []);

  const years = useMemo(() => {
    const set = new Set(allRuns.map((r) => (r.payDate || "").slice(0, 4)).filter(Boolean));
    return Array.from(set).sort().reverse();
  }, [allRuns]);

  const runsInYear = useMemo(
    () => allRuns.filter((r) => (r.payDate || "").slice(0, 4) === selectedYear),
    [allRuns, selectedYear],
  );
  const periods = useMemo(() => {
    const set = new Set(runsInYear.map((r) => r.period).filter(Boolean));
    return Array.from(set);
  }, [runsInYear]);

  const FINALIZED_STATUSES = ["Approved", "Authorized", "Paid", "Closed"];
  const finalizedRunsInPeriod = useMemo(
    () => runsInYear.filter((r) => r.period === selectedPeriod && FINALIZED_STATUSES.includes(r.status)),
    [runsInYear, selectedPeriod],
  );

  // Narrow each downstream selection when its parent changes.
  useEffect(() => { setSelectedPeriod(""); setSelectedRunId(""); }, [selectedYear]);
  useEffect(() => { setSelectedRunId(""); }, [selectedPeriod]);

  useEffect(() => {
    if (!selectedYear) { setReports([]); return; }
    getAvailableReports({ reportingYear: selectedYear }).then(setReports);
    setSelectedReportType("");
  }, [selectedYear]);

  const loadApplicable = useCallback(() => {
    if (!selectedRunId || !selectedReportType || !selectedYear) { setApplicable(null); return; }
    setLoadingApplicable(true);
    getApplicableReportTemplate({ reportingYear: selectedYear, reportType: selectedReportType, payrollRunId: selectedRunId })
      .then(setApplicable)
      .catch(() => setApplicable(null))
      .finally(() => setLoadingApplicable(false));
  }, [selectedRunId, selectedReportType, selectedYear]);

  useEffect(() => { loadApplicable(); }, [loadApplicable]);

  const validation = applicable?.validation;
  const canGenerate = Boolean(applicable?.template) && Boolean(
    validation && validation.jurisdictionMatch && validation.runFinalized && validation.periodMatch && validation.templatePublished,
  );

  async function handleGenerate() {
    setGenerating(true);
    try {
      const report = await generateReport({
        reportTemplateId: applicable.template.id, payrollRunId: Number(selectedRunId), reportingPeriod: selectedPeriod,
      });
      addToast?.("Report generated.", "success");
      onGenerated?.(report);
    } catch (err) {
      addToast?.(err.message || "Failed to generate report.", "error");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] space-y-4">
      <h3 className="text-[15px] font-bold text-foreground">Generate Report</h3>

      {upcomingFilings.length > 0 && (
        <div className="rounded-[12px] border border-warning/30 bg-warning/5 p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-bold text-foreground">
            <CalendarClock size={13} className="text-warning" /> Upcoming Filing Due Dates
          </p>
          <div className="flex flex-wrap gap-3">
            {upcomingFilings.map((f) => (
              <span key={f.id} className="text-[12px] text-foreground-secondary">
                <span className="font-semibold">{f.reportType} {f.periodKey}</span> due {f.dueDate}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div>
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Jurisdiction</label>
          <input className={inputClass} value={jurisdictionCountry} disabled />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Reporting Year</label>
          <select className={inputClass} value={selectedYear} onChange={(e) => setSelectedYear(e.target.value)} disabled={loadingRuns}>
            <option value="">Select…</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Reporting Period</label>
          <select className={inputClass} value={selectedPeriod} onChange={(e) => setSelectedPeriod(e.target.value)} disabled={!selectedYear}>
            <option value="">Select…</option>
            {periods.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Payroll Run</label>
          <select className={inputClass} value={selectedRunId} onChange={(e) => setSelectedRunId(e.target.value)} disabled={!selectedPeriod}>
            <option value="">Select…</option>
            {finalizedRunsInPeriod.map((r) => <option key={r.id} value={r.id}>{r.runCode || `Run #${r.id}`} — {r.status}</option>)}
          </select>
          {selectedPeriod && finalizedRunsInPeriod.length === 0 && (
            <p className="mt-1 text-[11px] text-warning">No finalized runs for this period yet.</p>
          )}
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Report</label>
          <select className={inputClass} value={selectedReportType} onChange={(e) => setSelectedReportType(e.target.value)} disabled={!selectedYear || reports.length === 0}>
            <option value="">Select…</option>
            {reports.map((r) => <option key={r.reportType} value={r.reportType}>{r.name}</option>)}
          </select>
          {selectedYear && reports.length === 0 && (
            <p className="mt-1 text-[11px] text-warning">No published report templates for this jurisdiction/year yet.</p>
          )}
        </div>
      </div>

      {selectedRunId && selectedReportType && (
        <div className="rounded-[12px] border border-border-light bg-background p-3.5 space-y-2">
          {loadingApplicable ? (
            <p className="flex items-center gap-2 text-[13px] text-foreground-muted"><Loader2 size={14} className="animate-spin" /> Resolving applicable template…</p>
          ) : applicable?.template ? (
            <>
              <p className="text-[13px] font-semibold text-foreground">
                Template: {applicable.template.name} v{applicable.template.version}
                <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] font-bold ${applicable.template.status === "Active" ? "bg-success/10 text-success" : "bg-info/10 text-info"}`}>
                  {applicable.template.status}
                </span>
              </p>
              {!canGenerate && validation?.reasons?.length > 0 && (
                <ul className="space-y-1">
                  {validation.reasons.map((reason, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-[12px] text-warning">
                      <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" /> {reason}
                    </li>
                  ))}
                </ul>
              )}
              {canGenerate && (
                <p className="flex items-center gap-1.5 text-[12px] text-success"><CheckCircle2 size={12} /> Ready to generate.</p>
              )}
            </>
          ) : (
            <p className="flex items-center gap-1.5 text-[13px] text-warning">
              <AlertTriangle size={13} /> No Published/Active template found for {jurisdictionCountry} · {selectedYear} · {selectedReportType}.
            </p>
          )}
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleGenerate} disabled={!canGenerate || generating}
          className="flex items-center gap-1.5 rounded-[12px] bg-primary text-white px-4 py-2.5 text-[13px] font-bold hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {generating ? <><Loader2 size={13} className="animate-spin" /> Generating…</> : "Generate Report"}
        </button>
      </div>
    </div>
  );
}
