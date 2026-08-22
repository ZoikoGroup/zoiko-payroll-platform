import { useState } from "react";
import { Eye, CheckCircle2, Trash2, Loader2 } from "lucide-react";
import { approveRun, deletePayRun } from "../../../service/payrollService";
import ApprovalDialog from "./ApprovalDialog";
import { useToast } from "../ToastContext";
import { formatCurrency } from "../../../utils/currency";
import { getPayrollLabels } from "../../../utils/jurisdictionLabels";

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
  Engineering: { bg: "bg-primary/10", text: "text-primary" },
  Marketing:   { bg: "bg-info/10", text: "text-info" },
  Sales:       { bg: "bg-warning/10", text: "text-warning" },
  Finance:     { bg: "bg-category-teal/10", text: "text-category-teal" },
  HR:          { bg: "bg-info/10", text: "text-info" },
  Operations:  { bg: "bg-warning/10", text: "text-warning" },
};

function Avatar({ name }) {
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-muted text-[10px] font-bold text-foreground-muted flex-shrink-0">
      {getInitials(name)}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-16 text-center">
      <p className="text-[15px] font-bold text-foreground mb-1">No payroll runs found</p>
      <p className="text-[13px] text-foreground-muted">Create your first run to get started.</p>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    Draft:       "bg-info/10 text-info",
    Processing:  "bg-warning/10 text-warning",
    Review:      "bg-warning/10 text-warning",
    Approved:    "bg-primary/10 text-primary",
    Paid:        "bg-primary/10 text-primary",
    Rejected:    "bg-error/10 text-error",
    Failed:      "bg-error/10 text-error",
  };
  const cls = map[status] || "bg-info/10 text-info";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold ${cls}`}>
      {status}
    </span>
  );
}

function ConfirmDialog({ message, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-background/40 backdrop-blur-sm" onClick={onCancel}>
      <div className="bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <p className="text-[14px] font-bold text-foreground mb-4">{message}</p>
        <div className="flex justify-end gap-3">
          <button onClick={onCancel} className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm} className="rounded-[10px] px-4 py-2 text-[13px] font-bold text-white bg-error hover:bg-error transition-colors">
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
  jurisdictionCountry = "IN",
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
    // Same reasoning applies to the income-tax column header itself —
    // "Tax" alone was the one static label left (TDS/PAYE/PAYG/
    // Lohnsteuer/Federal Withholding/Federal Tax all being genuinely
    // different terms), reusing the exact label map the payslip detail
    // view already uses so the two never disagree on wording.
    const incomeTaxLabel = getPayrollLabels(jurisdictionCountry).incomeTax;
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-muted border-b border-border">
              <th className="px-3 py-2.5 w-8">
                <input type="checkbox" checked={allSelected} onChange={toggleAllEmployees} className="rounded border-border h-3.5 w-3.5 text-primary focus:ring-primary" />
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Employee</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Department</th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Payable Days</th>
              <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Gross Pay</th>
              {!isSimple && contributionColumns.map((col) => (
                <th key={col.id} className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-foreground-muted">{col.label}</th>
              ))}
              {!isSimple && <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-foreground-muted">{incomeTaxLabel}</th>}
              <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-foreground-muted">{isSimple ? "LOP Deduction" : "Extra / Benefits"}</th>
              <th className="px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Net Pay</th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {employees.map((emp) => {
              const dept = DEPT_COLORS[emp.department] || { bg: "bg-surface-muted", text: "text-foreground-muted" };
              const isSelected = selectedEmployees.includes(emp.id);
              const extraBenefits = emp.monthlyExtra ?? ((Number(emp.rewards) || 0) + (Number(emp.bonus) || 0) + (Number(emp.otherCompensation) || 0));
              const empContribs = Object.fromEntries(
                (emp.contribComponents || []).map((c) => [c.id, c.value])
              );
              return (
                <tr key={emp.id} className={`transition-colors ${isSelected ? "bg-primary/5 dark:bg-primary/10" : "hover:bg-background dark:hover:bg-surface-muted"}`}>
                  <td className="px-3 py-2.5">
                    <input type="checkbox" checked={isSelected} onChange={() => toggleEmployee(emp.id)} className="rounded border-border h-3.5 w-3.5 text-primary focus:ring-primary" />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <Avatar name={emp.name} />
                      <div className="flex flex-col">
                        <span className="font-semibold text-foreground text-xs whitespace-nowrap">{emp.name}</span>
                        {emp.attendanceStatus && emp.attendanceStatus !== "unknown" && (
                          <span className={`text-[9px] font-bold ${
                            emp.attendanceStatus === "present" ? "text-primary" :
                            emp.attendanceStatus === "absent" ? "text-error" :
                            emp.attendanceStatus === "leave" ? "text-warning" :
                            "text-foreground-muted"
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
                      <span className={`text-xs font-semibold ${emp.prorated ? "text-amber-500" : "text-foreground-muted"}`}>
                        {emp.payableDays}/{emp.totalWorkingDays}{emp.prorated ? " \u26a0" : ""}
                      </span>
                    ) : (
                      <span className="text-xs text-foreground-muted">\u2014</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs font-semibold text-foreground whitespace-nowrap">
                    {fmtCurrencyLocal(emp.monthlyGross, fmtCurrency)}
                  </td>
                  {!isSimple && contributionColumns.map((col) => (
                    <td key={col.id} className="px-3 py-2.5 text-right text-xs font-semibold text-category-teal whitespace-nowrap">
                      {fmtCurrencyLocal(empContribs[col.id] ?? 0, fmtCurrency)}
                    </td>
                  ))}
                  {!isSimple && (
                    <td className="px-3 py-2.5 text-right whitespace-nowrap">
                      <span className="text-xs font-semibold text-error">{fmtCurrencyLocal(emp.monthlyTax, fmtCurrency)}</span>
                      {emp.taxSlabRate && emp.taxSlabRate !== "\u2014" && emp.taxSlabRate !== "Nil" && (
                        <span className={`ml-1 text-[9px] font-bold rounded px-1 py-px ${
                          emp.taxSlabRate.includes("87A rebate")
                            ? "text-primary bg-primary/10"
                            : "text-foreground-muted bg-surface-muted"
                        }`}>{emp.taxSlabRate}</span>
                      )}
                    </td>
                  )}
                  <td className="px-3 py-2.5 text-right text-xs font-semibold text-category-teal whitespace-nowrap">
                    {isSimple
                      ? fmtCurrencyLocal((emp.monthlyGross || 0) - (emp.monthlyNet || 0), fmtCurrency)
                      : fmtCurrencyLocal(extraBenefits, fmtCurrency)
                    }
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs font-bold text-info whitespace-nowrap">
                    {fmtCurrencyLocal(emp.monthlyNet, fmtCurrency)}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold bg-primary/10 text-primary">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary" />
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
            <tr className="bg-surface-muted border-b border-border">
              {listColumns.map((col) => (
                <th key={col} className={`px-5 py-3.5 text-[10px] font-bold uppercase tracking-widest text-foreground-muted ${col === "Gross" || col === "Deductions" || col === "Net" || col === "Submitted" ? "text-right" : col === "Actions" ? "text-center" : "text-left"}`}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {runs.map((run) => (
              <tr key={run.id} className="cursor-pointer transition-colors hover:bg-background dark:hover:bg-surface-muted" onClick={() => onSelect?.(run)}>
                <td className="px-5 py-4 text-xs font-semibold text-foreground">{run.period}</td>
                <td className="px-5 py-4 text-xs text-foreground-muted">{run.employees?.toLocaleString()}</td>
                <td className="px-5 py-4 text-xs font-semibold text-foreground text-right">{fmtCurrencyLocal(run.gross, fmtCurrency)}</td>
                <td className="px-5 py-4 text-xs font-semibold text-error text-right">{run.deductions ? fmtCurrencyLocal(run.deductions, fmtCurrency) : "\u2014"}</td>
                <td className="px-5 py-4 text-xs font-bold text-primary text-right">{fmtCurrencyLocal(run.net, fmtCurrency)}</td>
                <td className="px-5 py-4">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-5 py-4 text-xs text-foreground-muted text-right">{run.payDate}</td>
                <td className="px-5 py-4">
                  <div className="flex items-center justify-center gap-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); onSelect?.(run); }}
                      title="View"
                      className="rounded-[8px] p-1.5 text-foreground-muted hover:text-info hover:bg-info/10 transition-all duration-200"
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      onClick={(e) => handleApproveClick(e, run)}
                      title={nextStatusLabel(run.status) ? `Advance to ${nextStatusLabel(run.status)}` : "Already at final status"}
                      disabled={approvingId === run.id || !nextStatusLabel(run.status)}
                      className="rounded-[8px] p-1.5 text-foreground-muted hover:text-primary hover:bg-primary/10 transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      {approvingId === run.id ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmDelete(run.id); }}
                      title="Delete"
                      disabled={deletingId === run.id}
                      className="rounded-[8px] p-1.5 text-foreground-muted hover:text-error hover:bg-error/10 transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      {deletingId === run.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={listColumns.length} className="px-6 py-16 text-center text-[13px] text-foreground-muted">No payroll runs found.</td>
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
