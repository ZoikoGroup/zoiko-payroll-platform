import React, { useMemo, useState } from "react";
import { CheckSquare, Square, Users } from "lucide-react";
import { bulkUpdateEmployees, DEPARTMENTS, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES } from "../../../service/payrollService";
import { useToast } from "../ToastContext";

// Same editable field set as EmployeeForm.jsx — reused so this panel, the
// single-employee form, and the Send Template form builder never drift out
// of sync on what payroll considers an editable employee column.
export const STANDARD_EMPLOYEE_FIELDS = [
  { key: "department", label: "Department", type: "select", options: DEPARTMENTS },
  { key: "designation", label: "Designation", type: "text" },
  { key: "employmentType", label: "Employment type", type: "select", options: EMPLOYMENT_TYPES },
  { key: "status", label: "Status", type: "select", options: EMPLOYEE_STATUSES },
  { key: "dateOfJoining", label: "Date of joining", type: "date" },
  { key: "ctc", label: "CTC (annual)", type: "number" },
  { key: "bankName", label: "Bank name", type: "text" },
  { key: "bankAccountNumber", label: "Bank account number", type: "text" },
  { key: "ifscCode", label: "IFSC code", type: "text", uppercase: true },
  { key: "panNumber", label: "PAN number", type: "text", uppercase: true },
  { key: "uan", label: "UAN (PF)", type: "text" },
];

const FIELDS = STANDARD_EMPLOYEE_FIELDS;

const inputClass =
  "w-full rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-2 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200 disabled:opacity-50";

