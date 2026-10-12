import RatesTab from "../RatesTab";
import { IE_USC_COMPONENT_KEYS } from "./ieComponentConfig";

// Universal Social Charge (IE-009/IE-010).
//
// USC has its OWN payable base and its OWN cumulative paid figure, which
// is why it is never assumed equal to the PAYE base. The band limits here
// are ANNUAL figures; the engine divides them by the pay periods per year
// itself, exactly as Revenue's published method does.
export default function IEUscTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_USC_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        Universal Social Charge band thresholds and rates (IE-009/IE-010). Limits are annual
        totals — the engine converts them to per-period figures using the pay frequency, and
        tracks the paid amount cumulatively in its own year-to-date base.
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
