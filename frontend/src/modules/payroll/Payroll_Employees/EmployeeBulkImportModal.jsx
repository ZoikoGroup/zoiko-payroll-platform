import React, { useRef, useState } from "react";
import { Upload, Download, X, FileSpreadsheet, CheckCircle, AlertCircle } from "lucide-react";
import * as XLSX from "xlsx";
import { bulkCreateEmployees, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, DEPARTMENTS } from "../../../service/payrollService";
import { COUNTRIES, COUNTRY_FIELD_SPECS, COMPLIANCE_SPECS, complianceColumnHeader, validateComplianceFields } from "./countryFieldSpecs";

const COLUMN_MAP = {
  "ID": "_existingId",
  "Employee Name": "name",
  "Email": "email",
  "Phone": "phone",
  "Department": "department",
  "Designation": "designation",
  "Employment Type": "employmentType",
  "Status": "status",
  "Date of Joining (YYYY-MM-DD)": "dateOfJoining",
  "CTC": "ctc",
  "Bank Name": "bankName",
  "Bank Account Number": "bankAccountNumber",
  "Country": "countryCode",
  "IFSC Code": "ifscCode",
  "PAN Number": "panNumber",
  "UAN": "uan",
};

const HEADER_ALIASES = {
  "name": "name",
  "full name": "name",
  "employee": "name",
  "date of joining": "dateOfJoining",
  "doj": "dateOfJoining",
  "joining date": "dateOfJoining",
  "bank name": "bankName",
  "bank": "bankName",
  "bank a/c number": "bankAccountNumber",
  "bank account no": "bankAccountNumber",
  "bank a/c no": "bankAccountNumber",
  "account number": "bankAccountNumber",
  "pan": "panNumber",
  "ifsc": "ifscCode",
  "uan number": "uan",
  "country code": "countryCode",
  "jurisdiction": "countryCode",
  "emp id": "_existingId",
  "emp no": "_existingId",
  "emp #": "_existingId",
  "employee id": "_existingId",
  "employee code": "_existingId",
};

// The template carries the org's own jurisdiction statutory columns only —
// no cross-country noise. The parser still recognises every country's
// headers (COMPLIANCE_HEADER_LOOKUP) so a hand-edited mixed sheet keeps
// working for rows whose Country differs from the org's default.
//
// IFSC/PAN/UAN are India's dedicated columns, so they are dropped from the
// template whenever the org's jurisdiction is not India.
const IN_DEDICATED_HEADERS = ["IFSC Code", "PAN Number", "UAN"];
const BASE_TEMPLATE_HEADERS = Object.keys(COLUMN_MAP)
  .filter((h) => h !== "ID")
  .filter((h) => !IN_DEDICATED_HEADERS.includes(h));

// Sample values per statutory field, so each jurisdiction's template shows
// exactly how its own columns are meant to be filled.
const COMPLIANCE_SAMPLE_VALUES = {
  esi_number: "1234567890",
  tax_regime: "New",
  ssn: "123-45-6789",
  flsa_status: "Exempt",
  w4_filing_status: "Single",
  aba_routing_number: "123456789",
  state_tax_jurisdiction: "CA",
  nino: "AB123456C",
  paye_tax_code: "1257L",
  student_loan_plan: "Plan 1",
  auto_enrolment_pension: "true",
  sort_code: "12-34-56",
  tfn: "123456789",
  help_stsl_debt: "false",
  super_fund_usi: "123456789012",
  super_member_number: "12345",
  bsb_code: "123-456",
  sin: "123-456-789",
  td1_claim_amount: "15000",
  province: "ON",
  transit_number: "12345",
  financial_institution_number: "001",
  steuer_id: "12345678901",
  rv_nummer: "12345678A123",
  steuerklasse: "I",
  krankenkasse: "AOK",
  iban: "DE12345678901234567890",
  bic: "AARGDEFF",
};

function templateHeadersFor(countryCode) {
  const base =
    countryCode === "IN"
      ? [...BASE_TEMPLATE_HEADERS, ...IN_DEDICATED_HEADERS]
      : BASE_TEMPLATE_HEADERS;
  const jurisdiction = (COUNTRY_FIELD_SPECS[countryCode] || []).map((spec) => ({
    ...spec,
    country: countryCode,
  }));
  return [...base, ...jurisdiction.map(complianceColumnHeader)];
}

