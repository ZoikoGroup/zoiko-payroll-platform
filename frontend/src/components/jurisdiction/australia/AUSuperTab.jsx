import RatesTab from "../RatesTab";
import { AU_SUPER_COMPONENT_KEYS } from "./auComponentConfig";

// Superannuation Guarantee rate + Maximum Contribution Base (§10, Payday
// Super). The per-payday liability/receipt-SLA RECORD itself
// (SuperGuaranteeLiability) has no dedicated view yet — these two rows
// are the statutory RATE configuration only.
export default function AUSuperTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => AU_SUPER_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        Superannuation Guarantee rate and the annual Maximum Contribution Base (§10) — SG is capped once an employee's cumulative qualifying earnings for the Australian financial year reach this base.
      </p>
      <RatesTab pack={pack} rates={filtered} onAdd={onAddRate} onEdit={onEditRate} onDelete={onDeleteRate} />
    </div>
  );
}
