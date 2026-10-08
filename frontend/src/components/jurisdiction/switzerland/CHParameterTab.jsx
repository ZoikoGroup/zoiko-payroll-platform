import RatesTab from "../RatesTab";
import { CH_GROUPED_KEYS } from "./chComponentConfig";

// One Switzerland statutory-parameter group: the SAME canonical
// ContributionRate CRUD every country uses, filtered to one concept's
// scalar keys. Scalar rows carry no scope or worker class, so the generic
// rate form is safe for them.
//
// `keys` = null lists every scalar row no other group claims, so a
// parameter is never hidden just because this file has not been updated
// for it.
export default function CHParameterTab({ description, keys, pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = keys
    ? (rates || []).filter((r) => keys.includes(r.componentKey))
    : (rates || []).filter((r) => !CH_GROUPED_KEYS.has(r.componentKey));
  const present = new Set(filtered.map((r) => r.componentKey));
  const missingKeys = (keys || []).filter((k) => !present.has(k));
  if (!keys && filtered.length === 0) return null;
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">{description}</p>
      {missingKeys.length > 0 && (
        <p role="status" className="rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-xs text-foreground-secondary">
          Not configured in this pack (Swiss calculations that need them are blocked, never defaulted):{" "}
          <span className="font-mono">{missingKeys.join(", ")}</span>
        </p>
      )}
      <RatesTab pack={pack} rates={filtered} onAdd={onAddRate} onEdit={onEditRate} onDelete={onDeleteRate} />
    </div>
  );
}