import RatesTab from "../RatesTab";
import { IE_LPT_COMPONENT_KEYS } from "./ieComponentConfig";

// Local Property Tax (IE-003).
//
// LPT is deducted ONLY when Revenue instructs it on the employee's RPN, and
// is always kept separate from PAYE/USC/PRSI. The instruction rate itself
// is an authority-supplied value, not pack content — configuring it here
// would have no effect, so this tab exposes only the annual exemption
// threshold the engine applies to the instructed base.
export default function IELptTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_LPT_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        Local Property Tax annual exemption threshold (IE-003). LPT is deducted only when
        Revenue instructs it on the employee&apos;s RPN, and the instructed rate comes from that
        instruction rather than from this pack — this threshold is the only LPT figure the
        engine reads here.
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
