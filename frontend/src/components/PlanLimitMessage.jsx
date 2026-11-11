import { Link } from "react-router-dom";
import { ArrowRight, Lock } from "lucide-react";
import { isPlanLimitError } from "../service/errorClassification";

// The plan-selection page (App.jsx: /billing/plans → PlanSelectionPage).
export const PLAN_SELECTION_ROUTE = "/billing/plans";

// Re-exported so callers can import the check alongside the component.
export { isPlanLimitError };

// Renders a country-entitlement / plan-limit block (see isPlanLimitError)
// with an upgrade link. Pass either the thrown API `error`, or a `message`
// directly (e.g. a bulk-import failed[] row). `compact` drops the
// box chrome for use inside a table cell. The server message already names
// the plan, its country limit and the entitled countries, so it is shown as is.
export default function PlanLimitMessage({ error, message, compact = false, className = "" }) {
  const text = message || error?.message || "This action is not included in your current plan.";
  // No plan at all (or a cancelled one) — there is nothing to upgrade from.
  const noPlan = error?.trace?.resource === "subscription";

  const link = (
    <Link
      to={PLAN_SELECTION_ROUTE}
      className="inline-flex items-center gap-1 font-bold text-primary hover:text-primary-hover underline-offset-2 hover:underline"
    >
      {noPlan ? "Choose a plan" : "Upgrade plan"} <ArrowRight size={12} aria-hidden="true" />
    </Link>
  );

  if (compact) {
    return (
      <span className={`block ${className}`}>
        {text}
        <span className="mt-0.5 block text-[12px]">{link}</span>
      </span>
    );
  }

  return (
    <div role="alert" className={`flex items-start gap-2.5 rounded-[12px] border border-warning/30 bg-warning/10 px-4 py-3 text-[13px] text-warning ${className}`}>
      <Lock size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        <p className="font-semibold">{text}</p>
        <p className="mt-1.5 text-[12px]">{link}</p>
      </div>
    </div>
  );
}
