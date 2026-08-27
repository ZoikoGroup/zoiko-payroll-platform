import { useMemo, useState } from "react";
import { Pencil, Trash2, Plus } from "lucide-react";
import USATaxSlabFormModal from "./USATaxSlabFormModal";
import USABracketFilterBar, { collectFilingStatuses, filterSlabs } from "./USABracketFilterBar";

// USA-only tab, split out from USTaxComponentsTab.jsx at Venu's request so
// Income Tax Brackets get their own tab (beside "Tax Components") instead
// of living inside the same section as Contribution Components — same
// data/props JurisdictionLayout's extraTabs.render() already passes down,
// zero new fetching. Add/Edit/filtering logic is unchanged from what used
// to live in USTaxComponentsTab.jsx, just moved here.
export default function USIncomeTaxBracketsTab({ pack, slabs, onReload, onDeleteSlab }) {
  const [addingSlab, setAddingSlab] = useState(false);
  const [editingSlab, setEditingSlab] = useState(null);
  const [filingStatus, setFilingStatus] = useState("");
  const [search, setSearch] = useState("");

  const availableFilingStatuses = useMemo(() => collectFilingStatuses(slabs || []), [slabs]);
  const filteredSlabs = useMemo(() => filterSlabs(slabs || [], { filingStatus, search }), [slabs, filingStatus, search]);
  const slabGroups = useMemo(() => groupByFilingStatus(filteredSlabs), [filteredSlabs]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-foreground">Income Tax Brackets</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">Grouped by W-4 filing status — a row with no filing status applies to every employee.</p>
        </div>
        <button
          onClick={() => setAddingSlab(true)}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Bracket
        </button>
      </div>

      <USABracketFilterBar
        scopeLabel={pack.jurisdictionState || "Federal"}
        filingStatus={filingStatus} onFilingStatusChange={setFilingStatus}
        search={search} onSearchChange={setSearch}
        availableFilingStatuses={availableFilingStatuses}
      />

      {slabGroups.length === 0 ? (
        <EmptyState text={(slabs || []).length === 0 ? "No tax brackets configured yet." : "No brackets match the current filters."} />
      ) : (
        <div className="space-y-4">
          {slabGroups.map((group) => (
            <FilingStatusGroup key={group.filingStatus || "ALL"} group={group} onEdit={setEditingSlab} onDelete={onDeleteSlab} />
          ))}
        </div>
      )}

      {addingSlab && (
        <USATaxSlabFormModal
          pack={pack} onClose={() => setAddingSlab(false)}
          onSaved={() => { setAddingSlab(false); onReload(); }}
        />
      )}
      {editingSlab && (
        <USATaxSlabFormModal
          pack={pack} slab={editingSlab} onClose={() => setEditingSlab(null)}
          onSaved={() => { setEditingSlab(null); onReload(); }}
        />
      )}
    </div>
  );
}

function groupByFilingStatus(slabs) {
  const map = new Map();
  for (const s of slabs) {
    const key = s.filingStatus || "";
    if (!map.has(key)) map.set(key, { filingStatus: key, rows: [] });
    map.get(key).rows.push(s);
  }
  for (const group of map.values()) {
    group.rows.sort((a, b) => Number(a.minAmount) - Number(b.minAmount));
  }
  return Array.from(map.values()).sort((a, b) => (a.filingStatus || "").localeCompare(b.filingStatus || ""));
}

function FilingStatusGroup({ group, onEdit, onDelete }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="mb-2 text-xs font-bold uppercase tracking-wider text-foreground-muted">
        {group.filingStatus || "All Filing Statuses"}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border-light text-left text-foreground-muted">
              <th className="pb-2 pr-3">From</th>
              <th className="pb-2 pr-3">To</th>
              <th className="pb-2 pr-3">Rate</th>
              <th className="pb-2 pr-3">Label</th>
              <th className="pb-2 pr-3">State</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {group.rows.map((s) => (
              <tr key={s.id} className="border-b border-border-light last:border-0">
                <td className="py-2 pr-3">{s.minAmount}</td>
                <td className="py-2 pr-3">{s.maxAmount ?? "and above"}</td>
                <td className="py-2 pr-3 font-semibold text-foreground">{s.ratePct}%</td>
                <td className="py-2 pr-3">{s.rateLabel}</td>
                <td className="py-2 pr-3">{s.jurisdictionState || "—"}</td>
                <td className="py-2">
                  <div className="flex items-center gap-1">
                    <button onClick={() => onEdit(s)} className="rounded-md p-1.5 text-foreground-muted hover:bg-surface-muted"><Pencil size={13} /></button>
                    <button onClick={() => onDelete(s)} className="rounded-md p-1.5 text-error hover:bg-error-light"><Trash2 size={13} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface-muted py-8 text-center text-xs text-foreground-disabled">
      {text}
    </div>
  );
}
