import React, { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Upload, Download, X, FileSpreadsheet, CheckCircle, AlertCircle } from "lucide-react";
import * as XLSX from "xlsx";
import { bulkCreateEmployees, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES, DEPARTMENTS } from "../../../service/payrollService";
import { COUNTRIES, COUNTRY_FIELD_SPECS, COMPLIANCE_SPECS, DUPLICATE_ID_FIELDS, complianceColumnHeader, normalizeComplianceFields, validateComplianceFields } from "./countryFieldSpecs";
import { useEntitledCountries, toEmployeeCountryCode } from "../EntitledCountriesContext";
import { getCurrencyForJurisdiction } from "../../../utils/currency";
import PlanLimitMessage, { isPlanLimitError, PLAN_SELECTION_ROUTE } from "../../../components/PlanLimitMessage";

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

// Employees are imported one country at a time: the admin picks the
// country, downloads that country's template (its own statutory columns
// only), and every row in the file is an employee of that country. The
// template has no Country column — the import itself names the country —
// but a Country column in an older or exported sheet is still read, and a
// row for another country is flagged instead of imported.
//
// IFSC/PAN/UAN are India's dedicated columns, so only India's template has them.
const IN_DEDICATED_HEADERS = ["IFSC Code", "PAN Number", "UAN"];
const BASE_TEMPLATE_HEADERS = Object.keys(COLUMN_MAP)
  .filter((h) => h !== "ID" && h !== "Country")
  .filter((h) => !IN_DEDICATED_HEADERS.includes(h));
const REQUIRED_BASE_HEADERS = ["Employee Name", "Email", "Designation", "Date of Joining (YYYY-MM-DD)", "CTC"];

// A sample employee per country, so each template reads like that
// country's own payroll (salary in its currency, a local bank).
const COUNTRY_SAMPLES = {
  IN: { name: "Asha Rao", email: "asha.rao@example.com", phone: "9876543210", bank: "HDFC Bank", account: "123456789012", ctc: 1200000 },
  US: { name: "Jordan Lee", email: "jordan.lee@example.com", phone: "4155550123", bank: "Chase", account: "000123456789", ctc: 85000 },
  UK: { name: "Oliver Smith", email: "oliver.smith@example.com", phone: "07700900123", bank: "Barclays", account: "12345678", ctc: 45000 },
};
const GENERIC_SAMPLE = { name: "Alex Morgan", email: "alex.morgan@example.com", phone: "5550123", bank: "Example Bank", account: "12345678", ctc: 60000 };

function countryName(countryCode) {
  return COUNTRIES.find((c) => c.code === countryCode)?.name || countryCode;
}

function currencyCode(countryCode) {
  return getCurrencyForJurisdiction(countryCode)?.code || "";
}

// "CTC (annual, GBP)" — the parser strips the parenthetical, so it still maps to CTC.
function ctcHeader(countryCode) {
  const currency = currencyCode(countryCode);
  return currency ? `CTC (annual, ${currency})` : "CTC";
}

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
  tamis_tin: "123456789",
  nis_number: "A1234567",
  nib_member_number: "A1234567",
  cedula: "001-1234567-8",
  gra_tin: "1234567",
  trn: "123456789",
  nib_number: "A1234567",
  bir_file_number: "123456789",
  nibtt_number: "A1234567",
};

function countrySpecs(countryCode) {
  return (COUNTRY_FIELD_SPECS[countryCode] || []).map((spec) => ({ ...spec, country: countryCode }));
}

function templateHeadersFor(countryCode) {
  const base = (countryCode === "IN" ? [...BASE_TEMPLATE_HEADERS, ...IN_DEDICATED_HEADERS] : BASE_TEMPLATE_HEADERS)
    .map((h) => (h === "CTC" ? ctcHeader(countryCode) : h));
  return [...base, ...countrySpecs(countryCode).map(complianceColumnHeader)];
}

