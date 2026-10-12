import { Search, RotateCcw } from "lucide-react";
import { inputClass, labelClass } from "../constants";
import { US_FILING_STATUSES } from "./usaComponentConfig";

// USA-only filter bar for the Income Tax Brackets section. Operates purely
// on the already-fetched `slabs` array passed down from JurisdictionLayout
// (via USTaxComponentsTab) — no new API calls, no server-side filtering
// (getCanonicalTaxSlabs only supports jurisdictionPackId/country, confirmed
// via direct backend research). "State"/"Version" filters are deliberately
// omitted here: this tab already shows exactly one pack's slabs (its state
// is fixed by which pack you're viewing via the State/District sidebar, and
// its version is fixed by which pack version you selected) — a second
// filter for either would just duplicate an existing switcher one level up,
// the same class of redundant-navigation issue found and fixed in the
// Organizations/Versions/Audit tabs during the prior refactor phase.
export default function USABracketFilterBar({ scopeLabel, filingStatus, onFilingStatusChange, search, onSearchChange, availableFilingStatuses }) {
  const hasFilter = filingStatus !== "" || search !== "";
  return (
    <div className="mb-3 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface-muted p-3">
      <span className="rounded-md bg-surface px-2 py-1 text-[11px] font-semibold text-foreground-muted">{scopeLabel}</span>
      <div>
        <label className={labelClass}>Filing Status</label>
        <select className={inputClass + " w-auto min-w-[160px]"} value={filingStatus} onChange={(e) => onFilingStatusChange(e.target.value)}>
          <option value="">All Filing Statuses</option>
          {availableFilingStatuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="min-w-[200px] flex-1">
        <label className={labelClass}>Search</label>
        <div className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground-disabled" />
          <input
            className={inputClass + " pl-8"} value={search} onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search brackets by label or rate…"
          />
        </div>
      </div>
      {hasFilter && (
        <button
          onClick={() => { onFilingStatusChange(""); onSearchChange(""); }}
          className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface"
        >
          <RotateCcw size={12} /> Reset Filters
        </button>
      )}
    </div>
  );
}

export function collectFilingStatuses(slabs) {
  const set = new Set(US_FILING_STATUSES);
  for (const s of slabs) if (s.filingStatus) set.add(s.filingStatus);
  return Array.from(set);
}

export function filterSlabs(slabs, { filingStatus, search }) {
  const q = search.trim().toLowerCase();
  return slabs.filter((s) => {
    if (filingStatus && s.filingStatus !== filingStatus) return false;
    if (!q) return true;
    const haystack = `${s.rateLabel || ""} ${s.ratePct || ""} ${s.minAmount || ""} ${s.maxAmount || ""}`.toLowerCase();
    return haystack.includes(q);
  });
}
