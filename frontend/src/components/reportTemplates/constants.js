// Report Template lifecycle vocabulary — deliberately its own set (Draft →
// Review → Approved → Published → Active → Superseded), distinct from
// JurisdictionPack's (Draft|In Review|QA|Approved|Active|Deprecated|
// Retired) — see backend ReportTemplate model docstring for why a report
// template needs a genuine "Published but not yet the live version" state.
export const STATUS_OPTIONS = ["Draft", "Review", "Approved", "Published", "Active", "Superseded"];
export const STATUS_PILL_MAP = {
  Draft: "pending",
  Review: "pending",
  Approved: "approved",
  Published: "approved",
  Active: "active",
  Superseded: "inactive",
};

// Field type → input control, per the product spec's explicit mapping
// (percentage/currency/wage-base/threshold → numeric+unit input, date →
// date picker, boolean → toggle, enum → dropdown, tax-bracket-table →
// structured reference, text → plain text).
export const FIELD_TYPE_OPTIONS = [
  { value: "currency", label: "Currency" },
  { value: "percentage", label: "Percentage" },
  { value: "date", label: "Date" },
  { value: "boolean", label: "Boolean" },
  { value: "enum", label: "Dropdown (Enum)" },
  { value: "tax-bracket-table", label: "Tax Bracket / Slab Table" },
  { value: "text", label: "Text" },
];
