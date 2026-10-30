import { useState, useEffect, useCallback } from "react";
import { X, ChevronDown, Loader2, RotateCcw, ListTree, Sparkles } from "lucide-react";
import { getRunById, getRunItems, getRunLeaveSummary, recalculateEmployeePayslip } from "../../../service/payrollService";
import { useToast } from "../ToastContext";
import { getPayrollLabels, getIncomeTaxLines } from "../../../utils/jurisdictionLabels";
import { formatCurrency, createCurrencyFormatterForCode, getCountryNameFromCode, getCurrencyForJurisdiction } from "../../../utils/currency";
import CountryTotalsTable from "../../../components/payroll/CountryTotalsTable";
import RunStatusTimeline from "./RunStatusTimeline";
import AssistInlinePanel from "../../assist/AssistInlinePanel";
import SGRunPreflightPanel from "./SGRunPreflightPanel";
import HKRunPreflightPanel from "./HKRunPreflightPanel";
import NLRunPreflightPanel from "./NLRunPreflightPanel";
import NLPayslipBreakdown from "./NLPayslipBreakdown";
import HKCorrectionRequestPanel from "./HKCorrectionRequestPanel";
import StatutoryTraceDrawer from "../../../components/payroll/StatutoryTraceDrawer";
import MXRunPreflightPanel from "../../../components/jurisdiction/mexico/run/MXRunPreflightPanel";
import MXRunStatusBadges from "../../../components/jurisdiction/mexico/run/MXRunStatusBadges";
import MXRunCalculationTrace from "../../../components/jurisdiction/mexico/run/MXRunCalculationTrace";
import MXCfdiStagePanel from "../../../components/jurisdiction/mexico/run/MXCfdiStagePanel";
import MXCorrectionsPanel from "../../../components/jurisdiction/mexico/run/MXCorrectionsPanel";
import BRRunPreflightPanel from "./BRRunPreflightPanel";
import BRPayslipBreakdown from "./BRPayslipBreakdown";
import ZAPayslipBreakdown from "./ZAPayslipBreakdown";
import ZARunExceptionsPanel from "./ZARunExceptionsPanel";

const EDITABLE_STATUSES = ["Draft", "Review"];

// Columns of the per-country totals table shown for a run that pays
// employees in more than one country (detail.totalsByCountry).
const COUNTRY_TOTAL_COLUMNS = [
  { key: "employeeCount", label: "Employees" },
  { key: "totalGross", label: "Gross", money: true },
  { key: "totalDeductions", label: "Deductions", money: true, accent: "text-error" },
  { key: "totalEmployerContribution", label: "Employer Contributions", money: true, accent: "text-category-teal" },
  { key: "totalNet", label: "Net", money: true, accent: "text-primary" },
];

function fmtCurrencyLocal(n, fmtCurrency) {
  if (fmtCurrency) return fmtCurrency(n);
  if (n == null) return "—";
  return formatCurrency(n);
}

function maskAccount(acc) {
  if (!acc) return "—";
  const s = String(acc);
  if (s.length <= 4) return s;
  return "X".repeat(s.length - 4) + s.slice(-4);
}

function fmtDate(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return String(v);
  }
}

