// Client-side filter for the Super Admin Report Templates list (every country
// page and the SG / HK compliance tabs render ReportTemplateLayout, which uses
// this). Case-insensitive, partial match on the name, report type, template
// key and state. Plain JS (no JSX) so scripts/report-template-filter-
// validation.mjs can import it directly under Node.
const FIELDS = ["name", "reportType", "templateKey", "jurisdictionState"];

export function filterTemplates(templates, text) {
  const needle = (text || "").trim().toLowerCase();
  if (!needle) return templates || [];
  return (templates || []).filter((t) =>
    FIELDS.some((field) => String(t?.[field] ?? "").toLowerCase().includes(needle)),
  );
}
