import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, TriangleAlert } from "lucide-react";
import { bulkUpdateEmployees, DEPARTMENTS, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES } from "../../../service/payrollService";
import { useToast } from "../ToastContext";
import {
  EmployeePicker, FieldChecklist, WizardError, WizardFooter, WizardSteps, sectionLabelClass, wizardInputClass,
} from "./EmployeeWizardParts";

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

const STEPS = [
  { id: "employees", label: "Select employees" },
  { id: "fields", label: "Fields & new values" },
  { id: "review", label: "Review & update" },
];

const REVIEW_NAME_LIMIT = 10;

// Step-by-step bulk update: pick employees -> pick fields and enter the new
// values -> review exactly what will change -> apply. Only the checked fields
// of the selected employees are sent to the API; nothing else is touched.
export default function EmployeeBulkEditPanel({ employees, selectedIds, onSaved, onClose, currencyInfo, orgCountryCode }) {
  const { addToast } = useToast();
  const symbol = currencyInfo?.symbol || "";
  const [step, setStep] = useState(0); // 0..2, then "done"
  // Its own selection, seeded from the Employee List's — changing it here
  // never changes what is ticked on the list (where Delete acts on it).
  const [pickedIds, setPickedIds] = useState(() => new Set(selectedIds || []));
  const [checked, setChecked] = useState({});
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [showAllNames, setShowAllNames] = useState(false);
  const headingRef = useRef(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const fieldLabel = (field) => (field.type === "number" && symbol ? `${field.label.replace(/\)$/, "")}, ${symbol})` : field.label);
  const activeFields = FIELDS.filter((f) => checked[f.key]);
  const selectedEmployees = useMemo(
    () => (employees || []).filter((e) => pickedIds.has(e.id)),
    [employees, pickedIds],
  );
  const employeeCount = selectedEmployees.length;

  function goTo(next) {
    setError("");
    setStep(next);
  }

  function toggleField(key) {
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function updateValue(key, value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function validateFields() {
    if (activeFields.length === 0) return "Choose at least one field to update.";
    for (const field of activeFields) {
      const raw = values[field.key];
      if (raw === undefined || String(raw).trim() === "") return `Enter a new value for "${fieldLabel(field)}", or untick it.`;
      if (field.type === "number" && (!Number.isFinite(Number(raw)) || Number(raw) < 0)) {
        return `"${fieldLabel(field)}" must be a number of 0 or more.`;
      }
    }
    return "";
  }

  function handleContinueFromFields() {
    const problem = validateFields();
    if (problem) {
      setError(problem);
      return;
    }
    goTo(2);
  }

  function buildPatch() {
    const patch = {};
    for (const field of activeFields) {
      let v = values[field.key];
      if (field.type === "number") v = Number(v);
      else if (field.uppercase) v = String(v).trim().toUpperCase();
      else v = String(v).trim();
      patch[field.key] = v;
    }
    return patch;
  }

  function displayValue(field) {
    const v = values[field.key];
    if (field.type === "number") {
      const n = Number(v);
      return `${symbol}${Number.isFinite(n) ? n.toLocaleString() : v}`;
    }
    if (field.uppercase) return String(v).toUpperCase();
    return String(v);
  }

  async function handleApply() {
    setError("");
    const ids = selectedEmployees.map((e) => e.id);
    if (ids.length === 0) {
      setError("No employees selected. Go back to step 1 and select at least one.");
      return;
    }
    const problem = validateFields();
    if (problem) {
      setError(problem);
      return;
    }
    const patch = buildPatch();
    setSaving(true);
    try {
      const res = await bulkUpdateEmployees(ids.map((id) => ({ id, ...patch })));
      const updated = res.employees || [];
      const failed = res.failed || [];
      setResult({ updated: updated.length, failed });
      if (updated.length > 0) onSaved?.(updated);
      if (failed.length === 0) {
        addToast?.(`${updated.length} employee${updated.length === 1 ? "" : "s"} updated.`, "success");
      } else {
        addToast?.(`${updated.length} updated, ${failed.length} failed.`, updated.length > 0 ? "warning" : "error");
      }
      setStep("done");
    } catch (err) {
      setError(err.message || "Bulk update failed. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  function startOver() {
    setPickedIds(new Set());
    setChecked({});
    setValues({});
    setResult(null);
    setShowAllNames(false);
    goTo(0);
  }

  const nameOf = (id) => (employees || []).find((e) => e.id === id)?.name || `#${id}`;
  const visibleNames = showAllNames ? selectedEmployees : selectedEmployees.slice(0, REVIEW_NAME_LIMIT);

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div>
          <h3 ref={headingRef} tabIndex={-1} className="text-[15px] font-bold text-foreground outline-none">
            Update employees
          </h3>
          <p className="mt-1 text-[13px] text-foreground-muted">
            Change one or more fields for the employees you choose. Only the fields you tick are changed — everything else on
            each record stays exactly as it is.
          </p>
        </div>
        <WizardSteps steps={STEPS} current={step === "done" ? STEPS.length : step} />
      </div>

      {step === 0 && (
        <>
          <div>
            <span className={sectionLabelClass}>Which employees?</span>
            <EmployeePicker
              employees={employees}
              selectedIds={pickedIds}
              onSelectionChange={setPickedIds}
              currencyInfo={currencyInfo}
              orgCountryCode={orgCountryCode}
            />
          </div>
          <WizardError>{error}</WizardError>
          <WizardFooter
            onCancel={onClose}
            onNext={() => goTo(1)}
            nextDisabled={employeeCount === 0}
            nextLabel={employeeCount === 0 ? "Select employees to continue" : `Continue with ${employeeCount} employee${employeeCount === 1 ? "" : "s"}`}
          />
        </>
      )}

      {step === 1 && (
        <>
          <div className="rounded-[12px] border border-border bg-surface-muted px-4 py-2.5 text-[13px] text-foreground" aria-live="polite">
            Updating <strong>{employeeCount}</strong> employee{employeeCount === 1 ? "" : "s"} ·{" "}
            <strong>{activeFields.length}</strong> field{activeFields.length === 1 ? "" : "s"} chosen
          </div>
          <div>
            <span className={sectionLabelClass}>Which fields, and what should they become?</span>
            <FieldChecklist
              fields={FIELDS.map((f) => ({ key: f.key, label: fieldLabel(f) }))}
              checked={checked}
              onToggle={toggleField}
              renderExtra={({ key }) => {
                const field = FIELDS.find((f) => f.key === key);
                return field.type === "select" ? (
                  <select
                    aria-label={`New ${field.label.toLowerCase()}`}
                    className={wizardInputClass}
                    value={values[key] ?? ""}
                    onChange={(e) => updateValue(key, e.target.value)}
                  >
                    <option value="" disabled>Choose {field.label.toLowerCase()}…</option>
                    {field.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                  </select>
                ) : (
                  <input
                    type={field.type}
                    min={field.type === "number" ? "0" : undefined}
                    aria-label={`New ${field.label.toLowerCase()}`}
                    className={wizardInputClass}
                    value={values[key] ?? ""}
                    onChange={(e) => updateValue(key, field.uppercase ? e.target.value.toUpperCase() : e.target.value)}
                    placeholder={`New ${field.label.toLowerCase()}`}
                  />
                );
              }}
            />
          </div>
          <WizardError>{error}</WizardError>
          <WizardFooter
            onCancel={onClose}
            onPrevious={() => goTo(0)}
            onNext={handleContinueFromFields}
            nextDisabled={activeFields.length === 0}
            nextLabel="Review changes"
          />
        </>
      )}

      {step === 2 && (
        <>
          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
            <div className="rounded-[14px] border border-border">
              <div className="border-b border-border px-4 py-3">
                <p className="text-[13px] font-bold text-foreground">
                  {activeFields.length} field{activeFields.length === 1 ? "" : "s"} will change
                </p>
              </div>
              <dl className="divide-y divide-border">
                {activeFields.map((field) => (
                  <div key={field.key} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-[13px]">
                    <dt className="text-foreground-muted">{fieldLabel(field)}</dt>
                    <dd className="font-semibold text-foreground">{displayValue(field)}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="rounded-[14px] border border-border">
              <div className="border-b border-border px-4 py-3">
                <p className="text-[13px] font-bold text-foreground">
                  For {employeeCount} employee{employeeCount === 1 ? "" : "s"}
                </p>
              </div>
              <ul className="max-h-72 divide-y divide-border overflow-y-auto">
                {visibleNames.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-2 px-4 py-2 text-[13px]">
                    <span className="font-semibold text-foreground">{e.name}</span>
                    <span className="text-foreground-muted">{e.employeeCode}</span>
                  </li>
                ))}
              </ul>
              {selectedEmployees.length > REVIEW_NAME_LIMIT && (
                <button
                  type="button"
                  onClick={() => setShowAllNames((v) => !v)}
                  className="w-full border-t border-border px-4 py-2 text-left text-[12.5px] font-semibold text-primary hover:text-primary-hover"
                >
                  {showAllNames ? "Show fewer" : `Show all ${selectedEmployees.length}`}
                </button>
              )}
            </div>
          </div>
          <div className="flex items-start gap-2 rounded-[12px] border border-warning/30 bg-warning/10 px-4 py-3 text-[13px] text-warning">
            <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>
              This replaces the {activeFields.length === 1 ? "field" : `${activeFields.length} fields`} above for{" "}
              {employeeCount === 1 ? "this employee" : `all ${employeeCount} employees`}. Nothing else on their records changes.
            </p>
          </div>
          <WizardError>{error}</WizardError>
          <WizardFooter
            onCancel={onClose}
            onPrevious={() => goTo(1)}
            onNext={handleApply}
            busy={saving}
            nextLabel={saving ? "Updating…" : `Update ${employeeCount} employee${employeeCount === 1 ? "" : "s"}`}
          />
        </>
      )}

      {step === "done" && result && (
        <>
          <div className="flex items-start gap-3 rounded-[12px] border border-primary/20 bg-primary/10 px-4 py-3 text-[13px] text-primary">
            <CheckCircle2 size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>
              {result.updated} employee{result.updated === 1 ? "" : "s"} updated.
            </p>
          </div>
          {result.failed.length > 0 && (
            <div className="rounded-[12px] border border-error/20 bg-error/10 px-4 py-3 text-[13px] text-error">
              <p className="mb-1 font-semibold">{result.failed.length} could not be updated:</p>
              <ul className="space-y-0.5">
                {result.failed.map((f, i) => {
                  // The API reports failures as { row: { id, name }, reason }.
                  const id = f.row?.id ?? f.id;
                  const name = f.row?.name || (id !== undefined && id !== null ? nameOf(id) : null);
                  return <li key={id ?? i}>{name ? `${name} — ` : ""}{f.reason || "Update failed."}</li>;
                })}
              </ul>
            </div>
          )}
          <WizardFooter onCancel={startOver} cancelLabel="Update more employees" onNext={onClose} nextLabel="Done" />
        </>
      )}
    </div>
  );
}
