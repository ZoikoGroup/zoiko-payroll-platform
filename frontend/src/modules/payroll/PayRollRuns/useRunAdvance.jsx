import { useCallback, useState } from "react";

import { approveRun } from "../../../service/payrollService";
import { useToast } from "../ToastContext";
import ApprovalDialog from "./ApprovalDialog";
import { CONFIRMED_TARGETS, nextStatus } from "./runWorkflow";

/**
 * The one way to move a payroll run forward, shared by the Actions column,
 * the progress panel and the run detail view so they behave identically:
 *
 *  - into Approved / Authorized / Paid: opens ApprovalDialog (summary, then
 *    "Confirm <verb>"; Approved also offers the bank transfer file);
 *  - into Review / Closed: advances directly, as the Actions column always has.
 *
 * Permissions are enforced by the server (PUT /runs/{id}/approve); a refusal
 * shows the server's own reason instead of a generic failure.
 *
 * Returns { requestAdvance(run), advancingId, dialog } - render `dialog`.
 */
export default function useRunAdvance({ fmtCurrency, onAdvanced } = {}) {
  const { addToast } = useToast();
  const [advancingId, setAdvancingId] = useState(null);
  const [dialogRun, setDialogRun] = useState(null);

  const advanceDirectly = useCallback(async (run) => {
    const landedOn = nextStatus(run.status);
    setAdvancingId(run.id);
    try {
      await approveRun(run.id);
      addToast?.(landedOn ? `Payroll run advanced to ${landedOn}.` : "Payroll run advanced.", "success");
      onAdvanced?.(run.id);
    } catch (err) {
      addToast?.(err?.message ? `Couldn't advance the run: ${err.message}` : "Failed to advance payroll run.", "error");
    } finally {
      setAdvancingId(null);
    }
  }, [addToast, onAdvanced]);

  const requestAdvance = useCallback((run) => {
    if (!run || advancingId) return;
    const target = nextStatus(run.status);
    if (!target) return;
    if (CONFIRMED_TARGETS.includes(target)) {
      setDialogRun(run);
      return;
    }
    advanceDirectly(run);
  }, [advancingId, advanceDirectly]);

  const dialog = dialogRun ? (
    <ApprovalDialog
      run={dialogRun}
      targetStatus={nextStatus(dialogRun.status)}
      fmtCurrency={fmtCurrency}
      onApproved={() => onAdvanced?.(dialogRun.id)}
      onClose={() => setDialogRun(null)}
    />
  ) : null;

  return { requestAdvance, advancingId, dialog };
}
