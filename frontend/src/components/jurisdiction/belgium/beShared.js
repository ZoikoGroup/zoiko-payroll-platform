// Belgium (ZP-BE-ENG-001) Super Admin console — UI glue only.
//
// NO content key names and NO vocabulary values live here (or in any BE
// component): groups, labels, kinds, vocabularies, slab specs, earning-class
// treatments and reference notes come from
// GET /api/super-admin/compliance/belgium/packs/{id}/configuration.
// The frontend never computes a payroll amount; it renders what the backend
// returns. scripts/be-console-ui-validation.mjs enforces this.

import { getBeConfiguration } from "../../../service/superAdminService";

export const EDITABLE_PACK_STATUSES = ["Draft", "In Review", "QA", "Approved"];
export const isEditablePack = (pack) => Boolean(pack && EDITABLE_PACK_STATUSES.includes(pack.status));
export const isDraftPack = (pack) => Boolean(pack && pack.status === "Draft");

// Which catalogue groups (backend group ids) each console tab shows.
export const TAB_GROUPS = {
  policy: ["policy"],
  withholding: ["withholding"],
  onssEmployee: ["onss_employee"],
  onssEmployer: ["onss_employer", "reductions"],
  holidayPay: ["holiday"],
  wagesTime: ["wages", "working_time"],
  absence: ["absence"],
  publicHolidays: ["holidays"],
  earningClass: ["earning_class"],
};

export const PENDING_MARK = "[PENDING G1]";
export const cleanLabel = (label) => String(label || "").replace(PENDING_MARK, "").trim();

export function loadConfiguration(pack) {
  return pack ? getBeConfiguration(pack.id) : Promise.resolve(null);
}

// Value of a scalar row exactly as stored (no arithmetic; the backend holds the value).
export function displayValue(row) {
  if (!row) return null;
  if (row.employeeRatePct != null || row.employerRatePct != null) {
    const parts = [];
    if (row.employeeRatePct != null) parts.push(`Employee ${row.employeeRatePct}%`);
    if (row.employerRatePct != null) parts.push(`Employer ${row.employerRatePct}%`);
    return parts.join(" / ");
  }
  if (row.flatAmount != null) return String(row.flatAmount);
  return row.textValue || null;
}

export function slabRowsFor(config, key) {
  const spec = config?.slabSpecs?.[key];
  return spec ? config?.slabRows?.[spec.ruleType] || [] : [];
}

// Release gates as the backend reports them ({ G1: "MET" | "NOT MET", ... }).
export function gateCounts(summary) {
  const states = Object.values(summary?.gates || {});
  return { met: states.filter((s) => s === "MET").length, total: states.length };
}

// The backend engine status code shown in words (NOT_CERTIFIED -> Not certified).
export function engineStatusLabel(status) {
  const words = String(status || "unknown").replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Overview cards from the Belgium configuration (GET .../configuration):
// catalogue rows by group, slab rows by key — each with how many still await
// a second Super Admin's signature. Counts only; no value is read or shown.
const EMPLOYEE_GROUPS = TAB_GROUPS.onssEmployee;
const EMPLOYER_GROUPS = TAB_GROUPS.onssEmployer;
const tally = (rows) => ({ rows: rows.length, pending: rows.filter((r) => !r.signed).length });

export function beOverviewCounts(config) {
  const groups = config?.groups || {};
  const rowsOf = (names) => names.flatMap((g) => groups[g]?.rows || []);
  const order = config?.groupOrder || Object.keys(groups);
  const parameterGroups = order.filter((g) => !EMPLOYEE_GROUPS.includes(g) && !EMPLOYER_GROUPS.includes(g));
  const slabKeys = Object.keys(config?.slabSpecs || {});
  const slabRows = slabKeys.flatMap((key) => slabRowsFor(config, key));
  return {
    employee: tally(rowsOf(EMPLOYEE_GROUPS)),
    employer: tally(rowsOf(EMPLOYER_GROUPS)),
    parameters: tally(rowsOf(parameterGroups)),
    slabs: { ...tally(slabRows), keys: slabKeys.length,
      keysWithoutRows: slabKeys.filter((key) => slabRowsFor(config, key).length === 0).length },
  };
}

// "12 rows · 3 pending signature" / "12 rows · all signed" / "no rows yet".
export function rowsHint({ rows, pending }) {
  if (!rows) return "no rows yet";
  return `${rows} row${rows === 1 ? "" : "s"} · ${pending ? `${pending} pending signature` : "all signed"}`;
}