function StatusBadge({ status }) {
  const map = {
    Draft: "bg-info/10 text-info",
    Review: "bg-warning/10 text-warning",
    Approved: "bg-primary/10 text-primary",
    Authorized: "bg-primary/10 text-primary",
    Paid: "bg-primary/10 text-primary",
    Closed: "bg-foreground-muted/10 text-foreground-muted",
    Pending: "bg-warning/10 text-warning",
    Failed: "bg-error/10 text-error",
    // Phase 8BU: some components genuinely calculated, at least one other
    // (typically wage tax) genuinely unavailable — distinct from both a
    // normal Pending payslip and a fully Failed/blocked one.
    Partial: "bg-warning/10 text-warning",
  };
  const cls = map[status] || "bg-foreground-muted/10 text-foreground-muted";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ${cls}`}>
      {status || "—"}
    </span>
  );
}

function InfoField({ label, children }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted mb-1">{label}</p>
      <div className="text-[13px] font-semibold text-foreground">{children ?? "—"}</div>
    </div>
  );
}

const BREAKDOWN_COLUMNS = [
  { key: "employee", label: "Employee" },
  { key: "employeeId", label: "Employee ID" },
  { key: "department", label: "Department" },
  { key: "designation", label: "Designation" },
  { key: "attendance", label: "Attendance Summary" },
  { key: "gross", label: "Gross Earnings" },
  { key: "deductions", label: "Total Deductions" },
  { key: "net", label: "Net Salary" },
  { key: "bankName", label: "Bank Name" },
  { key: "account", label: "Account No." },
  // Phase 8BS: was two columns ("Payment Status"/"Payslip Status") both
  // rendering the exact same <StatusBadge status={item.status} /> — a
  // single PayslipStatus enum (Pending/Paid/Failed) has no second,
  // genuinely distinct status dimension to show, so this was pure
  // redundancy, not two different things. Collapsed to one; the actual
  // block reason (for a Failed row) is now populated into `item.notes`
  // by the backend (service.py's GermanyCalculationBlockedException
  // handler) and shown in the Remarks column below.
  { key: "payslipStatus", label: "Status" },
  { key: "remarks", label: "Remarks" },
];

function EarningsDeductionsBlock({ item, fmtCurrency }) {
  const labels = getPayrollLabels(item.country);

  const earnings = [
    ["Basic Salary", item.basicPay],
    ["House Rent Allowance", item.hra],
    ...(item.allowanceItems || []).map((a) => [a.label, a.amount]),
    ["Special Allowance", item.specialAllowance],
    ["Overtime", item.overtime],
    ["Additional Compensation", item.additionalCompensation],
  ].filter(([, v]) => Number(v) > 0);

  const deductions = [
    ["LOP Deduction", item.attendanceDeduction],
    ...getIncomeTaxLines(item),
    // Germany: Kirchensteuer/Soli are real, persisted, API-serialized
    // figures (item.churchTax/item.soli — see _serialize_payslip) that
    // this run-detail breakdown never rendered, even though the on-screen
    // PayslipStub and payslip PDF both surface them.
    ...(labels.churchTax ? [[labels.churchTax, item.churchTax]] : []),
    ...(labels.solidaritySurcharge ? [[labels.solidaritySurcharge, item.soli]] : []),
    [labels.pf, item.pf],
    [labels.esi, item.esi],
    [labels.professionalTax, item.professionalTax],
    [labels.socialSecurity, item.socialSecurity],
    [labels.medicare, item.medicare],
    [labels.niEmployee, item.niEmployee],
    [labels.employeePension || "Workplace Pension", item.employeePension],
    ["Student Loan Deduction", item.studyLoanDeduction],
    // UK: was reaching the API response (once the schema fix landed) but
    // still had no row here — found 2026-09-09 gap-closure Phase 3.
    ["Postgraduate Loan Deduction", item.postgradLoanDeduction],
    // US: State Disability Insurance / other state payroll-program employee
    // deductions (CA SDI, NY/NJ/RI TDI, CT/MA/WA/CO/OR/etc. paid-leave
    // employee share) — computed and persisted but never shown here until
    // the 2026-09-15 Org Admin visibility audit.
    ["State Disability Insurance", item.stateDisabilityInsurance],
    ["State Payroll Programs (e.g. Paid Leave/TDI)", item.stateProgramDeductions],
  ].filter(([, v]) => Number(v) > 0);

  const employerContributions = [
    [labels.employerPf, item.employerPf],
    [labels.employerEsi, item.employerEsi],
    [labels.employerSocialSecurity, item.employerSs],
    ["Employer Medicare", item.employerMedicare],
    [labels.employerPension, item.employerPension],
    [labels.employerOccupationalHazard, item.employerOccupationalHazard],
    ["Employer National Insurance", item.employerNi],
    // Employer-only payroll levies on employer_payroll_tax (AU state payroll
    // tax, South Africa SDL) — serialized as employerPayrollTax but never
    // listed here before; never an employee deduction.
    [labels.employerPayrollTax, item.employerPayrollTax],
    // UK: Apprenticeship Levy — computed since the 2026-09-08 commit but
    // silently discarded before ever reaching a persisted PayslipItem;
    // now actually persisted+serialized (Phase 3), shown here as an
    // employer-only charge, consistent with Employer National Insurance
    // above.
    ["Apprenticeship Levy", item.employerApprenticeshipLevy],
    // US: FUTA / SUI / state payroll-program employer contributions —
    // computed and persisted but never reached this list (or any payslip
    // API response at all) until the 2026-09-15 Org Admin visibility audit.
    ["FUTA (Employer)", item.employerFuta],
    ["SUI (Employer)", item.employerSui],
    ["State Payroll Programs (Employer)", item.employerStateProgramContributions],
  ].filter(([, v]) => Number(v) > 0);
  const employerContributionsTotal = employerContributions.reduce((sum, [, v]) => sum + (Number(v) || 0), 0);
  const employerTotalCost = (Number(item.salary) || 0) + employerContributionsTotal;
  // Mexico: the employer cost lives in the frozen Mexican result (IMSS,
  // INFONAVIT, state ISN) — never shown as an understated shared total.
  const isMx = (item.country || item.countryCode) === "MX";
  // Phase 8BV: previously only discoverable via a truncated free-text
  // Remarks cell (item.notes) — the structured list the backend already
  // serializes (germanyUnavailableComponents) is now shown as its own
  // first-class notice, matching the Germany Summary tab's own rendering.
  const unavailableComponents = item.germanyUnavailableComponents || [];

  return (
    <div>
      {unavailableComponents.length > 0 && (
        <div className="mb-3 rounded-md bg-warning/10 border border-warning/30 px-3 py-2 text-[12px] text-foreground">
          <span className="font-bold text-warning">Partially calculated —</span>{" "}
          unavailable: <span className="font-mono">{unavailableComponents.join(", ")}</span>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-primary mb-2">Earnings</p>
        {earnings.length === 0 ? (
          <p className="text-[12px] text-foreground-muted">No earnings line items.</p>
        ) : (
          <dl className="space-y-1.5">
            {earnings.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between text-[12px]">
                <dt className="text-foreground-muted">{label}</dt>
                <dd className="font-semibold text-foreground">{fmtCurrencyLocal(val, fmtCurrency)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-error mb-2">Deductions</p>
        {deductions.length === 0 ? (
          <p className="text-[12px] text-foreground-muted">No deductions.</p>
        ) : (
          <dl className="space-y-1.5">
            {deductions.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between text-[12px]">
                <dt className="text-foreground-muted">{label}</dt>
                <dd className="font-semibold text-foreground">{fmtCurrencyLocal(val, fmtCurrency)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-category-teal mb-2">Employer Contributions</p>
        {isMx ? (
          <p className="text-[12px] text-foreground-muted" data-testid="mx-employer-dash">
            — <span className="text-[11px]">(Mexican employer cost: see the Mexico trace below)</span>
          </p>
        ) : employerContributions.length === 0 ? (
          <p className="text-[12px] text-foreground-muted">No employer contributions.</p>
        ) : (
          <dl className="space-y-1.5">
            {employerContributions.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between text-[12px]">
                <dt className="text-foreground-muted">{label}</dt>
                <dd className="font-semibold text-foreground">{fmtCurrencyLocal(val, fmtCurrency)}</dd>
              </div>
            ))}
          </dl>
        )}
        {/* Employer total cost = gross + employer contributions — the
            reconciliation invariant this run detail never surfaced
            despite every underlying figure already being on-screen
            above. */}
        <div className="mt-2 flex items-center justify-between border-t border-border pt-1.5 text-[12px]">
          <dt className="font-bold text-foreground-muted">Employer Total Cost</dt>
          <dd className="font-bold text-category-teal">{isMx ? "—" : fmtCurrencyLocal(employerTotalCost, fmtCurrency)}</dd>
        </div>
      </div>
      </div>
    </div>
  );
}

function AttendanceLeaveBlock({ item, leave }) {
  const leaveRows = [
    ["Present", leave?.present],
    ["Absent", leave?.absent],
    ["Paid Leave", leave?.paidLeave],
    ["Unpaid Leave", leave?.unpaidLeave],
    ["Sick Leave", leave?.sickLeave],
    ["Casual Leave", leave?.casualLeave],
  ];
  return (
    <div className="mt-4 border-t border-border pt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-info mb-2">Attendance</p>
        <dl className="space-y-1.5 text-[12px]">
          <div className="flex items-center justify-between">
            <dt className="text-foreground-muted">Payable Days</dt>
            <dd className="font-semibold text-foreground">{item.payableDays ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-foreground-muted">Total Working Days</dt>
            <dd className="font-semibold text-foreground">{item.totalWorkingDays ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-foreground-muted">Unpaid Leave Days</dt>
            <dd className="font-semibold text-foreground">{item.unpaidLeaveDays ?? 0}</dd>
          </div>
        </dl>
      </div>
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-warning mb-2">Leave Summary</p>
        {leave ? (
          <dl className="space-y-1.5 text-[12px]">
            {leaveRows.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between">
                <dt className="text-foreground-muted">{label}</dt>
                <dd className="font-semibold text-foreground">{val ?? 0} day{val === 1 ? "" : "s"}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-[12px] text-foreground-muted">No attendance records for this period.</p>
        )}
      </div>
    </div>
  );
}

function EmployeeRow({ item, leave, fmtCurrency: orgFmtCurrency, currencyByCountry, runId, runStatus, onRecalculated }) {
  const [open, setOpen] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const { addToast } = useToast();
  const canRecalculate = EDITABLE_STATUSES.includes(runStatus);
  // Switzerland: the engine's own statutory lines, frozen on the payslip
  const chSnapshot = (item.country || item.countryCode) === "CH" ? item.chCalculationSnapshot : null;
  // Netherlands: employee pay and employer cost from the frozen snapshot (NL-048)
  const nlSnapshot = (item.country || item.countryCode) === "NL" ? item.nlCalculationSnapshot : null;
  // Mexico: the frozen engine result + input hashes (MX-063 trace)
  const mxSnapshot = (item.country || item.countryCode) === "MX" ? item.mxCalculationSnapshot : null;
  // Each payslip is paid in its own country's currency (from the run's
  // totalsByCountry); the org-currency formatter is only the fallback.
  const rowCurrency = currencyByCountry?.[String(item.country || item.countryCode || "").toUpperCase()];
  const fmtCurrency = rowCurrency ? createCurrencyFormatterForCode(rowCurrency) : orgFmtCurrency;

  async function handleRecalculate(e) {
    e.stopPropagation();
    setRecalculating(true);
    try {
      await recalculateEmployeePayslip(runId, item.employeeId);
      addToast?.(`Recalculated payslip for ${item.employee}.`, "success");
      await onRecalculated?.();
    } catch (err) {
      addToast?.(err.message || "Failed to recalculate payslip.", "error");
    } finally {
      setRecalculating(false);
    }
  }

  return (
    <>
      <tr
        onClick={() => setOpen((o) => !o)}
        className="cursor-pointer transition-colors hover:bg-background dark:hover:bg-surface-muted"
      >
        <td className="px-3 py-3 text-xs font-semibold text-foreground whitespace-nowrap">
          <span className="inline-flex items-center gap-1.5">
            <ChevronDown size={13} className={`text-foreground-muted transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
            {item.employee}
          </span>
        </td>
        <td className="px-3 py-3 text-xs text-foreground-muted whitespace-nowrap">{item.employeeId}</td>
        <td className="px-3 py-3 text-xs text-foreground-muted whitespace-nowrap">{item.department || "—"}</td>
        <td className="px-3 py-3 text-xs text-foreground-muted whitespace-nowrap">{item.designation || "—"}</td>
        <td className="px-3 py-3 text-xs text-foreground-muted whitespace-nowrap">
          {item.payableDays != null && item.totalWorkingDays != null
            ? `${item.payableDays}/${item.totalWorkingDays} days`
            : "—"}
        </td>
        <td className="px-3 py-3 text-xs font-semibold text-foreground text-right whitespace-nowrap">
          {fmtCurrencyLocal(item.salary, fmtCurrency)}
        </td>
        <td className="px-3 py-3 text-xs font-semibold text-error text-right whitespace-nowrap">
          {fmtCurrencyLocal(item.totalDeductions, fmtCurrency)}
        </td>
        <td className="px-3 py-3 text-xs font-bold text-primary text-right whitespace-nowrap">
          {fmtCurrencyLocal(item.netPay, fmtCurrency)}
        </td>
        <td className="px-3 py-3 text-xs text-foreground-muted whitespace-nowrap">{item.bankName || "—"}</td>
        <td className="px-3 py-3 text-xs text-foreground-muted whitespace-nowrap">{maskAccount(item.bankAccount)}</td>
        <td className="px-3 py-3 whitespace-nowrap"><StatusBadge status={item.status} /></td>
        <td className="px-3 py-3 text-xs text-foreground-muted max-w-[220px] truncate" title={item.notes || ""}>{item.notes || "—"}</td>
      </tr>
      {open && (
        <tr className="bg-background">
          <td colSpan={BREAKDOWN_COLUMNS.length} className="px-5 py-4">
            <div className="flex items-center justify-end gap-2 mb-3">
              {chSnapshot?.trace && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setTraceOpen(true); }}
                  className="flex items-center gap-1.5 text-[12px] font-semibold px-3 py-1.5 rounded-[10px] border border-border text-foreground transition-all duration-200 hover:border-primary hover:text-primary"
                >
                  <ListTree size={13} />
                  Statutory trace
                </button>
              )}
              <button
                type="button"
                onClick={handleRecalculate}
                disabled={!canRecalculate || recalculating}
                title={canRecalculate ? "Recalculate this employee's payslip using their current data" : "Only Draft/Review runs can be recalculated"}
                className="flex items-center gap-1.5 text-[12px] font-semibold px-3 py-1.5 rounded-[10px] border border-border text-foreground transition-all duration-200 hover:border-primary hover:text-primary disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <RotateCcw size={13} className={recalculating ? "animate-spin" : ""} />
                {recalculating ? "Recalculating…" : "Recalculate payslip"}
              </button>
            </div>
            {nlSnapshot && <NLPayslipBreakdown snapshot={nlSnapshot} employeeName={item.employee} />}
            {mxSnapshot && <MXRunCalculationTrace snapshot={mxSnapshot} />}
            {(item.country || item.countryCode) === "BR" && item.brCalculationSnapshot && <BRPayslipBreakdown snapshot={item.brCalculationSnapshot} employeeName={item.employee} />}
            {(item.country || item.countryCode) === "ZA" && item.zaCalculationSnapshot && <ZAPayslipBreakdown snapshot={item.zaCalculationSnapshot} employeeName={item.employee} />}
            <EarningsDeductionsBlock item={item} fmtCurrency={fmtCurrency} />
            <AttendanceLeaveBlock item={item} leave={leave} />
            <StatutoryTraceDrawer open={traceOpen} onClose={() => setTraceOpen(false)} snapshot={chSnapshot}
              title={`Statutory trace — ${item.employee}`} subtitle="Switzerland · as frozen on this payslip" currency="CHF" />
          </td>
        </tr>
      )}
    </>
  );
}

