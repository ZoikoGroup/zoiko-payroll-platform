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