function sampleRowFor(countryCode) {
  const row = {
    "Employee Name": "Asha Rao",
    "Email": "asha.rao@example.com",
    "Phone": "9876543210",
    "Department": DEPARTMENTS[0],
    "Designation": "Software Engineer",
    "Employment Type": EMPLOYMENT_TYPES[0],
    "Status": "Active",
    "Date of Joining (YYYY-MM-DD)": "2026-01-15",
    "CTC": 1200000,
    "Bank Name": "HDFC Bank",
    "Bank Account Number": "123456789012",
    "Country": countryCode,
  };
  if (countryCode === "IN") {
    row["IFSC Code"] = "HDFC0001234";
    row["PAN Number"] = "ABCDE1234F";
    row["UAN"] = "101234567890";
  }
  for (const spec of COUNTRY_FIELD_SPECS[countryCode] || []) {
    const sample = COMPLIANCE_SAMPLE_VALUES[spec.key];
    if (sample) row[complianceColumnHeader(spec)] = sample;
  }
  return row;
}

function downloadTemplate(defaultCountryCode) {
  const countryCode = normalizeCountryCode(defaultCountryCode) || "IN";
  const headers = templateHeadersFor(countryCode);
  const ws = XLSX.utils.json_to_sheet([sampleRowFor(countryCode)], { header: headers });
  ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 18) }));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Employees");
  XLSX.writeFile(wb, `employee_bulk_import_template_${countryCode}.xlsx`);
}

