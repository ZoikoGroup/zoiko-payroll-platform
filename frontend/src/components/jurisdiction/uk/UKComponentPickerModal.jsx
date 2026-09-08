import { useMemo, useState } from "react";
import { Search, ChevronRight, CornerDownRight } from "lucide-react";
import Modal from "../../Modal";
import { inputClass } from "../constants";
import { PAYROLL_COMPONENT_CATALOG, PAYROLL_COMPONENT_CATEGORIES } from "./ukComponentConfig";

// UK-specific Step 1 of "+ Add Component" — the admin picks a payroll
// component by business name (National Insurance, Workplace Pension, ...),
// never a technical UI type. Follows the same structure as
// india/INComponentPickerModal.jsx. Reuses `rates`/`slabs` already fetched
// for this pack to know which entries are already configured.
export default function UKComponentPickerModal({ pack, rates, slabs, onEditExisting, onAddNew, onNavigate, onCustom, onClose }) {
  const [search, setSearch] = useState("");

  const scopeLabel = pack.jurisdictionState || "United Kingdom";
  const q = search.trim().toLowerCase();

  const configuredKeys = useMemo(() => {
    const keySet = new Set((rates || []).map((r) => r.componentKey));
    const niBandCount = (slabs || []).filter((s) => s.ruleType === "NI_BAND").length;
    if (niBandCount > 0) keySet.add("__ni_bands");
    return keySet;
  }, [rates, slabs]);

  const entries = useMemo(() => {
    return PAYROLL_COMPONENT_CATALOG
      .map((entry) => ({ entry, configured: entry.synthetic ? configuredKeys.has(entry.componentKey) : configuredKeys.has(entry.componentKey) }))
      .filter(({ entry }) => !q || entry.displayName.toLowerCase().includes(q) || entry.description.toLowerCase().includes(q));
  }, [configuredKeys, q]);

  const grouped = useMemo(() => {
    const map = new Map();
    for (const item of entries) {
      const cat = item.entry.category;
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat).push(item);
    }
    return map;
  }, [entries]);

  function handleClick(entry, configured) {
    if (entry.navigatesTo) { onNavigate(entry.navigatesTo); return; }
    if (configured) {
      // Find the first matching rate row to edit
      const existingRow = (rates || []).find((r) => r.componentKey === entry.componentKey);
      if (existingRow) { onEditExisting(existingRow); return; }
      // For NI bands, navigate to the NI bands section
      if (entry.componentKey === "__ni_bands") { onNavigate("ni-bands"); return; }
    }
    onAddNew(entry);
  }

  return (
    <Modal title="Select Payroll Component" onClose={onClose} maxWidth="max-w-2xl">
      <div className="relative mb-4">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground-disabled" />
        <input
          autoFocus className={inputClass + " pl-9"} value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search components…"
        />
      </div>

      <div className="max-h-[28rem] space-y-5 overflow-y-auto pr-1">
        {Object.keys(PAYROLL_COMPONENT_CATEGORIES).map((catKey) => {
          const items = grouped.get(catKey);
          if (!items || items.length === 0) return null;
          return (
            <div key={catKey}>
              <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
                {PAYROLL_COMPONENT_CATEGORIES[catKey]}
              </p>
              <div className="space-y-1">
                {items.map(({ entry, configured }) => (
                  <button
                    key={entry.componentKey}
                    onClick={() => handleClick(entry, configured)}
                    className={`flex w-full items-center justify-between rounded-lg border border-border px-3 py-2.5 text-left hover:border-primary hover:bg-primary/5 ${entry.parentKey ? "ml-5" : ""}`}
                  >
                    <div className="flex items-start gap-2">
                      {entry.parentKey && <CornerDownRight size={13} className="mt-0.5 text-foreground-disabled" />}
                      <div>
                        <p className="text-sm font-medium text-foreground">{entry.displayName}</p>
                        <p className="text-xs text-foreground-muted">{entry.description}</p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusBadge entry={entry} configured={configured} />
                      <ChevronRight size={14} className="text-foreground-disabled" />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}

        {entries.length === 0 && (
          <p className="py-6 text-center text-xs text-foreground-disabled">No components match "{search}".</p>
        )}

        <div>
          <button
            onClick={onCustom}
            className="flex w-full items-center justify-between rounded-lg border border-dashed border-border px-3 py-2.5 text-left hover:border-primary hover:bg-primary/5"
          >
            <div>
              <p className="text-sm font-medium text-foreground">Other / Custom Component</p>
              <p className="text-xs text-foreground-muted">Not in the list above — configure a component manually.</p>
            </div>
            <ChevronRight size={14} className="text-foreground-disabled" />
          </button>
        </div>
      </div>

      <div className="mt-5 flex justify-end">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
      </div>
    </Modal>
  );
}

function StatusBadge({ entry, configured }) {
  if (entry.navigatesTo) {
    const label = entry.componentKey === "__paye_income_tax" ? "Managed in PAYE Income Tax" : "Managed in NI Bands";
    return <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{label}</span>;
  }
  return configured
    ? <span className="rounded-full bg-success-light px-2 py-0.5 text-[11px] font-medium text-success">Configured</span>
    : <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-foreground-disabled">Not configured</span>;
}
