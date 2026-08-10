import { useState } from "react";
import { Eye, CheckCircle2, Trash2, Loader2 } from "lucide-react";
import { approveRun, deletePayRun } from "../../../service/payrollService";
import ApprovalDialog from "./ApprovalDialog";
import { useToast } from "../ToastContext";
import { formatCurrency } from "../../../utils/currency";

// Mirrors backend PAYROLL_STATUS_ORDER (models.py) — a run can advance one
// step at a time all the way through Closed; only Closed itself is terminal.
const PAYROLL_STATUS_ORDER = ["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"];

function nextStatusLabel(status) {
  const idx = PAYROLL_STATUS_ORDER.indexOf(status);
  if (idx === -1 || idx >= PAYROLL_STATUS_ORDER.length - 1) return null;
  return PAYROLL_STATUS_ORDER[idx + 1];
}

function fmtCurrencyLocal(n, fmtCurrency) {
  if (fmtCurrency) return fmtCurrency(n);
  if (n == null) return "\u2014";
  return formatCurrency(n);
}

function getInitials(name) {
  if (!name) return "??";
  return name.split(" ").filter(Boolean).map((w) => w[0]).join("").toUpperCase().slice(0, 2);
}

const DEPT_COLORS = {
  Engineering: { bg: "bg-[#19C58A]/10", text: "text-[#19C58A]" },
  Marketing:   { bg: "bg-[#35B6F5]/10", text: "text-[#35B6F5]" },
  Sales:       { bg: "bg-[#F8A60A]/10", text: "text-[#F8A60A]" },
  Finance:     { bg: "bg-[#9D7BF2]/10", text: "text-[#9D7BF2]" },
  HR:          { bg: "bg-[#35B6F5]/10", text: "text-[#35B6F5]" },
  Operations:  { bg: "bg-[#F8A60A]/10", text: "text-[#F8A60A]" },
};

