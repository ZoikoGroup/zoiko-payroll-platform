import RatesTab from "../RatesTab";
import { IE_LABOUR_COMPONENT_KEYS } from "./ieComponentConfig";

// National Minimum Wage and Statutory Sick Pay (IE-035, IE-036).
//
// The NMW check is a BLOCK, not a warning: the engine raises a hard error
// when effective hourly pay falls below the band rate, and also blocks when
// contracted_weekly_hours is missing rather than deriving hours from a
// salary divided by a generic 40-hour week (IE-035).
//
// An employment flagged as subject to an ERO or SEO sector wage order is
// blocked outright until a certified sector rate is configured — the
// national minimum wage is deliberately not substituted for it.
export default function IELabourTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_LABOUR_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        National Minimum Wage hourly rates by age band, and the Statutory Sick Pay benefit days,
        rate, daily cap and service requirement (IE-035, IE-036). A pay rate below the
        applicable band BLOCKS the run rather than warning. Sector wage orders (ERO/SEO) are
        blocked until a certified sector rate exists — the national minimum wage is never
        substituted for one.
      </p>
      <RatesTab
        pack={pack}
        rates={filtered}
        onAdd={onAddRate}
        onEdit={onEditRate}
        onDelete={onDeleteRate}
      />
    </div>
  );
}