export default function RunDetailPanel({ run, onClose, fmtCurrency }) {
  const [detail, setDetail] = useState(null);
  const [items, setItems] = useState([]);
  const [leaveSummary, setLeaveSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [showAssist, setShowAssist] = useState(false);

  const totalGross = detail?.gross ?? detail?.totalGross ?? run?.gross ?? items.reduce((s, i) => s + (Number(i.salary) || 0), 0);
  const totalDeductions = detail?.deductions ?? detail?.totalDeductions ?? run?.deductions ?? items.reduce((s, i) => s + (Number(i.totalDeductions) || 0), 0);
  const totalNet = detail?.net ?? detail?.totalNet ?? run?.net ?? items.reduce((s, i) => s + (Number(i.netPay) || 0), 0);
  const totalEmployees = detail?.employees ?? run?.employees ?? items.length;

  const load = useCallback(async () => {
    if (!run?.id) return;
    setLoading(true);
    try {
      const [runDetail, runItems, leave] = await Promise.all([
        getRunById(run.id),
        getRunItems(run.id),
        getRunLeaveSummary(run.id),
      ]);
      setDetail(runDetail);
      setItems(runItems);
      setLeaveSummary(leave || {});
    } finally {
      setLoading(false);
    }
  }, [run?.id]);

  useEffect(() => {
    load();
  }, [load]);

  const totalsByCountry = detail?.totalsByCountry || [];
  const isMultiCountry = totalsByCountry.length > 1;
  const currencyByCountry = Object.fromEntries(
    totalsByCountry.filter((r) => r.country && r.currency).map((r) => [String(r.country).toUpperCase(), r.currency]),
  );
  const showBlockedColumn = totalsByCountry.some((r) => Number(r.blockedCount) > 0);
  const itemsByCountry = items.reduce((groups, item) => {
    const country = String(item.country || item.countryCode || "Other").toUpperCase();
    if (!groups.has(country)) groups.set(country, []);
    groups.get(country).push(item);
    return groups;
  }, new Map());

  if (!run) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-2 sm:p-4 md:p-6 bg-slate-950/60" onClick={onClose}>
      <div
        className="flex h-full max-h-[96vh] w-full max-w-[96vw] xl:max-w-7xl 2xl:max-w-[1560px] flex-col rounded-2xl bg-surface border border-border shadow-[0_24px_60px_rgba(0,0,0,0.25)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-foreground">
                  Payroll Run &middot; {detail?.period || run.period}
                </h2>
                <StatusBadge status={detail?.status || run.status} />
              </div>
              <p className="text-xs text-foreground-muted mt-0.5">Run details and employee-level breakdown</p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => setShowAssist((prev) => !prev)}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition-all duration-200 ${
                showAssist
                  ? "border-primary bg-primary text-white shadow-sm"
                  : "border-primary/20 bg-primary/5 hover:bg-primary/10 text-primary"
              }`}
              aria-expanded={showAssist}
              aria-label={showAssist ? "Close AI Assist panel" : "Ask AI Assist about this run"}
            >
              <Sparkles size={14} />
              <span>{showAssist ? "Close Assist" : "Ask Assist"}</span>
            </button>
            <button
              onClick={onClose}
              aria-label="Close panel"
              className="border border-border bg-surface-muted rounded-[12px] p-2 text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 size={22} className="animate-spin text-primary" />
            </div>
          ) : (
            <>
              <RunStatusTimeline run={detail || run} />

              {detail?.attendanceOverrideReason && (
                <div className="rounded-[14px] border border-warning/30 bg-warning/10 px-4 py-3 mb-5 text-[13px] text-foreground">
                  <strong>Run with incomplete attendance (admin override).</strong> Employees without attendance were paid as present for those days.
                  <span className="block text-foreground-muted mt-1">
                    Reason: {detail.attendanceOverrideReason}
                    {detail.attendanceOverrideAt && ` · ${fmtDate(detail.attendanceOverrideAt)}`}
                  </span>
                </div>
              )}

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
                <div className="rounded-[14px] border border-border bg-surface-muted/60 p-4 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Total Employees</p>
                  <p className="mt-1 text-2xl font-extrabold text-foreground">{totalEmployees}</p>
                </div>
                <div className="rounded-[14px] border border-border bg-surface-muted/60 p-4 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Total Gross Earnings</p>
                  <p className="mt-1 text-2xl font-extrabold text-foreground">{fmtCurrencyLocal(totalGross, fmtCurrency)}</p>
                </div>
                <div className="rounded-[14px] border border-border bg-surface-muted/60 p-4 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Total Deductions</p>
                  <p className="mt-1 text-2xl font-extrabold text-error">{fmtCurrencyLocal(totalDeductions, fmtCurrency)}</p>
                </div>
                <div className="rounded-[14px] border border-border bg-surface-muted/60 p-4 shadow-[0_1px_3px_rgba(0,0,0,0.03)]">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Total Net Salary</p>
                  <p className="mt-1 text-2xl font-extrabold text-primary">{fmtCurrencyLocal(totalNet, fmtCurrency)}</p>
                </div>
              </div>

              <div className="bg-surface-muted rounded-[18px] p-5 mb-5">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-4">Run Information</h4>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-4">
                  <InfoField label="Payroll Period">{detail?.period || run.period}</InfoField>
                  <InfoField label="Payroll Status"><StatusBadge status={detail?.status || run.status} /></InfoField>
                  <InfoField label="Approval Status">
                    <span className={detail?.approvalStatus === "Approved" ? "text-primary" : "text-warning"}>
                      {detail?.approvalStatus || "Pending"}
                    </span>
                  </InfoField>
                  <InfoField label="Created By">{detail?.createdBy || "—"}</InfoField>
                  <InfoField label="Approved By">{detail?.approvedBy || "—"}</InfoField>
                  <InfoField label="Created Date">{fmtDate(detail?.createdAt)}</InfoField>
                  <InfoField label="Processed Date">{fmtDate(detail?.processedAt)}</InfoField>
                  <InfoField label="Employees">{detail?.employees ?? items.length}</InfoField>
                </div>
              </div>

              {/* Mixed-country run: the run's own gross/net are a raw sum
                  across currencies, so totals are shown per country only. */}
              {isMultiCountry && (
                <div className="mb-5">
                  <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1">Totals by Country</h4>
                  <p className="text-[12px] text-foreground-muted mb-3">
                    This run pays employees in {totalsByCountry.length} countries — each total is in that country&apos;s own currency and they are not added together.
                  </p>
                  <CountryTotalsTable
                    rows={totalsByCountry}
                    columns={showBlockedColumn
                      ? [...COUNTRY_TOTAL_COLUMNS.slice(0, 1), { key: "blockedCount", label: "Blocked", accent: "text-error" }, ...COUNTRY_TOTAL_COLUMNS.slice(1)]
                      : COUNTRY_TOTAL_COLUMNS}
                  />
                </div>
              )}

              {showAssist && (
                <div className="mb-6 rounded-[18px] border border-primary/20 bg-surface shadow-md overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-2.5 bg-primary/5 border-b border-primary/10">
                    <div className="flex items-center gap-2 text-xs font-semibold text-primary">
                      <Sparkles size={14} />
                      <span>Assist AI &middot; Run Insights</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowAssist(false)}
                      className="inline-flex items-center gap-1 text-xs text-foreground-muted hover:text-foreground px-2 py-1 rounded-lg hover:bg-surface-muted transition-colors"
                    >
                      <X size={14} />
                      <span>Close</span>
                    </button>
                  </div>
                  <AssistInlinePanel
                    contextObject={{ type: "PAYROLL_RUN", id: run.id }}
                    title="Ask Assist about this run"
                    subtitle={`Ask about readiness, exceptions, or status for ${detail?.period || run.period} — answered using only this run's own data.`}
                  />
                </div>
              )}

              {items.some((i) => (i.country || i.countryCode) === "SG") && <SGRunPreflightPanel runId={run.id} />}
              {items.some((i) => (i.country || i.countryCode) === "HK") && <HKRunPreflightPanel runId={run.id} />}
              {items.some((i) => (i.country || i.countryCode) === "NL") && <NLRunPreflightPanel runId={run.id} />}
              {items.some((i) => (i.country || i.countryCode) === "MX") && (
                <>
                  <MXRunStatusBadges runId={run.id} refreshKey={(detail || run).status} />
                  <MXRunPreflightPanel runId={run.id} runStatus={(detail || run).status} onChanged={load} />
                  <MXCfdiStagePanel runId={run.id} />
                  <MXCorrectionsPanel runId={run.id} items={items} />
                </>
              )}
              {items.some((i) => (i.country || i.countryCode) === "BR") && <BRRunPreflightPanel runId={run.id} />}
              {items.some((i) => (i.country || i.countryCode) === "ZA") && (
                <ZARunExceptionsPanel runId={run.id} runStatus={(detail || run).status} items={items} />
              )}
              <HKCorrectionRequestPanel run={detail || run} items={items} />

              <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">
                Employee Payroll Details
              </h4>
              {items.length === 0 ? (
                <div className="rounded-[14px] border border-border px-5 py-10 text-center text-[13px] text-foreground-muted">
                  No employee payslips in this run yet.
                </div>
              ) : (
                <div className="space-y-5">
                  {[...itemsByCountry.entries()].map(([country, countryItems]) => {
                    const countryName = getCountryNameFromCode(country) || country;
                    const currency = currencyByCountry[country] || getCurrencyForJurisdiction(country)?.code;
                    const countryFormatter = currency ? createCurrencyFormatterForCode(currency) : fmtCurrency;

                    return (
                      <section key={country} className="overflow-hidden rounded-[16px] border border-border">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-muted px-4 py-3">
                          <div>
                            <h5 className="text-sm font-bold text-foreground">{countryName}</h5>
                            <p className="text-[11px] text-foreground-muted">
                              {countryItems.length} {countryItems.length === 1 ? "employee" : "employees"}
                              {currency ? ` · ${currency}` : ""}
                            </p>
                          </div>
                          <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-primary">
                            Country payroll
                          </span>
                        </div>
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="bg-surface-muted/60 border-b border-border">
                                {BREAKDOWN_COLUMNS.map((col) => (
                                  <th
                                    key={col.key}
                                    className={`px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-foreground-muted whitespace-nowrap ${
                                      ["gross", "deductions", "net"].includes(col.key) ? "text-right" : "text-left"
                                    }`}
                                  >
                                    {col.label}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-border/50">
                              {countryItems.map((item) => (
                                <EmployeeRow
                                  key={item.id}
                                  item={item}
                                  leave={leaveSummary?.[item.employeeId]}
                                  fmtCurrency={countryFormatter}
                                  currencyByCountry={currencyByCountry}
                                  runId={run.id}
                                  runStatus={detail?.status || run.status}
                                  onRecalculated={load}
                                />
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </section>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
