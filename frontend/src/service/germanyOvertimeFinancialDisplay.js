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
 *     "PARTIAL_WAGE_TAX_PENDING_PAP" (attach applied SI/gross, wage tax
 *     still pending PAP), "REVERSED" (set by detach), or null (never
 *     integrated — e.g. a NEVER_ATTACHED component).
 *   - appliedGrossDelta / appliedPfDelta / appliedEsiDelta: number | null
 *     (FastAPI's jsonable_encoder serializes Decimal as a JSON number, not
 *     a string — confirmed directly, not assumed) — null both before any
 *     attach and after a detach clears them (service.py's
 *     _detach_one_germany_overtime_premium_component sets these three
 *     columns back to None).
 */

export function describeOvertimeFinancialIntegration(component) {
  if (!component) {
    return { hasData: false, isPendingPap: false, isReversed: false, appliedGrossDelta: null, appliedPfDelta: null, appliedEsiDelta: null };
  }
  const status = component.financialIntegrationStatus ?? null;
  return {
    hasData: true,
    isPendingPap: status === "PARTIAL_WAGE_TAX_PENDING_PAP",
    isReversed: status === "REVERSED",
    appliedGrossDelta: component.appliedGrossDelta ?? null,
    appliedPfDelta: component.appliedPfDelta ?? null,
    appliedEsiDelta: component.appliedEsiDelta ?? null,
  };
}