function sampleRowFor(countryCode) {
  const sample = COUNTRY_SAMPLES[countryCode] || GENERIC_SAMPLE;
  const row = {
    "Employee Name": sample.name,
    "Email": sample.email,
    "Phone": sample.phone,
    "Department": DEPARTMENTS[0],
    "Designation": "Software Engineer",
    "Employment Type": EMPLOYMENT_TYPES[0],
    "Status": "Active",
    "Date of Joining (YYYY-MM-DD)": "2026-01-15",
    [ctcHeader(countryCode)]: sample.ctc,
    "Bank Name": sample.bank,
    "Bank Account Number": sample.account,
  };
  if (countryCode === "IN") {
    row["IFSC Code"] = "HDFC0001234";
    row["PAN Number"] = "ABCDE1234F";
    row["UAN"] = "101234567890";
  }
  for (const spec of countrySpecs(countryCode)) {
    const sample = COMPLIANCE_SAMPLE_VALUES[spec.key];
    if (sample) row[complianceColumnHeader(spec)] = sample;
  }
  return row;
}

// One row per template column: whether it's required and what it accepts.
function instructionRowsFor(countryCode) {
  const rows = templateHeadersFor(countryCode).map((header) => {
    const base = header.startsWith("CTC") ? "CTC" : header;
    const spec = countrySpecs(countryCode).find((sp) => complianceColumnHeader(sp) === header);
    let accepts = "";
    if (base === "CTC") accepts = `Annual cost to company in ${currencyCode(countryCode) || "local currency"}`;
    else if (base === "Employment Type") accepts = EMPLOYMENT_TYPES.join(", ");
    else if (base === "Status") accepts = EMPLOYEE_STATUSES.join(", ");
    else if (base === "Date of Joining (YYYY-MM-DD)") accepts = "Date, e.g. 2026-01-15";
    else if (spec?.choices && spec.choices.every((c) => ["true", "false"].includes(c.toLowerCase()))) accepts = "Yes or No";
    else if (spec?.choices) accepts = `${[...new Set(spec.choices)].join(", ")} (any capitalisation)`;
    else if (spec?.type === "date") accepts = "Date, e.g. 2026-01-15";
    else if (spec?.placeholder) accepts = `e.g. ${spec.placeholder}`;
    else if (spec?.showWhen) accepts = "Only when it applies (see column name)";
    const required = REQUIRED_BASE_HEADERS.includes(base) || spec?.required;
    return { Column: header, Required: required ? "Yes" : "No", "Accepted values": accepts };
  });
  return [
    { Column: `Every employee in this file is paid in ${countryName(countryCode)} (${countryCode}).`, Required: "", "Accepted values": "" },
    { Column: "Import other countries' employees separately, each with its own template.", Required: "", "Accepted values": "" },
    { Column: "Leave a column that doesn't apply blank (N/A is fine too).", Required: "", "Accepted values": "" },
    { Column: "", Required: "", "Accepted values": "" },
    ...rows,
  ];
}

// The template for one country: its own statutory columns, a sample
// employee from that country, and an Instructions sheet.
function downloadTemplate(countryCode) {
  const headers = templateHeadersFor(countryCode);
  const ws = XLSX.utils.json_to_sheet([sampleRowFor(countryCode)], { header: headers });
  ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 18) }));
  const help = XLSX.utils.json_to_sheet(instructionRowsFor(countryCode), { header: ["Column", "Required", "Accepted values"] });
  help["!cols"] = [{ wch: 60 }, { wch: 10 }, { wch: 70 }];
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, `${countryCode} employees`);
  XLSX.utils.book_append_sheet(wb, help, "Instructions");
  XLSX.writeFile(wb, `employee_import_template_${countryCode}.xlsx`);
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
  // "GB" (ISO) is spelled "UK" on employee records.
  return match ? match.code : toEmployeeCountryCode(raw);
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

