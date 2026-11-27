// The payroll run workflow, in ONE place for every screen that shows it
// (Payroll Runs list panel, the run detail view, the Actions column).
//
// Source of truth: backend PAYROLL_STATUS_ORDER (app/modules/payroll/models.py)
// and advance_payroll_run_status (service.py), reached through
// PUT /api/payroll/runs/{id}/approve. A run moves exactly one step forward per
// call; there is no step back. scripts/run-workflow-validation.mjs fails the
// build if this order ever drifts from the backend's.
//
// The guidance text below describes what the code actually does - the single
// Advance button (✓, "Advance to <next status>") in the Actions column, the
// confirmation dialog that some steps open (ApprovalDialog.jsx) and the
// checks the server makes. Keep it in step with those files.

import { ROLES } from "../../../config/roles";
import { PAYROLL_STATUS_ORDER } from "../../../service/payrollService";

// The frontend's one copy of the order lives in payrollService.js (also used
// by isRunFinalized and the reports pages); re-exported here for the workflow UI.
export { PAYROLL_STATUS_ORDER };

/** The status a run moves to next, or null at the final status / unknown status. */
export function nextStatus(status) {
  const idx = PAYROLL_STATUS_ORDER.indexOf(status);
  if (idx === -1 || idx >= PAYROLL_STATUS_ORDER.length - 1) return null;
  return PAYROLL_STATUS_ORDER[idx + 1];
}

// Moving INTO these statuses opens ApprovalDialog (summary + confirm); moving
// into Review or Closed happens directly, exactly as the Actions column does.
export const CONFIRMED_TARGETS = ["Approved", "Authorized", "Paid"];

// PUT /runs/{id}/approve requires get_current_payroll_operator.
export const PAYROLL_OPERATOR_ROLES = [ROLES.ORG_ADMIN, ROLES.PAYROLL_ADMIN];
export const PAYROLL_OPERATOR_LABEL = "an Organization Admin or Payroll Admin";

export function canOperatePayroll(role) {
  return PAYROLL_OPERATOR_ROLES.includes(role);
}

/**
 * Per status: what the stage means, how to move the run on (the action that
 * leaves this status), and the short action label used on buttons.
 * `action` is null for Closed (nothing left to do).
 */
export const STEP_GUIDE = {
  Draft: {
    meaning: "The run has been calculated but not checked yet. You can still recalculate an employee's payslip "
      + "from the run details, or delete the run (Delete, the bin icon, in Actions).",
    howTo: "To send it for review, click Advance (✓, \"Advance to Review\") in the Actions column. "
      + "The run moves straight to Review; there is no confirmation step.",
    action: "Submit for review",
  },
  Review: {
    meaning: "Check the totals and each employee's payslip (View, the eye icon). Payslips can still be recalculated.",
    howTo: "To approve, click Advance (✓, \"Advance to Approved\"), check the summary in \"Approve Payroll Run\" "
      + "and click Confirm Approve.",
    action: "Approve",
  },
  Approved: {
    meaning: "The run is approved and its amounts are locked. Right after approving, the same dialog lets you "
      + "generate and download the bank transfer file.",
    howTo: "To authorize payment, click Advance (✓, \"Advance to Authorized\"), then Confirm Authorize in "
      + "\"Authorize Payroll Run\".",
    action: "Authorize",
  },
  Authorized: {
    meaning: "The run is cleared for payment. Pay your employees from your bank, using the bank transfer file.",
    howTo: "Once they're paid, click Advance (✓, \"Advance to Paid\"), then Confirm Mark as Paid in "
      + "\"Mark Payroll Run as Paid\". This is refused while any payslip isn't Pending (for example Failed).",
    action: "Mark as paid",
  },
  Paid: {
    meaning: "Payment is recorded and every payslip in the run is marked Paid.",
    howTo: "To finish, click Advance (✓, \"Advance to Closed\"). The run moves straight to Closed; "
      + "there is no confirmation step.",
    action: "Close run",
  },
  Closed: {
    meaning: "Final status. Nothing else to do for this run.",
    howTo: null,
    action: null,
  },
};

/**
 * Who completed a step and when, where the run records it. Draft is "done"
 * when the run was created; Review and Closed record no actor on PayrollRun,
 * so nothing is invented for them.
 */
export function stepCompletion(step, run) {
  if (!run) return null;
  if (step === "Draft") return { by: run.createdBy, at: run.createdAt, verb: "Created" };
  if (step === "Approved") return { by: run.approvedBy, at: run.approvedAt, verb: "Approved" };
  if (step === "Authorized") return { by: run.authorizedBy, at: run.authorizedAt, verb: "Authorized" };
  if (step === "Paid") return { by: run.paidBy, at: run.processedAt, verb: "Marked paid" };
  return null;
}

/** "27 Nov 2026, 3:15 pm" in the viewer's locale; null for no value. */
export function formatWhen(value) {
  if (!value) return null;
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch {
    return String(value);
  }
}

/** A run's period as a Date (local midnight) from periodStart, or null. */
export function periodStartDate(run) {
  if (!run?.periodStart) return null;
  const [y, m, d] = String(run.periodStart).split("-").map(Number);
  return y && m ? new Date(y, m - 1, d || 1) : null;
}

/** "November 2026" for a Date. */
export function monthLabel(date) {
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/**
 * Which run the progress panel follows by default:
 *  - runs whose period starts in the current month, most recent first;
 *  - otherwise none for the month, plus the most recent run that isn't Closed.
 */
export function pickDefaultRuns(runs, today = new Date()) {
  const byRecency = [...(runs || [])].sort((a, b) => {
    const da = periodStartDate(a)?.getTime() ?? 0;
    const dbt = periodStartDate(b)?.getTime() ?? 0;
    return dbt - da || (b.id ?? 0) - (a.id ?? 0);
  });
  const thisMonth = byRecency.filter((r) => {
    const d = periodStartDate(r);
    return d && d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth();
  });
  const latestUnfinished = byRecency.find((r) => r.status !== "Closed") || null;
  return { thisMonth, latestUnfinished };
}

/**
 * The "Create New Run" wizard (PayrollRunsPage + RunDetailPage), step by step.
 * Note what step 3 really does: "Submit Payroll Run" moves the newly created
 * Draft run to Review - it does not approve or pay anything.
 */
export const WIZARD_GUIDE = {
  1: {
    title: "Configure",
    meaning: "Set the pay period start and end, the pay date and the pay schedule (Monthly, Bi-Weekly or "
      + "Weekly), and choose which active employees to include.",
    howTo: "When the dates and employees are right, click Calculate Payroll.",
  },
  2: {
    title: "Calculate",
    meaning: "Payroll is calculated for the selected employees. This is a preview: nothing is saved yet. "
      + "Check the totals and each employee's pay. Attendance for the period is checked automatically; "
      + "missing attendance blocks the run unless an admin turns on the override and records a reason.",
    howTo: "Use Recalculate after any change. Then click Approve & Continue and, in \"Confirm Payroll Run\", "
      + "click Confirm & Create. This creates the run as Draft.",
  },
  3: {
    title: "Approve",
    meaning: "Check the final summary: pay period, pay date, calculation mode and totals. The run already "
      + "exists as Draft at this point.",
    howTo: "Tick \"I confirm all payroll calculations are accurate and authorize this disbursement\", then click "
      + "Submit Payroll Run. This sends the run to Review; it does not approve or pay anyone yet.",
  },
  4: {
    title: "Process",
    meaning: "The run is created and sent for review. Approving, authorizing, paying and closing happen "
      + "afterwards from the Payroll Runs list (follow it in Run progress).",
    howTo: null,
  },
};
