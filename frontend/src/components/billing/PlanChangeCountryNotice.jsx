import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { getCountryNameFromCode } from "../../utils/currency";
import {
  COMPLIANCE_COUNTRIES_ROUTE,
  COMPLIANCE_COUNTRIES_STATE,
  impactNeedsReview,
  impactPausesCountries,
} from "../../utils/planLimits";

// What a plan change does to the org's countries — rendered from
// GET /billing/plan-change-impact, or from the 409 trace POST /billing/checkout
// returns when the change would pause countries without acknowledgement
// (same {planCode, newLimit, countries, keep, pause, restore} shape; see
// utils/planLimits.js for getCountryPauseImpact and the impact checks).

function names(codes = []) {
  return codes.map((c) => getCountryNameFromCode(c) || c).join(", ");
}

// Inline notice: pause warning (with the required confirmation checkbox) and
// a restore note. Renders nothing when the change touches no countries.
export default function PlanChangeCountryNotice({ impact, planName, acknowledged, onAcknowledgedChange, className = "" }) {
  if (!impactNeedsReview(impact)) return null;
  const pause = impact.pause || [];
  const restore = impact.restore || [];
  const keep = impact.keep || [];
  const plan = planName || impact.planCode || "this plan";

  return (
    <div className={`flex flex-col gap-3 text-left ${className}`}>
      {pause.length > 0 && (
        <div role="alert" className="rounded-[12px] border border-amber-300 bg-amber-50 px-4 py-3 text-[13px] text-amber-900 dark:border-amber-700/50 dark:bg-amber-900/20 dark:text-amber-100">
          <div className="flex items-start gap-2.5">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" aria-hidden="true" />
            <div className="min-w-0">
              <p className="font-semibold">
                Switching to {plan}
                {keep.length > 0 ? ` keeps ${names(keep)}` : ""}; payroll and new employees in {names(pause)} will be paused.
                Existing employees and payroll history stay readable.
              </p>
              <p className="mt-1.5 text-[12px]">
                To choose which countries stay active, review them under{" "}
                <Link to={COMPLIANCE_COUNTRIES_ROUTE} state={COMPLIANCE_COUNTRIES_STATE} className="font-bold underline underline-offset-2">
                  Compliance &gt; Countries
                </Link>{" "}
                before switching.
              </p>
              <label className="mt-3 flex cursor-pointer items-start gap-2 text-[12.5px] font-medium">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 shrink-0 accent-amber-600"
                  checked={Boolean(acknowledged)}
                  onChange={(e) => onAcknowledgedChange?.(e.target.checked)}
                />
                <span>I understand payroll and new employees in {names(pause)} will be paused on the {plan} plan.</span>
              </label>
            </div>
          </div>
        </div>
      )}
      {restore.length > 0 && (
        <div className="rounded-[12px] border border-emerald-300 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-900 dark:border-emerald-700/50 dark:bg-emerald-900/20 dark:text-emerald-100">
          <div className="flex items-start gap-2.5">
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" />
            <p className="font-semibold">
              Switching to {plan} reactivates payroll and new employees in {names(restore)}.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// Modal wrapper for plan pickers: shows the notice and continues to checkout
// only once a pause has been acknowledged.
export function PlanChangeCountryDialog({ impact, planName, acknowledged, onAcknowledgedChange, onConfirm, onClose, busy }) {
  const blocked = impactPausesCountries(impact) && !acknowledged;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="plan-change-country-title">
      <div className="w-full max-w-lg rounded-xl bg-surface p-6 shadow-lg">
        <h3 id="plan-change-country-title" className="text-lg font-semibold text-foreground">
          Switch to {planName || impact?.planCode}?
        </h3>
        <p className="mt-1 text-sm text-foreground-secondary">This plan change affects the countries you run payroll in.</p>
        <PlanChangeCountryNotice
          impact={impact}
          planName={planName}
          acknowledged={acknowledged}
          onAcknowledgedChange={onAcknowledgedChange}
          className="mt-4"
        />
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg bg-surface-muted px-4 py-2 text-sm font-medium text-foreground-secondary hover:bg-border-light disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || blocked}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {busy ? "Redirecting…" : "Continue to checkout"}
          </button>
        </div>
      </div>
    </div>
  );
}
