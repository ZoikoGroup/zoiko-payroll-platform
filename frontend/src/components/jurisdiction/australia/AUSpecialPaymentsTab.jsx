import RatesTab from "../RatesTab";
import { AU_SPECIAL_PAYMENT_COMPONENT_KEYS } from "./auComponentConfig";

// Employment Termination Payment caps, the genuine-redundancy tax-free
// formula parameters, and the reference-only super caps (§13). These are
// the only Special Payments figures your source document actually
// publishes — Schedules 2/3/4/5/6/12/13 and Working Holiday Maker's own
// scale have no rate/coefficient table anywhere in the document, so
// engine/countries/australia.py's calculate_au_special_payment_withholding
// deliberately raises rather than computing a guessed amount. There is
// nothing to configure here for those until real ATO data exists.
export default function AUSpecialPaymentsTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => AU_SPECIAL_PAYMENT_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        ETP life/death benefit caps, genuine redundancy tax-free formula ($13,598 + $6,801 × years of service), and reference-only super caps (§13). Schedules 2/3/4/5/6/12/13 and Working Holiday Maker have no published rate table in the source document and are not configurable here.
      </p>
      <RatesTab pack={pack} rates={filtered} onAdd={onAddRate} onEdit={onEditRate} onDelete={onDeleteRate} />
    </div>
  );
}
