import RatesTab from "../RatesTab";
import { IE_MFF_COMPONENT_KEYS } from "./ieComponentConfig";

// MyFutureFund (IE-018/IE-020).
//
// The 0.5% State contribution is administered separately by the State/NAERSA
// and must never be deducted from an employee's pay (IE-018), which is why
// it is configured here but reported separately by the engine as
// ie_mff_state_topup rather than included in the employee total.
//
// Whether an employee is contributory at all comes from their NAERSA-notified
// status, not from these rates: the engine blocks the run when no authority
// status is in force, and there is deliberately no "enrol this employee"
// control anywhere in the product.
export default function IEMyFutureFundTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_MFF_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        MyFutureFund employee and employer rates and the annual earnings threshold
        (IE-018/IE-020). The State contribution is shown for completeness but is never
        deducted from pay. Each employee&apos;s contributory status is the NAERSA-notified
        status in force on the pay date, not a setting on this page.
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
