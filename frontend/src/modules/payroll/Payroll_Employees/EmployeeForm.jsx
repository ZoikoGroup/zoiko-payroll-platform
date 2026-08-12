import React, { useState } from "react";
import { createEmployee, updateEmployee, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, DEPARTMENTS } from "../../../service/payrollService";

// Matches backend/app/modules/payroll/employee_validation.py exactly — these
// are the six jurisdictions get_employee_validation_strategy() dispatches
// on. Regex/required-field enforcement lives server-side (single source of
// truth); this form only needs labels/choices to render the right inputs
// and surface the backend's error message on failure.
const COUNTRIES = [
  { code: "IN", name: "India" },
  { code: "US", name: "United States" },
  { code: "UK", name: "United Kingdom" },
  { code: "AU", name: "Australia" },
  { code: "CA", name: "Canada" },
  { code: "DE", name: "Germany" },
];

const COUNTRY_FIELD_SPECS = {
  IN: [
    { key: "esi_number", label: "ESI number", type: "text" },
    { key: "tax_regime", label: "Tax regime", type: "select", choices: ["Old", "New"] },
  ],
  US: [
    { key: "ssn", label: "SSN", type: "text", placeholder: "123-45-6789" },
    { key: "flsa_status", label: "FLSA status", type: "select", choices: ["Exempt", "Non-Exempt"] },
    { key: "w4_filing_status", label: "W-4 filing status", type: "select", choices: ["Single", "Married Filing Jointly", "Married Filing Separately", "Head of Household"] },
    { key: "aba_routing_number", label: "ABA routing number", type: "text", placeholder: "9 digits" },
    { key: "state_tax_jurisdiction", label: "State tax jurisdiction", type: "text", placeholder: "e.g. CA" },
  ],
  UK: [
    { key: "nino", label: "NINO", type: "text", placeholder: "QQ123456C" },
    { key: "paye_tax_code", label: "PAYE tax code", type: "text", placeholder: "1257L" },
    { key: "student_loan_plan", label: "Student loan plan", type: "select", choices: ["None", "Plan 1", "Plan 2", "Plan 4", "Postgraduate"] },
    { key: "auto_enrolment_pension", label: "Auto-enrolment pension", type: "select", choices: ["true", "false"] },
    { key: "sort_code", label: "Bank sort code", type: "text", placeholder: "6 digits" },
  ],
  AU: [
    { key: "tfn", label: "TFN", type: "text", placeholder: "8-9 digits" },
    { key: "help_stsl_debt", label: "HELP/STSL debt", type: "select", choices: ["true", "false"] },
    { key: "super_fund_usi", label: "Super fund USI", type: "text" },
    { key: "super_member_number", label: "Super member number", type: "text" },
    { key: "bsb_code", label: "BSB code", type: "text", placeholder: "6 digits" },
  ],
  CA: [
    { key: "sin", label: "SIN", type: "text", placeholder: "9 digits" },
    { key: "td1_claim_amount", label: "TD1 claim amount", type: "text" },
    { key: "province", label: "Province of employment", type: "select", choices: ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"] },
    { key: "transit_number", label: "Bank transit number", type: "text", placeholder: "5 digits" },
    { key: "financial_institution_number", label: "Financial institution number", type: "text", placeholder: "3 digits" },
  ],
  DE: [
    { key: "steuer_id", label: "Steuer-ID", type: "text", placeholder: "11 digits" },
    { key: "rv_nummer", label: "RV-Nummer", type: "text", placeholder: "12 characters" },
    { key: "steuerklasse", label: "Steuerklasse", type: "select", choices: ["I", "II", "III", "IV", "V", "VI"] },
    { key: "krankenkasse", label: "Krankenkasse", type: "text" },
    { key: "iban", label: "IBAN", type: "text", placeholder: "DE + 20 digits" },
    { key: "bic", label: "BIC", type: "text" },
  ],
};

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
  basic: "",
  hra: "",
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
          <Field label="Country / jurisdiction">
            <select className={selectClass} value={form.countryCode} onChange={(e) => handleCountryChange(e.target.value)}>
              {COUNTRIES.map((c) => (
                <option key={c.code} value={c.code}>{c.name}</option>
              ))}
            </select>
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
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Bank details</h3>
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

      <div className="border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
          Statutory details &mdash; {COUNTRIES.find((c) => c.code === form.countryCode)?.name}
        </h3>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {form.countryCode === "IN" && (
            <>
              <Field label="PAN number" error={errors.panNumber}>
                <input className={`${inputClass} ${errors.panNumber ? "border-[#FF6E86] focus:border-[#FF6E86] focus:ring-[#FF6E86]/20" : ""}`} value={form.panNumber} onChange={(e) => update("panNumber", e.target.value.toUpperCase())} />
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
