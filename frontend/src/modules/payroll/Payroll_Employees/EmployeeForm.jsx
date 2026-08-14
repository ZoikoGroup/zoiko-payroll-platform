import React, { useState } from "react";
import { createEmployee, updateEmployee, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, DEPARTMENTS } from "../../../service/payrollService";
import { COUNTRIES, COUNTRY_FIELD_SPECS } from "./countryFieldSpecs";

function emptyCompliance() {
  return {};
}

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
  bankName: "",
  bankAccountNumber: "",
  ifscCode: "",
  panNumber: "",
  uan: "",
  countryCode: "IN",
  complianceFields: emptyCompliance(),
};

function Field({ label, children, error }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {error && <span className="mt-1.5 block text-[11px] font-semibold text-error">{error}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

const selectClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

function validate(form) {
  const errors = {};
  if (!form.name.trim()) errors.name = "Employee name is required";
  if (!form.email.trim()) errors.email = "Email is required";
  else if (!/^\S+@\S+\.\S+$/.test(form.email)) errors.email = "Enter a valid email";
  if (!form.designation.trim()) errors.designation = "Designation is required";
  if (!form.dateOfJoining) errors.dateOfJoining = "Date of joining is required";
  if (!form.ctc || Number(form.ctc) <= 0) errors.ctc = "Enter a valid annual CTC";
  if (form.countryCode === "IN" && form.panNumber && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(form.panNumber.toUpperCase())) {
    errors.panNumber = "PAN format looks incorrect (e.g. ABCDE1234F)";
  }
  // Jurisdiction-specific field patterns (SSN, NINO, IBAN, etc.) are
  // validated authoritatively server-side by employee_validation.py's
  // Strategy classes — not re-implemented here, so there's exactly one
  // place that defines "valid" per country.
  return errors;
}

export default function EmployeeForm({ employee, onSaved, onCancel, currencyInfo, defaultCountryCode }) {
  const symbol = currencyInfo?.symbol || "";
  const isEdit = Boolean(employee?.id);
  const [form, setForm] = useState(() => {
    if (employee) {
      return {
        ...EMPTY_FORM,
        ...employee,
        countryCode: employee.countryCode || defaultCountryCode || "IN",
        complianceFields: employee.complianceFields || {},
      };
    }
    return { ...EMPTY_FORM, countryCode: defaultCountryCode || "IN" };
  });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState("");

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function updateCompliance(key, value) {
    setForm((prev) => ({ ...prev, complianceFields: { ...prev.complianceFields, [key]: value } }));
  }

  function handleCountryChange(code) {
    // Switching jurisdiction starts compliance fields fresh — a NINO typed
    // in under UK has no meaning once the employee is switched to DE.
    setForm((prev) => ({ ...prev, countryCode: code, complianceFields: {} }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const validationErrors = validate(form);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) return;

    setSaving(true);
    setSubmitError("");
    try {
      const isIndia = form.countryCode === "IN";
      const payload = {
        ...form,
        ctc: Number(form.ctc),
        // Basic/HRA are no longer editable columns — the backend derives
        // them from CTC (40% / 20%) whenever they're absent.
        phone: form.phone !== "" ? form.phone : null,
        bankName: form.bankName !== "" ? form.bankName : null,
        bankAccountNumber: form.bankAccountNumber !== "" ? form.bankAccountNumber : null,
        // pan/uan/ifsc are India's dedicated columns — keep them null for
        // every other jurisdiction so switching an employee's country away
        // from India doesn't leave stray Indian identifiers on their record.
        ifscCode: isIndia && form.ifscCode !== "" ? form.ifscCode : null,
        uan: isIndia && form.uan !== "" ? form.uan : null,
        panNumber: isIndia && form.panNumber ? form.panNumber.toUpperCase() : null,
        complianceFields: isIndia ? form.complianceFields : form.complianceFields,
      };
      const saved = isEdit ? await updateEmployee(employee.id, payload) : await createEmployee(payload);
      onSaved?.(saved);
    } catch (err) {
      setSubmitError(err.message || "Something went wrong while saving. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const complianceSpec = COUNTRY_FIELD_SPECS[form.countryCode] || [];

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div>
        <h3 className="text-[15px] font-bold text-foreground">Personal details</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Employee name" error={errors.name}>
            <input className={`${inputClass} ${errors.name ? "border-error focus:border-error focus:ring-error/20" : ""}`} value={form.name} onChange={(e) => update("name", e.target.value)} />
          </Field>
          <Field label="Email" error={errors.email}>
            <input type="email" className={`${inputClass} ${errors.email ? "border-error focus:border-error focus:ring-error/20" : ""}`} value={form.email} onChange={(e) => update("email", e.target.value)} />
          </Field>
          <Field label="Phone">
            <input className={inputClass} value={form.phone} onChange={(e) => update("phone", e.target.value)} />
          </Field>
        </div>
      </div>

      <div className="border-t border-border pt-6">
        <h3 className="text-[15px] font-bold text-foreground">Employment</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Department">
            <select className={selectClass} value={form.department} onChange={(e) => update("department", e.target.value)}>
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </Field>
          <Field label="Designation" error={errors.designation}>
            <input className={`${inputClass} ${errors.designation ? "border-error focus:border-error focus:ring-error/20" : ""}`} value={form.designation} onChange={(e) => update("designation", e.target.value)} />
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
            <input type="date" className={`${inputClass} ${errors.dateOfJoining ? "border-error focus:border-error focus:ring-error/20" : ""}`} value={form.dateOfJoining} onChange={(e) => update("dateOfJoining", e.target.value)} />
          </Field>
          <Field label="Country / jurisdiction">
            <select className={selectClass} value={form.countryCode} onChange={(e) => handleCountryChange(e.target.value)}>
              {COUNTRIES.map((c) => (
                <option key={c.code} value={c.code}>{c.name}</option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <div className="border-t border-border pt-6">
        <h3 className="text-[15px] font-bold text-foreground">Salary structure (annual)</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={`CTC (${symbol})`} error={errors.ctc}>
            <input type="number" min="0" className={`${inputClass} ${errors.ctc ? "border-error focus:border-error focus:ring-error/20" : ""}`} value={form.ctc} onChange={(e) => update("ctc", e.target.value)} />
          </Field>
        </div>
      </div>

      <div className="border-t border-border pt-6">
        <h3 className="text-[15px] font-bold text-foreground">Bank details</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Bank name">
            <input className={inputClass} value={form.bankName} onChange={(e) => update("bankName", e.target.value)} />
          </Field>
          <Field label="Bank account number">
            <input className={inputClass} value={form.bankAccountNumber} onChange={(e) => update("bankAccountNumber", e.target.value)} />
          </Field>
          {form.countryCode === "IN" && (
            <Field label="IFSC code">
              <input className={inputClass} value={form.ifscCode} onChange={(e) => update("ifscCode", e.target.value.toUpperCase())} />
            </Field>
          )}
        </div>
      </div>

      <div className="border-t border-border pt-6">
        <h3 className="text-[15px] font-bold text-foreground">
          Statutory details &mdash; {COUNTRIES.find((c) => c.code === form.countryCode)?.name}
        </h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {form.countryCode === "IN" && (
            <>
              <Field label="PAN number" error={errors.panNumber}>
                <input className={`${inputClass} ${errors.panNumber ? "border-error focus:border-error focus:ring-error/20" : ""}`} value={form.panNumber} onChange={(e) => update("panNumber", e.target.value.toUpperCase())} />
              </Field>
              <Field label="UAN (PF)">
                <input className={inputClass} value={form.uan} onChange={(e) => update("uan", e.target.value)} />
              </Field>
            </>
          )}
          {complianceSpec.map((spec) =>
            spec.type === "select" ? (
              <Field key={spec.key} label={spec.label}>
                <select
                  className={selectClass}
                  value={form.complianceFields[spec.key] || ""}
                  onChange={(e) => updateCompliance(spec.key, e.target.value)}
                >
                  <option value="">Select&hellip;</option>
                  {spec.choices.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </Field>
            ) : (
              <Field key={spec.key} label={spec.label}>
                <input
                  className={inputClass}
                  placeholder={spec.placeholder}
                  value={form.complianceFields[spec.key] || ""}
                  onChange={(e) => updateCompliance(spec.key, e.target.value)}
                />
              </Field>
            )
          )}
        </div>
      </div>

      {submitError && (
        <div className="rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">
          {submitError}
        </div>
      )}

      <div className="flex justify-end gap-3 border-t border-border pt-6">
        <button
          type="button"
          onClick={onCancel}
          className="border border-border bg-surface-muted rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {saving ? "Saving…" : isEdit ? "Save changes" : "Add employee"}
        </button>
      </div>
    </form>
  );
}