function Avatar({ name }) {
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#F8F7F4] dark:bg-[#2A2520] text-[10px] font-bold text-[#6B6560] dark:text-[#A69B93] flex-shrink-0">
      {getInitials(name)}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-16 text-center">
      <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-1">No payroll runs found</p>
      <p className="text-[13px] text-[#9E9690]">Create your first run to get started.</p>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    Draft:       "bg-[#35B6F5]/10 text-[#35B6F5]",
    Processing:  "bg-[#F8A60A]/10 text-[#F8A60A]",
    Review:      "bg-[#F8A60A]/10 text-[#F8A60A]",
    Approved:    "bg-[#19C58A]/10 text-[#19C58A]",
    Paid:        "bg-[#19C58A]/10 text-[#19C58A]",
    Rejected:    "bg-[#FF6E86]/10 text-[#FF6E86]",
    Failed:      "bg-[#FF6E86]/10 text-[#FF6E86]",
  };
  const cls = map[status] || "bg-[#35B6F5]/10 text-[#35B6F5]";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold ${cls}`}>
      {status}
    </span>
  );
}

function ConfirmDialog({ message, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-[#1A1816]/40 backdrop-blur-sm" onClick={onCancel}>
      <div className="bg-white dark:bg-[#221D1A] rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <p className="text-[14px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-4">{message}</p>
        <div className="flex justify-end gap-3">
          <button onClick={onCancel} className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] hover:bg-[#F0EDE8] dark:hover:bg-[#38312D] transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm} className="rounded-[10px] px-4 py-2 text-[13px] font-bold text-white bg-[#FF6E86] hover:bg-[#E5556E] transition-colors">
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export default function RunsTable({
  runs = [],
  employees = [],
  selectedEmployees = [],
  toggleEmployee,
  toggleAllEmployees,
  onSelect,
  onDelete,
  isWizardMode = false,
  fmtCurrency,
  calculationMode = "standard",
}) {
  const { addToast } = useToast();
  const [approvingId, setApprovingId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [approvalDialogRun, setApprovalDialogRun] = useState(null);

  if (!isWizardMode && runs.length === 0) return <EmptyState />;
  if (isWizardMode && employees.length === 0) return <EmptyState />;

  const allSelected =
    isWizardMode &&
    employees.length > 0 &&
    selectedEmployees.length === employees.length;

  const handleApprove = async (e, run) => {
    e.stopPropagation();
    if (approvingId) return;
    const runId = run.id;
    const landedOn = nextStatusLabel(run.status);
    setApprovingId(runId);
    try {
      await approveRun(runId);
      addToast?.(landedOn ? `Payroll run advanced to ${landedOn}.` : "Payroll run advanced.", "success");
      onDelete?.("approve-refresh");
    } catch {
      addToast?.("Failed to advance payroll run.", "error");
    } finally {
      setApprovingId(null);
    }
  };

  // The single "Approve" action advances a run through several lifecycle
  // steps (Draft→Review→Approved→Authorized→Paid→Closed). The three steps
  // that matter for tracking (landing on Approved/Authorized/Paid) get the
  // richer confirmation dialog (summary, and — only for Approved — the bank
  // transfer file); Draft→Review and Paid→Closed keep the direct-call
  // behavior since there's nothing to confirm/track there.
  const DIALOG_STATUSES = ["Review", "Approved", "Authorized"];
  const handleApproveClick = (e, run) => {
    e.stopPropagation();
    if (DIALOG_STATUSES.includes(run.status)) {
      setApprovalDialogRun(run);
      return;
    }
    handleApprove(e, run);
  };

  const handleDelete = async (runId) => {
    setConfirmDelete(null);
    setDeletingId(runId);
    try {
      await deletePayRun(runId);
      onDelete?.(runId);
    } catch {
      // handled by service toast
    } finally {
      setDeletingId(null);
    }
  };

  if (isWizardMode) {
    const isSimple = calculationMode === "simple";
    // All employees in a run share the same jurisdiction, so the first
    // employee's contribComponents (built country-aware in RunDetailPage)
    // defines the column set for every row — no hardcoded PF/ESI/PT here.
    const contributionColumns = employees[0]?.contribComponents || [];
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[#F8F7F4] dark:bg-[#2A2520] border-b border-[#E5E0D9] dark:border-[#38312D]">
              <th className="px-3 py-2.5 w-8">
                <input type="checkbox" checked={allSelected} onChange={toggleAllEmployees} className="rounded border-[#E5E0D9] dark:border-[#38312D] h-3.5 w-3.5 text-[#19C58A] focus:ring-[#19C58A]" />
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Employee</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Department</th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Payable Days</th>
              <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Gross Pay</th>
              {!isSimple && contributionColumns.map((col) => (
                <th key={col.id} className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">{col.label}</th>
              ))}
              {!isSimple && <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Tax</th>}
              <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">{isSimple ? "LOP Deduction" : "Extra / Benefits"}</th>
              <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Net Pay</th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]/50">
            {employees.map((emp) => {
              const dept = DEPT_COLORS[emp.department] || { bg: "bg-[#F8F7F4] dark:bg-[#2A2520]", text: "text-[#6B6560] dark:text-[#A69B93]" };
              const isSelected = selectedEmployees.includes(emp.id);
              const extraBenefits = emp.monthlyExtra ?? ((Number(emp.rewards) || 0) + (Number(emp.bonus) || 0) + (Number(emp.otherCompensation) || 0));
              const empContribs = Object.fromEntries(
                (emp.contribComponents || []).map((c) => [c.id, c.value])
              );
              return (
                <tr key={emp.id} className={`transition-colors ${isSelected ? "bg-[#19C58A]/5 dark:bg-[#19C58A]/10" : "hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520]"}`}>
                  <td className="px-3 py-2.5">
                    <input type="checkbox" checked={isSelected} onChange={() => toggleEmployee(emp.id)} className="rounded border-[#E5E0D9] dark:border-[#38312D] h-3.5 w-3.5 text-[#19C58A] focus:ring-[#19C58A]" />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <Avatar name={emp.name} />
                      <div className="flex flex-col">
                        <span className="font-semibold text-[#1A1816] dark:text-[#F0EDE8] text-xs whitespace-nowrap">{emp.name}</span>
                        {emp.attendanceStatus && emp.attendanceStatus !== "unknown" && (
                          <span className={`text-[9px] font-bold ${
                            emp.attendanceStatus === "present" ? "text-[#19C58A]" :
                            emp.attendanceStatus === "absent" ? "text-[#FF6E86]" :
                            emp.attendanceStatus === "leave" ? "text-[#F8A60A]" :
                            "text-[#9E9690]"
                          }`}>
                            {emp.attendanceStatus === "present" ? "\u25cf Present" :
                             emp.attendanceStatus === "absent" ? "\u25cf Absent" :
                             emp.attendanceStatus === "leave" ? "\u25cf On Leave" : ""}
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${dept.bg} ${dept.text}`}>
                      {emp.department || "\u2014"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-center whitespace-nowrap">
                    {emp.payableDays != null && emp.totalWorkingDays != null ? (
                      <span className={`text-xs font-semibold ${emp.prorated ? "text-amber-500" : "text-[#9E9690]"}`}>
                        {emp.payableDays}/{emp.totalWorkingDays}{emp.prorated ? " \u26a0" : ""}
                      </span>
                    ) : (
                      <span className="text-xs text-[#9E9690]">\u2014</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs font-semibold text-[#1A1816] dark:text-[#F0EDE8] whitespace-nowrap">
                    {fmtCurrencyLocal(emp.monthlyGross, fmtCurrency)}
                  </td>
                  {!isSimple && contributionColumns.map((col) => (
                    <td key={col.id} className="px-3 py-2.5 text-right text-xs font-semibold text-[#9D7BF2] whitespace-nowrap">
                      {fmtCurrencyLocal(empContribs[col.id] ?? 0, fmtCurrency)}
                    </td>
                  ))}
                  {!isSimple && (
                    <td className="px-3 py-2.5 text-right whitespace-nowrap">
                      <span className="text-xs font-semibold text-[#FF6E86]">{fmtCurrencyLocal(emp.monthlyTax, fmtCurrency)}</span>
                      {emp.taxSlabRate && emp.taxSlabRate !== "\u2014" && emp.taxSlabRate !== "Nil" && (
                        <span className={`ml-1 text-[9px] font-bold rounded px-1 py-px ${
                          emp.taxSlabRate.includes("87A rebate")
                            ? "text-[#19C58A] bg-[#19C58A]/10"
                            : "text-[#9E9690] bg-[#F8F7F4] dark:bg-[#2A2520]"
                        }`}>{emp.taxSlabRate}</span>
                      )}
                    </td>
                  )}
                  <td className="px-3 py-2.5 text-right text-xs font-semibold text-[#9D7BF2] whitespace-nowrap">
                    {isSimple
                      ? fmtCurrencyLocal((emp.monthlyGross || 0) - (emp.monthlyNet || 0), fmtCurrency)
                      : fmtCurrencyLocal(extraBenefits, fmtCurrency)
                    }
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs font-bold text-[#35B6F5] whitespace-nowrap">
                    {fmtCurrencyLocal(emp.monthlyNet, fmtCurrency)}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold bg-[#19C58A]/10 text-[#19C58A]">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#19C58A]" />
                      Ready
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  const listColumns = ["Period", "Employees", "Gross", "Deductions", "Net", "Status", "Submitted", "Actions"];

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[#F8F7F4] dark:bg-[#2A2520] border-b border-[#E5E0D9] dark:border-[#38312D]">
              {listColumns.map((col) => (
                <th key={col} className={`px-5 py-3.5 text-[10px] font-bold uppercase tracking-widest text-[#9E9690] ${col === "Gross" || col === "Deductions" || col === "Net" || col === "Submitted" ? "text-right" : col === "Actions" ? "text-center" : "text-left"}`}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8F7F4] dark:divide-[#38312D]/50">
            {runs.map((run) => (
              <tr key={run.id} className="cursor-pointer transition-colors hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520]" onClick={() => onSelect?.(run)}>
                <td className="px-5 py-4 text-xs font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{run.period}</td>
                <td className="px-5 py-4 text-xs text-[#6B6560] dark:text-[#A69B93]">{run.employees?.toLocaleString()}</td>
                <td className="px-5 py-4 text-xs font-semibold text-[#1A1816] dark:text-[#F0EDE8] text-right">{fmtCurrencyLocal(run.gross, fmtCurrency)}</td>
                <td className="px-5 py-4 text-xs font-semibold text-[#FF6E86] text-right">{run.deductions ? fmtCurrencyLocal(run.deductions, fmtCurrency) : "\u2014"}</td>
                <td className="px-5 py-4 text-xs font-bold text-[#19C58A] text-right">{fmtCurrencyLocal(run.net, fmtCurrency)}</td>
                <td className="px-5 py-4">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-5 py-4 text-xs text-[#9E9690] text-right">{run.payDate}</td>
                <td className="px-5 py-4">
                  <div className="flex items-center justify-center gap-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); onSelect?.(run); }}
                      title="View"
                      className="rounded-[8px] p-1.5 text-[#9E9690] hover:text-[#35B6F5] hover:bg-[#35B6F5]/10 transition-all duration-200"
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      onClick={(e) => handleApproveClick(e, run)}
                      title={nextStatusLabel(run.status) ? `Advance to ${nextStatusLabel(run.status)}` : "Already at final status"}
                      disabled={approvingId === run.id || !nextStatusLabel(run.status)}
                      className="rounded-[8px] p-1.5 text-[#9E9690] hover:text-[#19C58A] hover:bg-[#19C58A]/10 transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      {approvingId === run.id ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmDelete(run.id); }}
                      title="Delete"
                      disabled={deletingId === run.id}
                      className="rounded-[8px] p-1.5 text-[#9E9690] hover:text-[#FF6E86] hover:bg-[#FF6E86]/10 transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      {deletingId === run.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={listColumns.length} className="px-6 py-16 text-center text-[13px] text-[#9E9690]">No payroll runs found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {confirmDelete && (
        <ConfirmDialog
          message="Are you sure you want to delete this payroll run? This action cannot be undone."
          onConfirm={() => handleDelete(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
      {approvalDialogRun && (
        <ApprovalDialog
          run={approvalDialogRun}
          targetStatus={nextStatusLabel(approvalDialogRun.status)}
          fmtCurrency={fmtCurrency}
          onApproved={() => onDelete?.("approve-refresh")}
          onClose={() => setApprovalDialogRun(null)}
        />
      )}
    </>
  );
}
