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

/**
 * Church tax is always configured — the 16-Land base matrix
 * (CHURCH_TAX_LAND_RATES) is a hardcoded constant the engine always has,
 * never a DB registry an operator populates. Zero rows in the separate
 * sub-Land EXCEPTIONS registry (e.g. Bad Wimpfen) is the normal case, not
 * an absence of church-tax configuration — so this must never fall
 * through to countLabel()'s generic "None configured" on that basis.
 */
export function churchTaxSummary({ laender, exceptions } = {}) {
  const landCount = Array.isArray(laender) ? laender.length : 0;
  if (landCount === 0) return "None configured";
  const exceptionCount = Array.isArray(exceptions) ? exceptions.length : 0;
  const exceptionPart = exceptionCount === 0
    ? "no sub-Land exceptions"
    : `${exceptionCount} sub-Land exception${exceptionCount === 1 ? "" : "s"}`;
  return `${landCount} Länder configured — ${exceptionPart}`;
}
