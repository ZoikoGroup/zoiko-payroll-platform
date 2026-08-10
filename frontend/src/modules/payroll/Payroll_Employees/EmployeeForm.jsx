import React, { useState } from "react";
import { createEmployee, updateEmployee, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, DEPARTMENTS } from "../../../service/payrollService";

const EMPTY_FORM = {
  name: "",
  email: "",
  phone: "",
  department: DEPARTMENTS[0],
  designation: "",
  employmentType: EMPLOYMENT_TYPES[0],
  status: "Active",
  dateOfJoining: "",
  ctc: "",
  basic: "",
  hra: "",
  bankName: "",
  bankAccountNumber: "",
  ifscCode: "",
  panNumber: "",
  uan: "",
};

function Field({ label, children, error }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">{label}</span>
      {children}
      {error && <span className="mt-1.5 block text-[11px] font-semibold text-[#FF6E86]">{error}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200";

const selectClass =
  "w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200";

function validate(form) {
  const errors = {};
  if (!form.name.trim()) errors.name = "Employee name is required";
  if (!form.email.trim()) errors.email = "Email is required";
  else if (!/^\S+@\S+\.\S+$/.test(form.email)) errors.email = "Enter a valid email";
  if (!form.designation.trim()) errors.designation = "Designation is required";
  if (!form.dateOfJoining) errors.dateOfJoining = "Date of joining is required";
  if (!form.ctc || Number(form.ctc) <= 0) errors.ctc = "Enter a valid annual CTC";
  if (form.panNumber && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(form.panNumber.toUpperCase())) {
    errors.panNumber = "PAN format looks incorrect (e.g. ABCDE1234F)";
  }
  return errors;
}

export default function EmployeeForm({ employee, onSaved, onCancel, currencyInfo }) {
  const symbol = currencyInfo?.symbol || "";
  const isEdit = Boolean(employee?.id);
  const [form, setForm] = useState(() => (employee ? { ...EMPTY_FORM, ...employee } : EMPTY_FORM));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState("");

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const validationErrors = validate(form);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) return;

    setSaving(true);
    setSubmitError("");
    try {
      const payload = {
        ...form,
        ctc: Number(form.ctc),
        // Empty string means the admin cleared the field — send explicit
        // null so the backend actually nulls it out instead of silently
        // keeping the old value. The backend's partial-update skips only
        // "" (meaning "not touched"); undefined keys are dropped by
        // JSON.stringify before they even reach it, and null is the only
        // value that reliably signals "clear this field."
        basic: form.basic !== "" ? Number(form.basic) : null,
        hra: form.hra !== "" ? Number(form.hra) : null,
        phone: form.phone !== "" ? form.phone : null,
        bankName: form.bankName !== "" ? form.bankName : null,
        bankAccountNumber: form.bankAccountNumber !== "" ? form.bankAccountNumber : null,
        ifscCode: form.ifscCode !== "" ? form.ifscCode : null,
        uan: form.uan !== "" ? form.uan : null,
        panNumber: form.panNumber ? form.panNumber.toUpperCase() : null,
      };
      const saved = isEdit ? await updateEmployee(employee.id, payload) : await createEmployee(payload);
      onSaved?.(saved);
    } catch (err) {
      setSubmitError(err.message || "Something went wrong while saving. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div>
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Personal details</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Employee name" error={errors.name}>
            <input className={`${inputClass} ${errors.name ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.name} onChange={(e) => update("name", e.target.value)} />
          </Field>
          <Field label="Email" error={errors.email}>
            <input type="email" className={`${inputClass} ${errors.email ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.email} onChange={(e) => update("email", e.target.value)} />
          </Field>
          <Field label="Phone">
            <input className={inputClass} value={form.phone} onChange={(e) => update("phone", e.target.value)} />
          </Field>
        </div>
      </div>

      <div className="border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Employment</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Department">
            <select className={selectClass} value={form.department} onChange={(e) => update("department", e.target.value)}>
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </Field>
          <Field label="Designation" error={errors.designation}>
            <input className={`${inputClass} ${errors.designation ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.designation} onChange={(e) => update("designation", e.target.value)} />
          </Field>
          <Field label="Employment type">
            <select className={selectClass} value={form.employmentType} onChange={(e) => update("employmentType", e.target.value)}>
              {EMPLOYMENT_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </Field>
          <Field label="Status">
            <select className={selectClass} value={form.status} onChange={(e) => update("status", e.target.value)}>
              {EMPLOYEE_STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Date of joining" error={errors.dateOfJoining}>
            <input type="date" className={`${inputClass} ${errors.dateOfJoining ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.dateOfJoining} onChange={(e) => update("dateOfJoining", e.target.value)} />
          </Field>
        </div>
      </div>

      <div className="border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Salary structure (annual)</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label={`CTC (${symbol})`} error={errors.ctc}>
            <input type="number" min="0" className={`${inputClass} ${errors.ctc ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.ctc} onChange={(e) => update("ctc", e.target.value)} />
          </Field>
          <Field label={`Basic (${symbol})`}>
            <input type="number" min="0" className={inputClass} value={form.basic} onChange={(e) => update("basic", e.target.value)} />
          </Field>
          <Field label={`HRA (${symbol})`}>
            <input type="number" min="0" className={inputClass} value={form.hra} onChange={(e) => update("hra", e.target.value)} />
          </Field>
        </div>
      </div>

      <div className="border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Statutory & bank details</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Bank name">
            <input className={inputClass} value={form.bankName} onChange={(e) => update("bankName", e.target.value)} />
          </Field>
          <Field label="Bank account number">
            <input className={inputClass} value={form.bankAccountNumber} onChange={(e) => update("bankAccountNumber", e.target.value)} />
          </Field>
          <Field label="IFSC code">
            <input className={inputClass} value={form.ifscCode} onChange={(e) => update("ifscCode", e.target.value.toUpperCase())} />
          </Field>
          <Field label="PAN number" error={errors.panNumber}>
            <input className={`${inputClass} ${errors.panNumber ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.panNumber} onChange={(e) => update("panNumber", e.target.value.toUpperCase())} />
          </Field>
          <Field label="UAN (PF)">
            <input className={inputClass} value={form.uan} onChange={(e) => update("uan", e.target.value)} />
          </Field>
        </div>
      </div>

      {submitError && (
        <div className="rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">
          {submitError}
        </div>
      )}

      <div className="flex justify-end gap-3 border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
        <button
          type="button"
          onClick={onCancel}
          className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {saving ? "Saving…" : isEdit ? "Save changes" : "Add employee"}
        </button>
      </div>
    </form>
  );
}