function toRowObject(rawRow, importCountry) {
  const row = {};
  const filledSpecs = [];
  for (const [rawHeader, rawValue] of Object.entries(rawRow)) {
    const normalized = normalizeHeader(rawHeader);
    const field = NORMALIZED_FIELD_LOOKUP[normalized];
    if (field) {
      row[field] = rawValue ?? "";
      continue;
    }
    const complianceSpec = COMPLIANCE_HEADER_LOOKUP[normalized];
    if (complianceSpec && String(rawValue ?? "").trim() !== "") {
      filledSpecs.push([complianceSpec, rawValue]);
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
  // A blank Country is the import's country; one naming another country is
  // flagged by validateRow (each country is imported separately).
  row.countryCode = normalizeCountryCode(row.countryCode) || importCountry || "";
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
  // Statutory columns belong to one country; another country's filled-in
  // columns mean the row (or file) is for that country, not this import.
  row.complianceFields = {};
  row.foreignColumns = [];
  for (const [spec, value] of filledSpecs) {
    if (spec.country === row.countryCode) row.complianceFields[spec.key] = value;
    else row.foreignColumns.push(spec);
  }
  // "No" -> "false", "Non-exempt" -> "Non-Exempt", "N/A" -> dropped, …
  row.complianceFields = normalizeComplianceFields(row.countryCode, row.complianceFields);
  return row;
}

// True when the entitlement list has loaded and the row's (otherwise valid)
// country isn't one of the org's ACTIVE entitled countries — the server
// would reject it with a plan-limit block, so it is flagged before upload.
function isRowCountryNotEntitled(row, entitlement) {
  return (
    entitlement.loaded &&
    COUNTRIES.some((c) => c.code === row.countryCode) &&
    !entitlement.isEntitled(row.countryCode)
  );
}

function validateRow(row, entitlement, importCountry) {
  const errors = [];
  if (importCountry && row.countryCode && row.countryCode !== importCountry) {
    errors.push(
      `This row is for ${countryName(row.countryCode)} (${row.countryCode}), but you are importing ${countryName(importCountry)} employees — import it separately with the ${row.countryCode} template`
    );
    return errors;
  }
  if (row.foreignColumns?.length > 0) {
    const other = row.foreignColumns[0].country;
    errors.push(
      `Has ${countryName(other)} columns filled in (${row.foreignColumns.map((sp) => sp.label).slice(0, 3).join(", ")}) — this looks like a ${other} employee. Use the ${countryName(importCountry)} template, or import ${other} employees separately`
    );
    return errors;
  }
  if (!String(row.name || "").trim()) errors.push("Employee name is required");
  if (!String(row.email || "").trim()) errors.push("Email is required");
  else if (!/^\S+@\S+\.\S+$/.test(row.email)) errors.push("Email format looks incorrect");
  if (!String(row.designation || "").trim()) errors.push("Designation is required");
  if (!row.dateOfJoining || isNaN(new Date(row.dateOfJoining))) errors.push("Date of joining is missing or invalid");
  if (!row.ctc || Number(row.ctc) <= 0) errors.push("CTC must be a positive number");
  if (!row.countryCode) {
    errors.push("Country is required — it decides which country's payroll engine calculates this employee");
  } else if (!COUNTRIES.some((c) => c.code === row.countryCode)) {
    errors.push(`Country "${row.countryCode}" has no payroll engine — must be exactly one of: ${COUNTRIES.map((c) => c.code).join(", ")}`);
  } else if (isRowCountryNotEntitled(row, entitlement)) {
    errors.push(
      entitlement.entitledEmployeeCodes.length > 0
        ? `Country "${row.countryCode}" is not included in your plan — your organization can add employees in: ${entitlement.entitledEmployeeCodes.join(", ")}`
        : `Country "${row.countryCode}" is not included in your plan — your organization has no active countries yet`
    );
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

// Each employee's email and national ID must be unique: a second row with the
// same value would be refused by the server ("already exists") after the
// first one is created. Flag it in the preview instead, naming the row it
// repeats. Emails already on file are flagged too. (National IDs come back
// masked from the API, so only the server can check those against existing
// employees.)
function flagDuplicates(rows, existingEmails) {
  const idKey = (v) => String(v ?? "").replace(/[\s-]/g, "").toUpperCase();
  const seenEmail = new Map();
  const seenId = new Map();
  rows.forEach(({ row, errors }, i) => {
    if (row._existingId) return;
    const rowLabel = `row ${i + 2}${row.name ? ` (${row.name})` : ""}`;
    const email = String(row.email || "").trim().toLowerCase();
    if (email) {
      if (seenEmail.has(email)) errors.push(`Same email as ${seenEmail.get(email)} — every employee needs their own email`);
      else if (existingEmails.has(email)) errors.push(`An employee with this email already exists`);
      else seenEmail.set(email, rowLabel);
    }
    const idField = row.countryCode === "IN" ? "panNumber" : DUPLICATE_ID_FIELDS[row.countryCode];
    const idValue = idField === "panNumber" ? row.panNumber : row.complianceFields?.[idField];
    const key = idKey(idValue);
    if (idField && key && !key.includes("*")) {
      const label = COUNTRY_FIELD_SPECS[row.countryCode]?.find((sp) => sp.key === idField)?.label || (idField === "panNumber" ? "PAN" : idField);
      const scoped = `${row.countryCode}:${key}`;
      if (seenId.has(scoped)) {
        errors.push(`Same ${label} as ${seenId.get(scoped)} — each employee needs their own ${label} (a placeholder like ${idValue} can only be used once)`);
      } else {
        seenId.set(scoped, rowLabel);
      }
    }
  });
  return rows;
}

export default function EmployeeBulkImportModal({ onClose, onImported, defaultCountryCode, existingEmployees = [] }) {
  const entitlement = useEntitledCountries();
  const primaryCountry = entitlement.primaryEmployeeCode || toEmployeeCountryCode(defaultCountryCode) || "";
  // The countries this org can import into (its ACTIVE plan countries),
  // primary first; before the list loads, just the primary country.
  const countryChoices = (() => {
    const codes = entitlement.loaded && entitlement.entitledEmployeeCodes.length > 0
      ? entitlement.entitledEmployeeCodes
      : [primaryCountry].filter(Boolean);
    const known = codes.filter((code) => COUNTRIES.some((c) => c.code === code));
    return [...new Set(known)].sort((a, b) => (a === primaryCountry ? -1 : b === primaryCountry ? 1 : 0));
  })();
  const [chosenCountry, setChosenCountry] = useState("");
  const importCountry = countryChoices.includes(chosenCountry) ? chosenCountry : countryChoices[0] || "";
  const importCountryName = countryName(importCountry);
  const fileInputRef = useRef(null);
  const [fileName, setFileName] = useState("");
  const [parsedRows, setParsedRows] = useState([]);
  const [parseError, setParseError] = useState("");
  const [planError, setPlanError] = useState(null);
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
          const row = toRowObject(rawRow, importCountry);
          const errors = row._existingId ? [] : validateRow(row, entitlement, importCountry);
          return { row, errors };
        });
        const existingEmails = new Set(existingEmployees.map((e) => String(e.email || "").trim().toLowerCase()).filter(Boolean));
        setParsedRows(flagDuplicates(rows, existingEmails));
      } catch (err) {
        setParseError(err.message || "Could not read this file. Please check it's a valid .xlsx or .csv file.");
      }
    };
    reader.onerror = () => setParseError("Could not read this file. Please try again.");
    reader.readAsArrayBuffer(file);
  }

  async function handleImport() {
    const rowsToImport = parsedRows.filter((r) => r.errors.length === 0 && !r.row._existingId).map((r) => {
      // eslint-disable-next-line no-unused-vars
      const { _existingId, foreignColumns, ...rest } = r.row;
      return rest;
    });
    if (rowsToImport.length === 0) return;

    setImporting(true);
    setParseError("");
    setPlanError(null);
    try {
      const payload = rowsToImport.map((row) => ({
        ...row,
        panNumber: row.panNumber || "",
      }));
      const response = await bulkCreateEmployees(payload, importCountry);
      // response.created is a COUNT; the actual created employee records
      // (needed to add them to the list instantly, without waiting for a
      // refetch) are under response.employees.
      const createdEmployees = response?.employees || [];
      const failed = response?.failed || [];
      setResult({ importedCount: response?.created ?? createdEmployees.length, skippedCount: existingCount, failed });
      if (createdEmployees.length > 0) onImported?.(createdEmployees);
    } catch (err) {
      // No plan / plan-limit refusals get the "Choose a plan" link.
      if (isPlanLimitError(err)) setPlanError(err);
      else setParseError(err.message || "Import failed. No employees were added. Please try again.");
    } finally {
      setImporting(false);
    }
  }

  function handleReupload() {
    setFileName("");
    setParsedRows([]);
    setParseError("");
    setPlanError(null);
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
    setPlanError(null);
    setResult(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // A parsed file belongs to the country it was checked against — switching
  // country asks for the file again.
  function chooseCountry(code) {
    if (code === importCountry) return;
    setChosenCountry(code);
    reset();
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/40 backdrop-blur-sm px-4" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-[18px] font-extrabold text-foreground">Import employees from Excel</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="border border-border bg-surface-muted rounded-[12px] p-2 text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
          >
            <X size={15} />
          </button>
        </div>

        {result ? (
          <div>
            <div className="flex items-center gap-3 rounded-[12px] bg-primary/10 px-4 py-3.5 text-[13px] font-semibold text-primary border border-primary/20">
              <CheckCircle size={18} />
              {`Successfully imported ${result.importedCount} new ${importCountryName} employee${result.importedCount === 1 ? "" : "s"}.`}
              {result.skippedCount > 0 && (
                <span className="ml-1.5 text-info">Skipped {result.skippedCount} existing.</span>
              )}
            </div>

            {result.failed.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-[13px] font-semibold text-error">
                  <AlertCircle size={14} className="inline mr-1 -mt-0.5" />
                  {result.failed.length} row{result.failed.length === 1 ? "" : "s"} could not be imported:
                </p>
                <div className="max-h-56 overflow-y-auto rounded-[12px] border border-error/20 bg-error/10">
                  <table className="w-full text-[13px]">
                    <thead className="sticky top-0 bg-error-light">
                      <tr className="text-left text-[12px] uppercase tracking-wide text-error">
                        <th className="px-4 py-2 font-bold">Row</th>
                        <th className="px-4 py-2 font-bold">Name</th>
                        <th className="px-4 py-2 font-bold">Email</th>
                        <th className="px-4 py-2 font-bold">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.failed.map((f, i) => (
                        <tr key={i} className="border-t border-error/15 text-error text-error">
                          <td className="px-4 py-2 font-mono text-[12px]">{i + 1}</td>
                          <td className="px-4 py-2">{f.row?.name || "—"}</td>
                          <td className="px-4 py-2">{f.row?.email || "—"}</td>
                          <td className="px-4 py-2">
                            {isPlanLimitError(f) ? <PlanLimitMessage compact message={f.reason} trace={f.trace} /> : f.reason}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[12px] text-foreground-muted">
                  Fix these rows in your sheet and click &quot;Import another file&quot; to re-upload. Rows that were already imported
                  will come back as &quot;already exists&quot; — that&apos;s expected, just leave them in the sheet.
                </p>
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={reset}
                className="border border-border bg-surface-muted rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
              >
                Import another file
              </button>
              <button
                onClick={onClose}
                className="bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)]"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="mb-4">
              <label htmlFor="import-country" className="mb-2 block text-[13px] font-bold text-foreground">1. Country template — which country are these employees paid in?</label>
              {countryChoices.length === 0 ? (
                <p className="text-[13px] text-foreground-muted">
                  {entitlement.loaded ? "Your organization has no active countries yet — add one under Compliance → Countries." : "Loading your countries…"}
                </p>
              ) : (
                <select
                  id="import-country"
                  aria-label="Import country"
                  value={importCountry}
                  onChange={(e) => chooseCountry(e.target.value)}
                  className="w-full sm:w-96 rounded-[12px] border border-border bg-surface px-3.5 py-2.5 text-[13px] text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  {countryChoices.map((code) => (
                    <option key={code} value={code}>
                      {countryName(code)} ({code}{currencyCode(code) ? ` · ${currencyCode(code)}` : ""}){code === primaryCountry ? " — primary" : ""}
                    </option>
                  ))}
                </select>
              )}
              <p className="mt-2 text-[12px] text-foreground-muted">
                Only the countries selected in Compliance → Countries are listed. Each country is imported separately with its own template — its payroll engine, statutory fields and currency differ.
              </p>
            </div>

            <div
              className="border-2 border-dashed border-border rounded-[18px] p-8 text-center transition-all duration-200 hover:border-primary hover:bg-primary/5"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
            >
              <Upload size={36} className="mx-auto mb-3 text-primary" />
              <p className="text-[13px] text-foreground-muted mb-4">
                {importCountry
                  ? <>2. Upload your <b className="text-foreground">{importCountryName}</b> employees — one per row. Existing employees (with an ID) are skipped.</>
                  : "Choose a country first."}
              </p>
              <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  disabled={!importCountry}
                  aria-label={`Upload ${importCountryName} employees file`}
                  onChange={handleFileChange}
                  className="block w-full text-[13px] text-foreground-muted file:mr-3 file:rounded-[12px] file:border-0 file:bg-primary file:px-4 file:py-2 file:text-[13px] file:font-bold file:text-white file:cursor-pointer file:transition-all duration-200 hover:file:bg-primary-hover sm:w-auto"
                />
              </div>
              {fileName && (
                <div className="mt-3 inline-flex items-center gap-2 rounded-[10px] bg-surface-muted px-3.5 py-2">
                  <FileSpreadsheet size={14} className="text-primary" />
                  <span className="text-[13px] text-foreground">{fileName}</span>
                </div>
              )}
              <div className="mt-4 pt-4 border-t border-border">
                <p className="text-[11px] text-foreground-muted mb-2">
                  The {importCountryName || "country"} template has {importCountryName || "that country"}&apos;s own statutory columns
                  {currencyCode(importCountry) ? ` and salaries in ${currencyCode(importCountry)}` : ""}; its Instructions sheet lists
                  what each column accepts. Every row is calculated by the {importCountryName || "chosen country"} payroll engine.
                </p>
                <button
                  type="button"
                  disabled={!importCountry}
                  onClick={() => downloadTemplate(importCountry)}
                  className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary hover:text-primary-hover transition-colors duration-200 disabled:opacity-50"
                >
                  <Download size={14} />
                  Download {importCountryName ? `${importCountryName} (${importCountry})` : ""} template
                </button>
              </div>
            </div>

            {planError && <PlanLimitMessage error={planError} className="mt-4" />}

            {parseError && (
              <div className="mt-4 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">
                {parseError}
              </div>
            )}

            {parsedRows.length > 0 && (
              <div className="mt-5">
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-[13px] text-foreground">
                    <span className="font-bold text-primary">{validCount} ready to import</span>
                    {existingCount > 0 && (
                      <span className="ml-2 text-foreground-muted">· {existingCount} existing (will be skipped)</span>
                    )}
                    {invalidCount > 0 && (
                      <span className="ml-2 text-error">· {invalidCount} with errors</span>
                    )}
                  </p>
                  <button
                    type="button"
                    onClick={handleReupload}
                    className="text-[13px] font-semibold text-primary hover:text-primary-hover transition-colors duration-200"
                  >
                    Re-upload
                  </button>
                </div>

                <div className="max-h-72 overflow-auto rounded-[18px] border border-border">
                  <table className="min-w-full divide-y divide-border text-[13px]">
                    <thead className="sticky top-0 bg-surface-muted">
                      <tr>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Name</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Email</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Department</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Country (payroll engine)</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">CTC</th>
                        <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {parsedRows.map(({ row, errors }, i) => (
                        <tr key={i} className={
                          row._existingId ? "bg-info/5"
                          : errors.length > 0 ? "bg-error/5"
                          : "hover:bg-background dark:hover:bg-surface-muted transition-all duration-150"
                        }>
                          <td className="px-3 py-2.5 text-[13px] text-foreground">
                            {row.name}
                            {row._existingId && (
                              <span className="ml-2 inline-flex items-center rounded-full bg-info/10 px-2 py-0.5 text-[10px] font-bold text-info">existing · will be skipped</span>
                            )}
                            {errors.length > 0 && (
                              <ul className="mt-1 space-y-0.5">
                                {errors.map((e, j) => (
                                  <li key={j} className="text-[11px] text-error">• {e}</li>
                                ))}
                              </ul>
                            )}
                            {!row._existingId && isRowCountryNotEntitled(row, entitlement) && (
                              <Link to={PLAN_SELECTION_ROUTE} className="mt-0.5 inline-block text-[11px] font-bold text-primary hover:text-primary-hover hover:underline">
                                Upgrade plan to add this country →
                              </Link>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] text-foreground-muted">{row.email}</td>
                          <td className="px-3 py-2.5 text-[13px] text-foreground-muted">{row.department}</td>
                          <td className="px-3 py-2.5 text-[13px] text-foreground-muted">
                            {row.countryCode ? (
                              <span title="Payroll engine this employee will be calculated with">
                                {COUNTRIES.find((c) => c.code === row.countryCode)?.name || row.countryCode}
                                <span className="ml-1 text-[11px] opacity-70">({row.countryCode})</span>
                              </span>
                            ) : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] text-foreground-muted">{row.ctc || "—"}</td>
                          <td className="px-3 py-2.5">
                            <span className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${
                              row.status === "Active" ? "bg-primary/10 text-primary" :
                              row.status === "On Leave" ? "bg-warning/10 text-warning" :
                              "bg-error/10 text-error"
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

            <div className="mt-6 flex justify-end gap-3 border-t border-border pt-5">
              <button
                onClick={onClose}
                className="border border-border bg-surface-muted rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={validCount === 0 || importing}
                className="bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-60 disabled:hover:translate-y-0"
              >
                {importing ? "Importing…" : `Import ${validCount || ""} ${importCountryName} employee${validCount === 1 ? "" : "s"}`.replace(/\s+/g, " ")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
