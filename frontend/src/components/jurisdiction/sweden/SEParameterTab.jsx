import RatesTab from "../RatesTab";

// One Sweden statutory-parameter tab: the SAME canonical ContributionRate
// CRUD every country uses, filtered to one statutory concept's keys (see
// seComponentConfig.js). No Sweden-only table, no bespoke CRUD — the tabs
// exist so a reviewer audits employer contributions, withholding, SLP and
// leave/sick parameters separately instead of in one undifferentiated list.
//
// `missingKeys` are the keys of `keys` this pack has no row for: shown so an
// absent statutory value is visible (the engine blocks on it) rather than
// silently missing from the list.
export default function SEParameterTab({ description, keys, pack, rates, onAddRate, onEditRate, onDeleteRate, footer }) {
  const filtered = (rates || []).filter((r) => keys.includes(r.componentKey));
  const present = new Set(filtered.map((r) => r.componentKey));
  const missingKeys = keys.filter((k) => !present.has(k));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">{description}</p>
      {missingKeys.length > 0 && (
        <p role="status" className="rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-xs text-foreground-secondary">
          Not configured in this pack (Sweden calculations that need them are blocked, never defaulted):{" "}
          <span className="font-mono">{missingKeys.join(", ")}</span>
        </p>
      )}
      <RatesTab pack={pack} rates={filtered} onAdd={onAddRate} onEdit={onEditRate} onDelete={onDeleteRate} />
      {footer}
    </div>
  );
}
