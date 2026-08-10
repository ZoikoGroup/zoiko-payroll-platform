import { useState, useEffect, useCallback } from "react";
import { X, ChevronDown, Loader2, RotateCcw } from "lucide-react";
import { getRunById, getRunItems, getRunLeaveSummary, recalculateEmployeePayslip } from "../../../service/payrollService";
import { useToast } from "../ToastContext";
import { getPayrollLabels } from "../../../utils/jurisdictionLabels";
import { formatCurrency } from "../../../utils/currency";
import RunStatusTimeline from "./RunStatusTimeline";

const EDITABLE_STATUSES = ["Draft", "Review"];

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
    Draft: "bg-[#35B6F5]/10 text-[#35B6F5]",
    Review: "bg-[#F8A60A]/10 text-[#F8A60A]",
    Approved: "bg-[#19C58A]/10 text-[#19C58A]",
    Authorized: "bg-[#19C58A]/10 text-[#19C58A]",
    Paid: "bg-[#19C58A]/10 text-[#19C58A]",
    Closed: "bg-[#9E9690]/10 text-[#9E9690]",
    Pending: "bg-[#F8A60A]/10 text-[#F8A60A]",
  };
  const cls = map[status] || "bg-[#9E9690]/10 text-[#9E9690]";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ${cls}`}>
      {status || "—"}
    </span>
  );
}

function InfoField({ label, children }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-widest text-[#9E9690] mb-1">{label}</p>
      <div className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{children ?? "—"}</div>
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
  { key: "paymentStatus", label: "Payment Status" },
  { key: "payslipStatus", label: "Payslip Status" },
  { key: "remarks", label: "Remarks" },
];

function EarningsDeductionsBlock({ item, fmtCurrency }) {
  const labels = getPayrollLabels(item.country);

  const earnings = [
    ["Basic Salary", item.basicPay],
    ["House Rent Allowance", item.hra],
    ["Special Allowance", item.specialAllowance],
    ["Overtime", item.overtime],
    ["Additional Compensation", item.additionalCompensation],
  ].filter(([, v]) => Number(v) > 0);

  const deductions = [
    ["LOP Deduction", item.attendanceDeduction],
    [labels.incomeTax, item.tds],
    [labels.pf, item.pf],
    [labels.esi, item.esi],
    ["Professional Tax", item.professionalTax],
    [labels.socialSecurity, item.socialSecurity],
    [labels.medicare, item.medicare],
    ["National Insurance", item.niEmployee],
  ].filter(([, v]) => Number(v) > 0);

  const employerContributions = [
    [labels.employerPf, item.employerPf],
    [labels.employerEsi, item.employerEsi],
    [labels.employerSocialSecurity, item.employerSs],
    ["Employer Medicare", item.employerMedicare],
    [labels.employerPension, item.employerPension],
  ].filter(([, v]) => Number(v) > 0);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-[#19C58A] mb-2">Earnings</p>
        {earnings.length === 0 ? (
          <p className="text-[12px] text-[#9E9690]">No earnings line items.</p>
        ) : (
          <dl className="space-y-1.5">
            {earnings.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between text-[12px]">
                <dt className="text-[#6B6560] dark:text-[#A69B93]">{label}</dt>
                <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{fmtCurrencyLocal(val, fmtCurrency)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-[#FF6E86] mb-2">Deductions</p>
        {deductions.length === 0 ? (
          <p className="text-[12px] text-[#9E9690]">No deductions.</p>
        ) : (
          <dl className="space-y-1.5">
            {deductions.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between text-[12px]">
                <dt className="text-[#6B6560] dark:text-[#A69B93]">{label}</dt>
                <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{fmtCurrencyLocal(val, fmtCurrency)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-[#9D7BF2] mb-2">Employer Contributions</p>
        {employerContributions.length === 0 ? (
          <p className="text-[12px] text-[#9E9690]">No employer contributions.</p>
        ) : (
          <dl className="space-y-1.5">
            {employerContributions.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between text-[12px]">
                <dt className="text-[#6B6560] dark:text-[#A69B93]">{label}</dt>
                <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{fmtCurrencyLocal(val, fmtCurrency)}</dd>
              </div>
            ))}
          </dl>
        )}
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
    <div className="mt-4 border-t border-[#E5E0D9] dark:border-[#38312D] pt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-[#35B6F5] mb-2">Attendance</p>
        <dl className="space-y-1.5 text-[12px]">
          <div className="flex items-center justify-between">
            <dt className="text-[#6B6560] dark:text-[#A69B93]">Payable Days</dt>
            <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{item.payableDays ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-[#6B6560] dark:text-[#A69B93]">Total Working Days</dt>
            <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{item.totalWorkingDays ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-[#6B6560] dark:text-[#A69B93]">Unpaid Leave Days</dt>
            <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{item.unpaidLeaveDays ?? 0}</dd>
          </div>
        </dl>
      </div>
      <div>
        <p className="text-[11px] font-bold uppercase tracking-widest text-[#F8A60A] mb-2">Leave Summary</p>
        {leave ? (
          <dl className="space-y-1.5 text-[12px]">
            {leaveRows.map(([label, val]) => (
              <div key={label} className="flex items-center justify-between">
                <dt className="text-[#6B6560] dark:text-[#A69B93]">{label}</dt>
                <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{val ?? 0} day{val === 1 ? "" : "s"}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-[12px] text-[#9E9690]">No attendance records for this period.</p>
        )}
      </div>
    </div>
  );
}

function EmployeeRow({ item, leave, fmtCurrency, runId, runStatus, onRecalculated }) {
  const [open, setOpen] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const { addToast } = useToast();
  const canRecalculate = EDITABLE_STATUSES.includes(runStatus);

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
        className="cursor-pointer transition-colors hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520]"
      >
        <td className="px-3 py-3 text-xs font-semibold text-[#1A1816] dark:text-[#F0EDE8] whitespace-nowrap">
          <span className="inline-flex items-center gap-1.5">
            <ChevronDown size={13} className={`text-[#9E9690] transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
            {item.employee}
          </span>
        </td>
        <td className="px-3 py-3 text-xs text-[#6B6560] dark:text-[#A69B93] whitespace-nowrap">{item.employeeId}</td>
        <td className="px-3 py-3 text-xs text-[#6B6560] dark:text-[#A69B93] whitespace-nowrap">{item.department || "—"}</td>
        <td className="px-3 py-3 text-xs text-[#6B6560] dark:text-[#A69B93] whitespace-nowrap">{item.designation || "—"}</td>
        <td className="px-3 py-3 text-xs text-[#6B6560] dark:text-[#A69B93] whitespace-nowrap">
          {item.payableDays != null && item.totalWorkingDays != null
            ? `${item.payableDays}/${item.totalWorkingDays} days`
            : "—"}
        </td>
        <td className="px-3 py-3 text-xs font-semibold text-[#1A1816] dark:text-[#F0EDE8] text-right whitespace-nowrap">
          {fmtCurrencyLocal(item.salary, fmtCurrency)}
        </td>
        <td className="px-3 py-3 text-xs font-semibold text-[#FF6E86] text-right whitespace-nowrap">
          {fmtCurrencyLocal(item.totalDeductions, fmtCurrency)}
        </td>
        <td className="px-3 py-3 text-xs font-bold text-[#19C58A] text-right whitespace-nowrap">
          {fmtCurrencyLocal(item.netPay, fmtCurrency)}
        </td>
        <td className="px-3 py-3 text-xs text-[#6B6560] dark:text-[#A69B93] whitespace-nowrap">{item.bankName || "—"}</td>
        <td className="px-3 py-3 text-xs text-[#6B6560] dark:text-[#A69B93] whitespace-nowrap">{maskAccount(item.bankAccount)}</td>
        <td className="px-3 py-3 whitespace-nowrap"><StatusBadge status={item.status} /></td>
        <td className="px-3 py-3 whitespace-nowrap"><StatusBadge status={item.status} /></td>
        <td className="px-3 py-3 text-xs text-[#9E9690] max-w-[160px] truncate">{item.notes || "—"}</td>
      </tr>
      {open && (
        <tr className="bg-[#F8F7F4] dark:bg-[#1A1816]">
          <td colSpan={BREAKDOWN_COLUMNS.length} className="px-5 py-4">
            <div className="flex items-center justify-end mb-3">
              <button
                type="button"
                onClick={handleRecalculate}
                disabled={!canRecalculate || recalculating}
                title={canRecalculate ? "Recalculate this employee's payslip using their current data" : "Only Draft/Review runs can be recalculated"}
                className="flex items-center gap-1.5 text-[12px] font-semibold px-3 py-1.5 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] text-[#1A1816] dark:text-[#F0EDE8] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <RotateCcw size={13} className={recalculating ? "animate-spin" : ""} />
                {recalculating ? "Recalculating…" : "Recalculate payslip"}
              </button>
            </div>
            <EarningsDeductionsBlock item={item} fmtCurrency={fmtCurrency} />
            <AttendanceLeaveBlock item={item} leave={leave} />
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

  if (!run) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-[#1A1816]/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-5xl flex-col bg-white dark:bg-[#221D1A] border-l border-[#E5E0D9] dark:border-[#38312D] shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-[#E5E0D9] dark:border-[#38312D]">
          <div>
            <h2 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
              Payroll Run &middot; {detail?.period || run.period}
            </h2>
            <p className="text-[12px] text-[#9E9690] mt-0.5">Run details and employee-level breakdown</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] p-2 text-[#9E9690] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
          >
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 size={22} className="animate-spin text-[#19C58A]" />
            </div>
          ) : (
            <>
              <RunStatusTimeline run={detail || run} />

              <div className="bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[18px] p-5 mb-5">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-4">Run Information</h4>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <InfoField label="Payroll Period">{detail?.period || run.period}</InfoField>
                  <InfoField label="Payroll Status"><StatusBadge status={detail?.status || run.status} /></InfoField>
                  <InfoField label="Approval Status">
                    <span className={detail?.approvalStatus === "Approved" ? "text-[#19C58A]" : "text-[#F8A60A]"}>
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

              <h4 className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-3">
                Employee Payroll Details
              </h4>
              <div className="rounded-[14px] border border-[#E5E0D9] dark:border-[#38312D] overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-[#F8F7F4] dark:bg-[#2A2520] border-b border-[#E5E0D9] dark:border-[#38312D]">
                        {BREAKDOWN_COLUMNS.map((col) => (
                          <th
                            key={col.key}
                            className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690] whitespace-nowrap"
                          >
                            {col.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]/50">
                      {items.length === 0 ? (
                        <tr>
                          <td colSpan={BREAKDOWN_COLUMNS.length} className="px-5 py-10 text-center text-[13px] text-[#9E9690]">
                            No employee payslips in this run yet.
                          </td>
                        </tr>
                      ) : (
                        items.map((item) => (
                          <EmployeeRow
                            key={item.id}
                            item={item}
                            leave={leaveSummary?.[item.employeeId]}
                            fmtCurrency={fmtCurrency}
                            runId={run.id}
                            runStatus={detail?.status || run.status}
                            onRecalculated={load}
                          />
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
