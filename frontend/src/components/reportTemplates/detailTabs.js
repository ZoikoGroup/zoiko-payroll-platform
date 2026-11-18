// The detail-tab strip of ReportTemplateLayout: the built-in tabs minus any a
// page hides, then the page's extra tabs. "overview" is never hidden — it is
// the tab a selection opens on. Plain JS so scripts/mx-report-template-layout-
// validation.mjs can evaluate it under Node.
export function buildDetailTabs(builtIn, hidden = [], extra = []) {
  return [...builtIn.filter((t) => t.key === "overview" || !hidden.includes(t.key)), ...extra];
}
