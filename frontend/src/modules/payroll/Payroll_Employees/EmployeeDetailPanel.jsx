import React, { useEffect, useState } from "react";
import { X, Edit, Trash2 } from "lucide-react";
import EmployeeForm from "./EmployeeForm";
import { deleteEmployee, getCustomFields } from "../../../service/payrollService";

const DEPARTMENT_STYLES = {
  Engineering: "bg-info/10 text-info",
  Sales: "bg-primary/10 text-primary",
  Marketing: "bg-category-teal/10 text-category-teal",
  HR: "bg-error/10 text-error",
  Finance: "bg-warning/10 text-warning",
};

function DepartmentBadge({ dept }) {
  const style = DEPARTMENT_STYLES[dept] || "bg-foreground-muted/10 text-foreground-muted";
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${style}`}>
      {dept}
    </span>
  );
}

function initials(name) {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0][0]}${parts[parts.length - 1][0]}` : parts[0].slice(0, 2);
}

function formatCurrency(value, info) {
  if (value === null || value === undefined || value === "") return "—";
  if (!info) return value;
  try {
    return new Intl.NumberFormat(info.locale, {
      style: "currency",
      currency: info.code,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${info.symbol}${value}`;
  }
}

function DetailRow({ label, value }) {
  return (
    <div className="flex justify-between gap-4 py-3">
      <dt className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</dt>
      <dd className="text-[13px] font-semibold text-foreground text-right">{value || "—"}</dd>
    </div>
  );
}

export default function EmployeeDetailPanel({ employee, onClose, onUpdated, onDeleted, currencyInfo }) {
  const [mode, setMode] = useState("view");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [customFieldDefs, setCustomFieldDefs] = useState([]);

  useEffect(() => {
    getCustomFields().then(setCustomFieldDefs).catch(() => {});
  }, []);

  if (!employee) return null;

  const customFieldEntries = customFieldDefs
    .map((def) => ({ label: def.label, value: employee.customFields?.[def.fieldKey] }))
    .filter((entry) => entry.value !== undefined && entry.value !== null && entry.value !== "");

  async function handleDelete() {
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteEmployee(employee.id);
      onDeleted?.(employee.id);
    } catch (err) {
      setDeleteError(err.message || "Could not remove this employee. Please try again.");
    } finally {
      setDeleting(false);
      setConfirmingDelete(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-lg flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <h2 className="text-[15px] font-bold text-foreground">
            {mode === "edit" ? "Edit employee" : employee.name}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="border border-border bg-surface-muted rounded-[12px] p-2 text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
          >
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {mode === "edit" ? (
            <EmployeeForm
              employee={employee}
              currencyInfo={currencyInfo}
              onCancel={() => setMode("view")}
              onSaved={(updated) => {
                setMode("view");
                onUpdated?.(updated);
              }}
            />
          ) : (
            <>
              <div className="flex items-center gap-4 mb-6 pb-6 border-b border-border">
                <div className="w-14 h-14 rounded-full bg-info/10 text-info flex items-center justify-center text-[18px] font-bold">
                  {initials(employee.name)}
                </div>
                <div>
                  <h3 className="text-[15px] font-bold text-foreground">{employee.name}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[13px] text-foreground-muted">{employee.employeeCode}</span>
                    <DepartmentBadge dept={employee.department} />
                  </div>
                </div>
              </div>

              <div className="bg-surface-muted rounded-[18px] p-5">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Contact & employment</h4>
                <dl className="divide-y divide-border">
                  <DetailRow label="Email" value={employee.email} />
                  <DetailRow label="Phone" value={employee.phone} />
                  <DetailRow label="Designation" value={employee.designation} />
                  <DetailRow label="Employment type" value={employee.employmentType} />
                  <DetailRow label="Status" value={employee.status} />
                  <DetailRow label="Date of joining" value={employee.dateOfJoining} />
                </dl>
              </div>

              <div className="bg-surface-muted rounded-[18px] p-5 mt-4">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Salary structure</h4>
                <dl className="divide-y divide-border">
                  <DetailRow label="Annual CTC" value={formatCurrency(employee.ctc, currencyInfo)} />
                </dl>
              </div>

              <div className="bg-surface-muted rounded-[18px] p-5 mt-4">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Statutory & bank</h4>
                <dl className="divide-y divide-border">
                  <DetailRow label="Bank name" value={employee.bankName} />
                  <DetailRow label="Bank account" value={employee.bankAccountNumber} />
                  <DetailRow label="PAN" value={employee.panNumber} />
                </dl>
              </div>

              {customFieldEntries.length > 0 && (
                <div className="bg-surface-muted rounded-[18px] p-5 mt-4">
                  <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Custom fields</h4>
                  <dl className="divide-y divide-border">
                    {customFieldEntries.map((entry) => (
                      <DetailRow key={entry.label} label={entry.label} value={String(entry.value)} />
                    ))}
                  </dl>
                </div>
              )}

              {deleteError && (
                <div className="mt-4 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">
                  {deleteError}
                </div>
              )}
            </>
          )}
        </div>

        {mode === "view" && (
          <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-4">
            {confirmingDelete ? (
              <div className="flex w-full items-center justify-between gap-2">
                <span className="text-[13px] font-semibold text-foreground">Remove this employee?</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => setConfirmingDelete(false)}
                    className="border border-border bg-surface-muted rounded-[12px] px-4 py-2 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleDelete}
                    disabled={deleting}
                    className="bg-error rounded-[12px] px-4 py-2 text-[13px] font-bold text-white transition-all duration-200 hover:bg-error shadow-[0_2px_8px_rgba(255,110,134,0.3)] disabled:opacity-60"
                  >
                    {deleting ? "Removing…" : "Confirm remove"}
                  </button>
                </div>
              </div>
            ) : (
              <>
                <button
                  onClick={() => setConfirmingDelete(true)}
                  className="border border-border bg-surface-muted rounded-[12px] px-4 py-2.5 text-[13px] font-semibold text-error transition-all duration-200 hover:border-error"
                >
                  <Trash2 size={14} className="inline mr-1.5 -mt-0.5" />
                  Remove
                </button>
                <button
                  onClick={() => setMode("edit")}
                  className="bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px]"
                >
                  <Edit size={14} className="inline mr-1.5 -mt-0.5" />
                  Edit details
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
