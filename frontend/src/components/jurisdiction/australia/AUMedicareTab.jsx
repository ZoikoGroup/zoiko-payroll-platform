import RatesTab from "../RatesTab";
import { AU_MEDICARE_COMPONENT_KEYS } from "./auComponentConfig";

// Medicare Levy Surcharge only — Medicare Levy proper is embedded in the
// PAYG tab's own Scale 1/2/5/6 coefficient bands (see engine/countries/
// australia.py's own module docstring for why). Reuses the generic
// RatesTab/RateFormModal as-is via JurisdictionLayout's own onAddRate/
// onEditRate/onDeleteRate — no AU-specific fields needed for a plain
// rate+threshold pair.
export default function AUMedicareTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => AU_MEDICARE_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        Medicare Levy Surcharge (MLS) — a genuinely separate annual calculation from ordinary PAYG, unrelated to Scale selection. Medicare Levy proper is configured on the PAYG tab's own Scale 5/6 coefficient bands.
      </p>
      <RatesTab pack={pack} rates={filtered} onAdd={onAddRate} onEdit={onEditRate} onDelete={onDeleteRate} />
    </div>
  );
}
