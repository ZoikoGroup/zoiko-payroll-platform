import { useMemo, useState } from "react";
import { Pencil, Trash2, Plus, Search, RotateCcw } from "lucide-react";
import USATaxSlabFormModal from "./USATaxSlabFormModal";
import { collectFilingStatuses } from "./USABracketFilterBar";
import { inputClass } from "../constants";
import StatusPill from "../../StatusPill";
import { STATUS_PILL_MAP } from "../constants";

// USA-only Income Tax Brackets tab — a flat, filterable bracket table
// (one row per TaxSlab) with Filing Status / search / status / effective
// year filters, replacing the old grouped stacked tables. Same
// slabs/onReload/onDeleteSlab props, zero new fetching.
export default function USIncomeTaxBracketsTab({ pack, slabs, onReload, onDeleteSlab }) {
  const [addingSlab, setAddingSlab] = useState(false);
  const [editingSlab, setEditingSlab] = useState(null);
  const [filingStatus, setFilingStatus] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");

  const availableFilingStatuses = useMemo(() => collectFilingStatuses(slabs || []), [slabs]);
  const availableYears = useMemo(() => {
    const set = new Set();
    for (const s of slabs || []) {
      if (s.effectiveFrom) set.add(String(s.effectiveFrom).slice(0, 4));
      if (s.effectiveTo) set.add(String(s.effectiveTo).slice(0, 4));
    }
    return Array.from(set).sort();
  }, [slabs]);

  const filteredSlabs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (slabs || [])
      .filter((s) => {
        if (filingStatus && s.filingStatus !== filingStatus) return false;
        if (statusFilter && (s.status || pack?.status) !== statusFilter) return false;
        if (yearFilter) {
          const eff = String(s.effectiveFrom || s.effectiveTo || "").slice(0, 4);
          if (eff !== yearFilter) return false;
        }
        if (q) {
          const hay = `${s.rateLabel || ""} ${s.ratePct || ""} ${s.minAmount || ""} ${s.maxAmount || ""} ${s.filingStatus || ""}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      })
      .sort((a, b) => {
        const fs = (a.filingStatus || "").localeCompare(b.filingStatus || "");
        if (fs !== 0) return fs;
        return Number(a.minAmount) - Number(b.minAmount);
      });
  }, [slabs, filingStatus, search, statusFilter, yearFilter, pack]);

  const hasFilter = filingStatus !== "" || search !== "" || statusFilter !== "" || yearFilter !== "";

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-foreground">Income Tax Brackets</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">Marginal-rate brackets by W-4 filing status — a row with no filing status applies to every employee.</p>
        </div>
        <button
          onClick={() => setAddingSlab(true)}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Bracket
        </button>
      </div>

      <FilterBar
        filingStatus={filingStatus} onFilingStatus={setFilingStatus}
        search={search} onSearch={setSearch}
        statusFilter={statusFilter} onStatusFilter={setStatusFilter}
        yearFilter={yearFilter} onYearFilter={setYearFilter}
        availableFilingStatuses={availableFilingStatuses}
        availableYears={availableYears}
        hasFilter={hasFilter}
        onReset={() => { setFilingStatus(""); setSearch(""); setStatusFilter(""); setYearFilter(""); }}
      />

      {filteredSlabs.length === 0 ? (
        <EmptyState text={(slabs || []).length === 0 ? "No tax brackets configured yet." : "No brackets match the current filters."} />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-xs">
              <thead>
                <tr className="border-b border-border-light text-left text-[11px] font-semibold uppercase tracking-wider text-foreground-muted">
                  <th className="px-3 py-2.5">Filing Status</th>
                  <th className="px-3 py-2.5 text-right">Min Income</th>
                  <th className="px-3 py-2.5 text-right">Max Income</th>
                  <th className="px-3 py-2.5 text-right">Rate %</th>
                  <th className="px-3 py-2.5">Effective Period</th>
                  <th className="px-3 py-2.5">Status</th>
                  <th className="px-3 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredSlabs.map((s) => (
                  <tr key={s.id} className="border-b border-border-light last:border-0 hover:bg-surface-muted">
                    <td className="px-3 py-2.5 font-medium text-foreground">{s.filingStatus || <span className="text-foreground-disabled">Any</span>}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{s.minAmount}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{s.maxAmount ?? "and above"}</td>
                    <td className="px-3 py-2.5 text-right font-semibold text-foreground tabular-nums">{s.ratePct}%</td>
                    <td className="px-3 py-2.5 text-foreground-secondary">
                      <EffectivePeriod slab={s} />
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusPill status={STATUS_PILL_MAP[s.status || pack?.status] || "pending"} label={s.status || pack?.status || "—"} />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => setEditingSlab(s)} title="Edit" className="rounded-md p-1.5 text-foreground-muted hover:bg-surface hover:text-foreground"><Pencil size={13} /></button>
                        <button onClick={() => onDeleteSlab(s)} title="Delete" className="rounded-md p-1.5 text-error hover:bg-error-light"><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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

function EffectivePeriod({ slab }) {
  const from = slab.effectiveFrom;
  const to = slab.effectiveTo;
  if (from && to) return <span>{from} → {to}</span>;
  if (from) return <span>{from} → open</span>;
  return <span className="text-foreground-disabled">—</span>;
}

function FilterBar({ filingStatus, onFilingStatus, search, onSearch, statusFilter, onStatusFilter, yearFilter, onYearFilter, availableFilingStatuses, availableYears, hasFilter, onReset }) {
  return (
    <div className="mb-3 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface-muted p-3">
      <div className="min-w-[200px] flex-1">
        <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Search</label>
        <div className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground-disabled" />
          <input className={inputClass + " pl-8"} value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search by label, rate, or range…" />
        </div>
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Filing Status</label>
        <select className={inputClass + " w-auto min-w-[150px]"} value={filingStatus} onChange={(e) => onFilingStatus(e.target.value)}>
          <option value="">All Filing Statuses</option>
          {availableFilingStatuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Status</label>
        <select className={inputClass + " w-auto min-w-[130px]"} value={statusFilter} onChange={(e) => onStatusFilter(e.target.value)}>
          <option value="">All Statuses</option>
          <option value="Active">Active</option>
          <option value="Draft">Draft</option>
          <option value="In Review">In Review</option>
          <option value="Approved">Approved</option>
        </select>
      </div>
      {availableYears.length > 0 && (
        <div>
          <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Effective Year</label>
          <select className={inputClass + " w-auto min-w-[130px]"} value={yearFilter} onChange={(e) => onYearFilter(e.target.value)}>
            <option value="">All Years</option>
            {availableYears.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      )}
      {hasFilter && (
        <button onClick={onReset} className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface">
          <RotateCcw size={12} /> Reset
        </button>
      )}
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
