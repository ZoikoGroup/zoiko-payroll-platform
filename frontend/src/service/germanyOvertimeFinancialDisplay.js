/**
 * service/germanyOvertimeFinancialDisplay.js
 * ------------------------------------------------------------
 * Phase 8AU — pure display-logic extraction for the Germany overtime
 * financial-integration summary shown in both GermanyOvertimePanel.jsx's
 * single-attach AttachRow (added Phase 8AT) and its batch attach view
 * (added Phase 8AU) — one shared, testable function instead of the same
 * conditional logic duplicated in two JSX components.
 *
 * Kept as a plain, DOM-free function (same convention as
 * service/errorClassification.js) so it can be unit-tested — this repo has
 * no component-rendering test infrastructure (no @testing-library/react,
 * no jsdom setup), only vitest against plain functions/modules.
 *
 * Backend contract this is built against (verified directly against
 * backend/app/modules/payroll/schemas.py's
 * GermanyOvertimePremiumComponentResponse, not assumed):
 *   - financialIntegrationStatus: string | null — one of
 *     "CALCULATED" (Phase 8BW: gross/SI/wage-tax/Soli/Kirchensteuer all
 *     genuinely computed via the internal §32a/§39b calculator, reusing
 *     the base payslip's own zvE), "PARTIAL" (wage tax/Soli computed, but
 *     this employee's own base payslip has church tax flagged unavailable
 *     — Phase 8BU — so church-tax delta stays an explicitly-unavailable
 *     0), "BLOCKED" (the base payslip's own wage tax was never computed
 *     via the internal calculator at all, so none of the three tax deltas
 *     could be derived — only gross/SI apply), "REVERSED" (set by
 *     detach), or null (never integrated — e.g. a NEVER_ATTACHED
 *     component). The retired "PARTIAL_WAGE_TAX_PENDING_PAP" value never
 *     appears on any component attached under Phase 8BW or later.
 *   - appliedGrossDelta / appliedPfDelta / appliedEsiDelta /
 *     appliedWageTaxDelta / appliedSoliDelta / appliedChurchTaxDelta:
 *     number | null (FastAPI's jsonable_encoder serializes Decimal as a
 *     JSON number, not a string — confirmed directly, not assumed) — null
 *     both before any attach and after a detach clears them (service.py's
 *     _detach_one_germany_overtime_premium_component sets all six columns
 *     back to None).
 */

export function describeOvertimeFinancialIntegration(component) {
  if (!component) {
    return {
      hasData: false, isCalculated: false, isPartial: false, isBlocked: false, isReversed: false,
      appliedGrossDelta: null, appliedPfDelta: null, appliedEsiDelta: null,
      appliedWageTaxDelta: null, appliedSoliDelta: null, appliedChurchTaxDelta: null,
    };
  }
  const status = component.financialIntegrationStatus ?? null;
  return {
    hasData: true,
    isCalculated: status === "CALCULATED",
    isPartial: status === "PARTIAL",
    isBlocked: status === "BLOCKED",
    isReversed: status === "REVERSED",
    appliedGrossDelta: component.appliedGrossDelta ?? null,
    appliedPfDelta: component.appliedPfDelta ?? null,
    appliedEsiDelta: component.appliedEsiDelta ?? null,
    appliedWageTaxDelta: component.appliedWageTaxDelta ?? null,
    appliedSoliDelta: component.appliedSoliDelta ?? null,
    appliedChurchTaxDelta: component.appliedChurchTaxDelta ?? null,
  };
}
