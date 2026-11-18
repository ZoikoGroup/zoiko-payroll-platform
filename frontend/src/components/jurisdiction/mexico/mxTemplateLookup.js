// Finds the SELECTED report template's entry in the Mexico library responses
// (GET …/mexico/report-templates/coverage and …/versions). Keyed on the
// template_key first: a row whose id matches but whose key does not is never
// used (a mismatched row would show another template's build kind / gates).
// Falls back to template_key + version when the id is not present. Plain JS
// (no JSX) so scripts/mx-report-template-layout-validation.mjs imports it.
const sameVersion = (a, b) => String(a ?? "") === String(b ?? "");

export function findCoverageRow(rows, detail) {
  if (!detail?.templateKey) return null;
  const forKey = (rows || []).filter((r) => r.templateKey === detail.templateKey);
  return forKey.find((r) => r.id === detail.id) || forKey.find((r) => sameVersion(r.version, detail.version)) || null;
}

export function findVersionsGroup(groups, detail) {
  if (!detail?.templateKey) return null;
  return (groups || []).find((g) => g.templateKey === detail.templateKey) || null;
}

export function findVersionEntry(groups, detail) {
  const group = findVersionsGroup(groups, detail);
  if (!group) return null;
  return group.versions.find((v) => v.id === detail.id) || group.versions.find((v) => sameVersion(v.version, detail.version)) || null;
}
