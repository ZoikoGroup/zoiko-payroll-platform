import RatesTab from "../RatesTab";
import { IE_PRSI_COMPONENT_KEYS, labelForIePrsiSubclass } from "./ieComponentConfig";

// PRSI (IE-001/IE-016) — Class A only for the certified launch cohort.
//
// The six rate rows exist TWICE in this tab, once for the window to
// 30 September 2026 and once from 1 October 2026. Ireland selects the PRSI
// rate set by PAY DATE (IE-006), never by earning period, so an earning
// period straddling 1 October is not split — the whole run uses the rate set
// in force on its pay date.
export default function IEPrsiTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_PRSI_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        PRSI Class A weekly rate bands, sub-class ceilings and the AX tapered credit
        (IE-001/IE-016). Rates stepped up on 1 October 2026, so each rate row appears twice with
        its own effective dates. The employee&apos;s sub-class is an eligibility result resolved
        before the run — not a value entered here. Certified sub-classes:{" "}
        {["A0", "AX", "AL", "A1"].map(labelForIePrsiSubclass).join("; ")}.
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
