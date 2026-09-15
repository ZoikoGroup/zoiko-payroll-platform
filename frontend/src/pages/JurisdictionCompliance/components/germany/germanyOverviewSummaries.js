/**
 * Pure, DOM-free summary formatting for the Germany country compliance
 * overview (DEOverviewDashboard.jsx) — kept separate from the component so
 * it can be unit-tested the same way this project already tests
 * service/errorClassification.js and service/germanyOvertimeFinancialDisplay.js
 * (no React component-rendering test infrastructure exists in this repo).
 */

export function countLabel(singular, plural) {
  return (rows) => {
    const n = Array.isArray(rows) ? rows.length : 0;
    if (n === 0) return "None configured";
    return `${n} ${n === 1 ? singular : plural || `${singular}s`}`;
  };
}

export function latestStatus(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return "None configured";
  const latest = [...rows].sort((a, b) => (b.id || 0) - (a.id || 0))[0];
  const count = `${rows.length} release${rows.length === 1 ? "" : "s"}`;
  return latest?.status ? `${count} — most recent: ${latest.status}` : count;
}