function normalizeHeader(header) {
  return String(header || "")
    .replace(/\(.*?\)/g, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

const NORMALIZED_FIELD_LOOKUP = (() => {
  const lookup = {};
  for (const [header, field] of Object.entries(COLUMN_MAP)) {
    lookup[normalizeHeader(header)] = field;
  }
  for (const [header, field] of Object.entries(HEADER_ALIASES)) {
    lookup[normalizeHeader(header)] = field;
  }
  return lookup;
})();

// normalizeHeader() strips the "(CC)" suffix, so this keys purely on the
// field's label — safe because no two jurisdictions in countryFieldSpecs.js
// reuse the same label.
const COMPLIANCE_HEADER_LOOKUP = (() => {
  const lookup = {};
  for (const spec of COMPLIANCE_SPECS) {
    lookup[normalizeHeader(spec.label)] = spec;
  }
  return lookup;
})();

function normalizeCountryCode(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const match = COUNTRIES.find(
    (c) => c.code.toLowerCase() === raw.toLowerCase() || c.name.toLowerCase() === raw.toLowerCase()
  );
  return match ? match.code : raw.toUpperCase();
}

// Matches an uploaded value against an allowed list case/whitespace-
// insensitively and snaps it to the list's canonical casing (e.g. the
// template's "Full-time" vs. a user typing "Full-Time") — returns the
// original (untouched) value when nothing matches, so validateRow() can
// still flag it and show the user exactly what they entered.
function normalizeAgainstAllowedList(value, allowedList) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const match = allowedList.find((allowed) => allowed.toLowerCase() === raw.toLowerCase());
  return match || raw;
}

function normalizeDate(value) {
  if (!value) return "";
  if (value instanceof Date && !isNaN(value)) {
    return value.toISOString().slice(0, 10);
  }
  const asString = String(value).trim();
  const parsed = new Date(asString);
  if (!isNaN(parsed) && /\d{4}/.test(asString)) {
    return parsed.toISOString().slice(0, 10);
  }
  return asString;
}

function toRowObject(rawRow, defaultCountryCode) {
  const row = {};
  const complianceFields = {};
  for (const [rawHeader, rawValue] of Object.entries(rawRow)) {
    const normalized = normalizeHeader(rawHeader);
    const field = NORMALIZED_FIELD_LOOKUP[normalized];
    if (field) {
      row[field] = rawValue ?? "";
      continue;
    }
    const complianceSpec = COMPLIANCE_HEADER_LOOKUP[normalized];
    if (complianceSpec && String(rawValue ?? "").trim() !== "") {
      complianceFields[complianceSpec.key] = rawValue;
    }
  }
  for (const field of Object.values(COLUMN_MAP)) {
    if (!(field in row)) row[field] = "";
  }

  row.dateOfJoining = normalizeDate(row.dateOfJoining);
  // Department is free text — the uploaded value is used as-is (no whitelist).
  row.department = row.department || DEPARTMENTS[0];
  row.employmentType = normalizeAgainstAllowedList(row.employmentType, EMPLOYMENT_TYPES) || EMPLOYMENT_TYPES[0];
  row.status = normalizeAgainstAllowedList(row.status, EMPLOYEE_STATUSES) || "Active";
  row.countryCode = normalizeCountryCode(row.countryCode) || defaultCountryCode || "IN";
  row.bankName = row.bankName ? String(row.bankName).trim() : "";
  row.bankAccountNumber = row.bankAccountNumber ? String(row.bankAccountNumber).trim() : "";
  row.ctc = row.ctc === "" ? "" : Number(row.ctc);

  // PAN/IFSC/UAN are India's dedicated columns — clearing them for every
  // other jurisdiction mirrors EmployeeForm's handleSubmit so a row that
  // switches country away from India never carries stray Indian identifiers.
  const isIndia = row.countryCode === "IN";
  row.panNumber = isIndia && row.panNumber ? String(row.panNumber).toUpperCase().trim() : "";
  row.ifscCode = isIndia && row.ifscCode ? String(row.ifscCode).toUpperCase().trim() : "";
  row.uan = isIndia ? row.uan : "";
  row.complianceFields = complianceFields;
  return row;
}

function validateRow(row) {
  const errors = [];
  if (!String(row.name || "").trim()) errors.push("Employee name is required");
  if (!String(row.email || "").trim()) errors.push("Email is required");
  else if (!/^\S+@\S+\.\S+$/.test(row.email)) errors.push("Email format looks incorrect");
  if (!String(row.designation || "").trim()) errors.push("Designation is required");
  if (!row.dateOfJoining || isNaN(new Date(row.dateOfJoining))) errors.push("Date of joining is missing or invalid");
  if (!row.ctc || Number(row.ctc) <= 0) errors.push("CTC must be a positive number");
  if (!COUNTRIES.some((c) => c.code === row.countryCode)) {
    errors.push(`Country "${row.countryCode || "(blank)"}" is not valid — must be exactly one of: ${COUNTRIES.map((c) => c.code).join(", ")}`);
  }
  if (row.countryCode === "IN" && row.panNumber && !/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(row.panNumber)) {
    errors.push("PAN format looks incorrect (e.g. ABCDE1234F)");
  }
  if (!EMPLOYMENT_TYPES.includes(row.employmentType)) {
    errors.push(`Employment type "${row.employmentType || "(blank)"}" is not valid — must be exactly one of: ${EMPLOYMENT_TYPES.join(", ")}`);
  }
  if (!EMPLOYEE_STATUSES.includes(row.status)) {
    errors.push(`Status "${row.status || "(blank)"}" is not valid — must be exactly one of: ${EMPLOYEE_STATUSES.join(", ")}`);
  }
  // Jurisdiction-specific compliance fields (SSN, NINO, IBAN, sort code,
  // student loan plan, etc.) — mirrored here by countryFieldSpecs.js's
  // validateComplianceFields() from employee_validation.py so the preview
  // shows the exact causes before upload; the server re-validates anyway.
  errors.push(...validateComplianceFields(row.countryCode, row.complianceFields));
  return errors;
}

export default function EmployeeBulkImportModal({ onClose, onImported, defaultCountryCode }) {
  const fileInputRef = useRef(null);
  const [fileName, setFileName] = useState("");
  const [parsedRows, setParsedRows] = useState([]);
  const [parseError, setParseError] = useState("");
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState(null);

  const validCount = parsedRows.filter((r) => r.errors.length === 0 && !r.row._existingId).length;
  const existingCount = parsedRows.filter((r) => r.row._existingId).length;
  const invalidCount = parsedRows.length - validCount - existingCount;

  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    setFileName(file.name);
    setParseError("");
    setParsedRows([]);
    setResult(null);

    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const data = new Uint8Array(evt.target.result);
        const workbook = XLSX.read(data, { type: "array", cellDates: true });
        const firstSheetName = workbook.SheetNames[0];
        if (!firstSheetName) throw new Error("The file doesn't contain any sheets.");
        const sheet = workbook.Sheets[firstSheetName];
        const rawRows = XLSX.utils.sheet_to_json(sheet, { defval: "" });

        if (rawRows.length === 0) {
          setParseError("No data rows found. Make sure the first row has headers and there's at least one employee below it.");
          return;
        }

        const rows = rawRows.map((rawRow) => {
          const row = toRowObject(rawRow, defaultCountryCode);
          const errors = row._existingId ? [] : validateRow(row);
          return { row, errors };
        });
        setParsedRows(rows);
      } catch (err) {
        setParseError(err.message || "Could not read this file. Please check it's a valid .xlsx or .csv file.");
      }
    };
    reader.onerror = () => setParseError("Could not read this file. Please try again.");
    reader.readAsArrayBuffer(file);
  }

  async function handleImport() {
    const rowsToImport = parsedRows.filter((r) => r.errors.length === 0 && !r.row._existingId).map((r) => {
      const { _existingId, ...rest } = r.row;
      return rest;
    });
    if (rowsToImport.length === 0) return;

    setImporting(true);
    setParseError("");
    try {
      const payload = rowsToImport.map((row) => ({
        ...row,
        panNumber: row.panNumber || "",
      }));
      const response = await bulkCreateEmployees(payload);
      // response.created is a COUNT; the actual created employee records
      // (needed to add them to the list instantly, without waiting for a
      // refetch) are under response.employees.
      const createdEmployees = response?.employees || [];
      const failed = response?.failed || [];
      setResult({ importedCount: response?.created ?? createdEmployees.length, skippedCount: existingCount, failed });
      if (createdEmployees.length > 0) onImported?.(createdEmployees);
    } catch (err) {
      setParseError(err.message || "Import failed. No employees were added. Please try again.");
    } finally {
      setImporting(false);
    }
  }

  function handleReupload() {
    setFileName("");
    setParsedRows([]);
    setParseError("");
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
      fileInputRef.current.click();
    }
  }

  function reset() {
    setFileName("");
    setParsedRows([]);
    setParseError("");
    setResult(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    const file = e.dataTransfer?.files?.[0];
    if (file) {
      if (fileInputRef.current) {
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInputRef.current.files = dt.files;
      }
      handleFileChange({ target: { files: [file] } });
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#1A1816]/40 backdrop-blur-sm px-4" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto bg-white dark:bg-[#221D1A] rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-[18px] font-extrabold text-[#1A1816] dark:text-[#F0EDE8]">Import employees from Excel</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] p-2 text-[#9E9690] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
          >
            <X size={15} />
          </button>
        </div>

        {result ? (
          <div>
            <div className="flex items-center gap-3 rounded-[12px] bg-[#19C58A]/10 px-4 py-3.5 text-[13px] font-semibold text-[#19C58A] border border-[#19C58A]/20">
              <CheckCircle size={18} />
              {`Successfully imported ${result.importedCount} new employee${result.importedCount === 1 ? "" : "s"}.`}
              {result.skippedCount > 0 && (
                <span className="ml-1.5 text-[#35B6F5]">Skipped {result.skippedCount} existing.</span>
              )}
            </div>

            {result.failed.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-[13px] font-semibold text-[#FF6E86]">
                  <AlertCircle size={14} className="inline mr-1 -mt-0.5" />
                  {result.failed.length} row{result.failed.length === 1 ? "" : "s"} could not be imported:
                </p>
                <div className="max-h-56 overflow-y-auto rounded-[12px] border border-[#FF6E86]/20 bg-[#FF6E86]/10">
                  <table className="w-full text-[13px]">
                    <thead className="sticky top-0 bg-[#FBE3E3] dark:bg-[#3A2A28]">
                      <tr className="text-left text-[12px] uppercase tracking-wide text-[#FF6E86]">
                        <th className="px-4 py-2 font-bold">Row</th>
                        <th className="px-4 py-2 font-bold">Name</th>
                        <th className="px-4 py-2 font-bold">Email</th>
                        <th className="px-4 py-2 font-bold">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.failed.map((f, i) => (
                        <tr key={i} className="border-t border-[#FF6E86]/15 text-[#7A3B42] dark:text-[#F2C9C9]">
                          <td className="px-4 py-2 font-mono text-[12px]">{i + 1}</td>
                          <td className="px-4 py-2">{f.row?.name || "—"}</td>
                          <td className="px-4 py-2">{f.row?.email || "—"}</td>
                          <td className="px-4 py-2">{f.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[12px] text-[#9E9690]">
                  Fix these rows in your sheet and click &quot;Import another file&quot; to re-upload. Rows that were already imported
                  will come back as &quot;already exists&quot; — that&apos;s expected, just leave them in the sheet.
                </p>
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={reset}
                className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
              >
                Import another file
              </button>
              <button
                onClick={onClose}
                className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <>
            <div
              className="border-2 border-dashed border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-8 text-center transition-all duration-200 hover:border-[#19C58A] hover:bg-[#19C58A]/5"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
            >
              <Upload size={36} className="mx-auto mb-3 text-[#19C58A]" />
              <p className="text-[13px] text-[#9E9690] mb-4">
                Upload a spreadsheet with one employee per row. Existing employees (with an ID) are automatically skipped.
              </p>
              <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  onChange={handleFileChange}
                  className="block w-full text-[13px] text-[#9E9690] file:mr-3 file:rounded-[12px] file:border-0 file:bg-[#19C58A] file:px-4 file:py-2 file:text-[13px] file:font-bold file:text-white file:cursor-pointer file:transition-all duration-200 hover:file:bg-[#15B07A] sm:w-auto"
                />
              </div>
              {fileName && (
                <div className="mt-3 inline-flex items-center gap-2 rounded-[10px] bg-[#F8F7F4] dark:bg-[#2A2520] px-3.5 py-2">
                  <FileSpreadsheet size={14} className="text-[#19C58A]" />
                  <span className="text-[13px] text-[#1A1816] dark:text-[#F0EDE8]">{fileName}</span>
                </div>
              )}
              <div className="mt-4 pt-4 border-t border-[#E5E0D9] dark:border-[#38312D]">
                <p className="text-[11px] text-[#9E9690] mb-2">Tip: Use "Export" on the employee list to download all existing employees. Add new rows without IDs, then re-upload — existing rows are auto-skipped. The statutory columns in this template match your organization's jurisdiction ({defaultCountryCode || "IN"}); set the "Country" column per row to place an employee under a different jurisdiction.</p>
                <button
                  type="button"
                  onClick={() => downloadTemplate(defaultCountryCode)}
                  className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#19C58A] hover:text-[#15B07A] transition-colors duration-200"
                >
                  <Download size={14} />
                  Download template
                </button>
              </div>
            </div>

            {parseError && (
              <div className="mt-4 rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">
                {parseError}
              </div>
            )}

            {parsedRows.length > 0 && (
              <div className="mt-5">
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-[13px] text-[#1A1816] dark:text-[#F0EDE8]">
                    <span className="font-bold text-[#19C58A]">{validCount} ready to import</span>
                    {existingCount > 0 && (
                      <span className="ml-2 text-[#9E9690]">· {existingCount} existing (will be skipped)</span>
                    )}
                    {invalidCount > 0 && (
                      <span className="ml-2 text-[#FF6E86]">· {invalidCount} with errors</span>
                    )}
                  </p>
                  <button
                    type="button"
                    onClick={handleReupload}
                    className="text-[13px] font-semibold text-[#19C58A] hover:text-[#15B07A] transition-colors duration-200"
                  >
                    Re-upload
                  </button>
                </div>

                <div className="max-h-72 overflow-auto rounded-[18px] border border-[#E5E0D9] dark:border-[#38312D]">
                  <table className="min-w-full divide-y divide-[#E5E0D9] dark:divide-[#38312D] text-[13px]">
                    <thead className="sticky top-0 bg-[#F8F7F4] dark:bg-[#2A2520]">
                      <tr>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Name</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Email</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Department</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Country</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">CTC</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
                      {parsedRows.map(({ row, errors }, i) => (
                        <tr key={i} className={
                          row._existingId ? "bg-[#35B6F5]/5"
                          : errors.length > 0 ? "bg-[#FF6E86]/5"
                          : "hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-all duration-150"
                        }>
                          <td className="px-3 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8]">
                            {row.name}
                            {row._existingId && (
                              <span className="ml-2 inline-flex items-center rounded-full bg-[#35B6F5]/10 px-2 py-0.5 text-[10px] font-bold text-[#35B6F5]">existing · will be skipped</span>
                            )}
                            {errors.length > 0 && (
                              <ul className="mt-1 space-y-0.5">
                                {errors.map((e, j) => (
                                  <li key={j} className="text-[11px] text-[#FF6E86]">• {e}</li>
                                ))}
                              </ul>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{row.email}</td>
                          <td className="px-3 py-2.5 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{row.department}</td>
                          <td className="px-3 py-2.5 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{row.countryCode}</td>
                          <td className="px-3 py-2.5 text-[13px] text-[#6B6560] dark:text-[#A69B93]">{row.ctc || "—"}</td>
                          <td className="px-3 py-2.5">
                            <span className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${
                              row.status === "Active" ? "bg-[#19C58A]/10 text-[#19C58A]" :
                              row.status === "On Leave" ? "bg-[#F8A60A]/10 text-[#F8A60A]" :
                              "bg-[#FF6E86]/10 text-[#FF6E86]"
                            }`}>
                              {row.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3 border-t border-[#E5E0D9] dark:border-[#38312D] pt-5">
              <button
                onClick={onClose}
                className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={validCount === 0 || importing}
                className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-60 disabled:hover:translate-y-0"
              >
                {importing ? "Importing…" : `Import ${validCount || ""} new employee${validCount === 1 ? "" : "s"}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
