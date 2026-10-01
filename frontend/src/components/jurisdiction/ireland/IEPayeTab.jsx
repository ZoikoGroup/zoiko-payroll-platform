import RatesTab from "../RatesTab";
import { IE_PAYE_COMPONENT_KEYS } from "./ieComponentConfig";

// PAYE statutory rates (IE-003).
//
// The employee's own standard-rate band and tax credit are deliberately
// NOT editable here: they come from Revenue's frozen RPN instruction per
// employee (IE-005), and IE-045 forbids substituting current pack values
// into a historical replay. Editing these two rates changes what the
// calculator ASSESSES, not what Revenue has instructed.
export default function IEPayeTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_PAYE_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        PAYE Standard and Higher statutory rates (IE-003). Each employee&apos;s standard-rate
        band and tax credit are issued per-employee by Revenue and held as a frozen RPN
        snapshot — they are read from that instruction, never from these rows.
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