export default function EmployeeBulkEditPanel({ employees, selectedIds, onSaved, onClose, currencyInfo }) {
  const { addToast } = useToast();
  const symbol = currencyInfo?.symbol || "";
  const hasSelection = selectedIds && selectedIds.size > 0;
  const [scope, setScope] = useState(hasSelection ? "selected" : "all");
  const [checked, setChecked] = useState({});
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const targetIds = useMemo(() => {
    if (scope === "selected") return [...(selectedIds || [])];
    return employees.map((e) => e.id);
  }, [scope, selectedIds, employees]);

  const activeFieldKeys = Object.keys(checked).filter((k) => checked[k]);

  function toggleField(key) {
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function updateValue(key, value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setResult(null);

    if (targetIds.length === 0) {
      setError(scope === "selected" ? "No employees selected. Go back and select employees, or choose \"All employees\"." : "There are no employees to update.");
      return;
    }
    if (activeFieldKeys.length === 0) {
      setError("Check at least one field to update.");
      return;
    }
    for (const key of activeFieldKeys) {
      const field = FIELDS.find((f) => f.key === key);
      const raw = values[key];
      if (raw === undefined || raw === "") {
        setError(`Enter a value for "${field.label}", or uncheck it.`);
        return;
      }
    }

    const patch = {};
    for (const key of activeFieldKeys) {
      const field = FIELDS.find((f) => f.key === key);
      let v = values[key];
      if (field.type === "number") v = Number(v);
      else if (field.uppercase) v = String(v).toUpperCase();
      patch[key] = v;
    }

    setSaving(true);
    try {
      const res = await bulkUpdateEmployees(targetIds.map((id) => ({ id, ...patch })));
      const updated = res.employees || [];
      const failed = res.failed || [];
      setResult({ updated: updated.length, failed: failed.length, failedDetail: failed });
      if (updated.length > 0) {
        onSaved?.(updated);
      }
      if (failed.length === 0) {
        addToast?.(`${updated.length} employee${updated.length === 1 ? "" : "s"} updated.`, "success");
      } else {
        addToast?.(`${updated.length} updated, ${failed.length} failed.`, updated.length > 0 ? "warning" : "error");
      }
    } catch (err) {
      setError(err.message || "Bulk update failed. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div>
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Update employees</h3>
        <p className="text-[13px] text-[#9E9690] mt-1">
          Choose which employees and which field(s) to change. Only the fields you check are updated — everything else on each record stays exactly as it is.
        </p>
      </div>

      <div>
        <span className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Employees</span>
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={() => hasSelection && setScope("selected")}
            disabled={!hasSelection}
            className={`flex-1 flex items-center gap-2.5 rounded-[12px] border px-4 py-3 text-left text-[13px] font-semibold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed ${
              scope === "selected" ? "border-[#19C58A] bg-[#19C58A]/5 text-[#19C58A]" : "border-[#E5E0D9] dark:border-[#38312D] text-[#6B6560] dark:text-[#A69B93]"
            }`}
          >
            {scope === "selected" ? <CheckSquare size={16} /> : <Square size={16} />}
            Selected employees ({selectedIds?.size || 0})
          </button>
          <button
            type="button"
            onClick={() => setScope("all")}
            className={`flex-1 flex items-center gap-2.5 rounded-[12px] border px-4 py-3 text-left text-[13px] font-semibold transition-all duration-200 ${
              scope === "all" ? "border-[#19C58A] bg-[#19C58A]/5 text-[#19C58A]" : "border-[#E5E0D9] dark:border-[#38312D] text-[#6B6560] dark:text-[#A69B93]"
            }`}
          >
            <Users size={16} />
            All employees in this list ({employees.length})
          </button>
        </div>
        {scope === "all" && (
          <p className="mt-1.5 text-[11.5px] text-[#9E9690]">This applies to every employee currently matching your search/filters, not necessarily your whole organization.</p>
        )}
      </div>

      <div>
        <span className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Fields to update</span>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {FIELDS.map((field) => {
            const isChecked = Boolean(checked[field.key]);
            return (
              <div
                key={field.key}
                className={`rounded-[12px] border px-3.5 py-3 transition-all duration-200 ${
                  isChecked ? "border-[#19C58A] bg-[#19C58A]/5" : "border-[#E5E0D9] dark:border-[#38312D]"
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggleField(field.key)}
                  className="flex w-full items-center gap-2.5 text-left text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]"
                >
                  {isChecked ? <CheckSquare size={16} className="text-[#19C58A] flex-shrink-0" /> : <Square size={16} className="text-[#9E9690] flex-shrink-0" />}
                  {field.label}{field.type === "number" && symbol ? ` (${symbol})` : ""}
                </button>
                {isChecked && (
                  <div className="mt-2.5">
                    {field.type === "select" ? (
                      <select
                        className={inputClass}
                        value={values[field.key] ?? ""}
                        onChange={(e) => updateValue(field.key, e.target.value)}
                      >
                        <option value="" disabled>Choose {field.label.toLowerCase()}…</option>
                        {field.options.map((opt) => (
                          <option key={opt} value={opt}>{opt}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={field.type}
                        min={field.type === "number" ? "0" : undefined}
                        className={inputClass}
                        value={values[field.key] ?? ""}
                        onChange={(e) => updateValue(field.key, field.uppercase ? e.target.value.toUpperCase() : e.target.value)}
                        placeholder={`New ${field.label.toLowerCase()}`}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {error && (
        <div className="rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">
          {error}
        </div>
      )}

      {result && (
        <div className="rounded-[12px] bg-[#19C58A]/10 px-4 py-3 text-[13px] text-[#19C58A] border border-[#19C58A]/20">
          {result.updated} employee{result.updated === 1 ? "" : "s"} updated.
          {result.failed > 0 && (
            <span className="block mt-1 text-[#FF6E86]">
              {result.failed} failed: {result.failedDetail.map((f) => f.reason || `#${f.id}`).join("; ")}
            </span>
          )}
        </div>
      )}

      <div className="flex justify-end gap-3 border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
        <button
          type="button"
          onClick={onClose}
          className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
        >
          Close
        </button>
        <button
          type="submit"
          disabled={saving}
          className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-60"
        >
          {saving ? "Updating…" : `Update ${targetIds.length} employee${targetIds.length === 1 ? "" : "s"}`}
        </button>
      </div>
    </form>
  );
}
