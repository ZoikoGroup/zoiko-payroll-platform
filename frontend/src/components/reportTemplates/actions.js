// Approve / Delete availability and the Overview's required metadata for a
// report template. Plain JS (no JSX) so scripts/report-template-ui-validation.mjs
// can evaluate it under Node. The server still enforces every rule; these only
// decide what the UI offers.

// backend service._EDITABLE_TEMPLATE_STATUSES — the only statuses
// set_report_template_approver accepts (a released version's approval is its
// release evidence and is never replaced) and hard_delete_report_template allows.
export const PRE_RELEASE_STATUSES = ["Draft", "Review", "Approved"];

// Approve applies only before release (re-approving an Approved version is allowed).
export const canApprove = (template) => Boolean(template && PRE_RELEASE_STATUSES.includes(template.status));

// { allowed, reason, confirmMessage } for the Delete button.
export function deleteState(template) {
  if (!template) return { allowed: false, reason: null, confirmMessage: null };
  const label = `"${template.name}" v${template.version}`;
  if (PRE_RELEASE_STATUSES.includes(template.status)) {
    const base = `Permanently delete ${label}? This cannot be undone, and is refused if reports were generated from it.`;
    return {
      allowed: true, reason: null,
      confirmMessage: template.status === "Approved"
        ? `${base} It is Approved: its approval record${template.approvedById ? ` (user #${template.approvedById})` : ""} will be lost.`
        : base,
    };
  }
  if (template.status === "Superseded") {
    return { allowed: false, confirmMessage: null,
      reason: "Superseded versions are kept as version history and cannot be deleted." };
  }
  return { allowed: false, confirmMessage: null,
    reason: `${template.status} templates cannot be deleted — supersede the template first, then create a new version.` };
}

// Required metadata on the Overview (empty = "Missing"); reconciliation
// tolerance is optional — empty means an exact match is required.
export const REQUIRED_FIELDS = [
  { key: "regulatoryAuthority", label: "Regulatory Authority" },
  { key: "sourceReferences", label: "Source References" },
  { key: "changeSummary", label: "Change Summary" },
];
const empty = (v) => v === null || v === undefined || String(v).trim() === "";

export function missingRequiredFields(template) {
  return REQUIRED_FIELDS.filter((f) => empty(template?.[f.key])).map((f) => f.label);
}

export function toleranceLabel(template) {
  const v = template?.reconciliationTolerance;
  return empty(v) ? "Exact match" : String(v);
}
