import { useMemo, useState } from "react";
import { Percent, Plus, Search, RotateCcw } from "lucide-react";
import USComponentSummaryCards from "./USComponentSummaryCards";
import USTaxComponentTable from "./USTaxComponentTable";
import USAAddComponentModal from "./USAAddComponentModal";
import USAComponentFormModal from "./USAComponentFormModal";
import { inputClass } from "../constants";
import { classifyContributionRate } from "./usaComponentConfig";

// USA-only "Tax Components" tab. Wired into usaComplianceConfig's extraTabs,
// fed the exact same `rates`/`onReload`/`onDeleteRate` props JurisdictionLayout
// already passes. Replaces the old stacked USAComponentCard presentation with
// compact summary cards + client-side filters + a clean one-row-per-rate
// table. No new fetching; save refreshes only this pack's rates via onReload.
export default function USTaxComponentsTab({ pack, rates, slabs, onReload, onDeleteRate, onNavigateTab }) {
  const [showWizard, setShowWizard] = useState(false);
  const [editingRate, setEditingRate] = useState(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [appliesFilter, setAppliesFilter] = useState("");

  const rows = useMemo(() => {
    const arr = (rates || []).slice();
    const q = search.trim().toLowerCase();
    return arr
      .filter((r) => {
        if (typeFilter) {
          const { uiType } = classifyContributionRate(r);
          if (uiType !== typeFilter) return false;
        }
        if (appliesFilter) {
          const applies = r.filingStatus || r.jurisdictionState || "Any";
          if (applies !== appliesFilter) return false;
        }
        if (q) {
          const hay = `${r.label || ""} ${r.componentKey || ""} ${r.filingStatus || ""} ${r.jurisdictionState || ""}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      })
      .sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0) || (a.label || "").localeCompare(b.label || ""));
  }, [rates, search, typeFilter, appliesFilter]);

  const hasFilter = search !== "" || typeFilter !== "" || appliesFilter !== "";

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground"><Percent size={15} /> Tax Components</h3>
          <p className="mt-0.5 text-xs text-foreground-muted">Contribution rates for social security, Medicare, FUTA, and more — grouped into a single view.</p>
        </div>
        <button
          onClick={() => setShowWizard(true)}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Component
        </button>
      </div>

      <div className="mb-4">
        <USComponentSummaryCards rates={rates} slabs={slabs} />
      </div>

      <FilterBar
        search={search} onSearch={setSearch}
        typeFilter={typeFilter} onTypeFilter={setTypeFilter}
        appliesFilter={appliesFilter} onAppliesFilter={setAppliesFilter}
        rates={rates}
        hasFilter={hasFilter}
        onReset={() => { setSearch(""); setTypeFilter(""); setAppliesFilter(""); }}
      />

      <USTaxComponentTable
        rates={rows}
        packStatus={pack?.status}
        onEdit={setEditingRate}
        onDelete={onDeleteRate}
      />

      {showWizard && (
        <USAAddComponentModal
          pack={pack} rates={rates || []}
          onClose={() => setShowWizard(false)}
          onEditExisting={(row) => { setShowWizard(false); setEditingRate(row); }}
          onSaved={() => { setShowWizard(false); onReload(); }}
          onNavigateIncomeTax={() => { setShowWizard(false); onNavigateTab?.("incomeTax"); }}
        />
      )}
      {editingRate && (
        <USAComponentFormModal
          pack={pack} rate={editingRate} onClose={() => setEditingRate(null)}
          onSaved={() => { setEditingRate(null); onReload(); }}
        />
      )}
    </div>
  );
}

function FilterBar({ search, onSearch, typeFilter, onTypeFilter, appliesFilter, onAppliesFilter, rates, hasFilter, onReset }) {
  const typeOptions = useMemo(() => {
    const set = new Set();
    for (const r of rates || []) set.add(classifyContributionRate(r).uiType);
    return Array.from(set).sort();
  }, [rates]);

  const appliesOptions = useMemo(() => {
    const set = new Set();
    for (const r of rates || []) set.add(r.filingStatus || r.jurisdictionState || "Any");
    return Array.from(set).sort();
  }, [rates]);

  const TYPE_LABELS = {
    PERCENTAGE: "Percentage",
    EMPLOYEE_EMPLOYER_PERCENTAGE: "Employee + Employer",
    EMPLOYER_ASSIGNED_RATE: "Employer Rate",
    WAGE_BASE: "Wage Base",
    THRESHOLD: "Threshold",
    FIXED_AMOUNT: "Fixed",
    DEDUCTION_AMOUNT: "Deduction",
    INCOME_TAX_POINTER: "Income Tax",
  };

  return (
    <div className="mb-3 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface-muted p-3">
      <div className="min-w-[200px] flex-1">
        <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Search</label>
        <div className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-foreground-disabled" />
          <input className={inputClass + " pl-8"} value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search by name, key, or filing status…" />
        </div>
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Type</label>
        <select className={inputClass + " w-auto min-w-[160px]"} value={typeFilter} onChange={(e) => onTypeFilter(e.target.value)}>
          <option value="">All Types</option>
          {typeOptions.map((t) => <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>)}
        </select>
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Applies To</label>
        <select className={inputClass + " w-auto min-w-[150px]"} value={appliesFilter} onChange={(e) => onAppliesFilter(e.target.value)}>
          <option value="">All</option>
          {appliesOptions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>
      {hasFilter && (
        <button onClick={onReset} className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface">
          <RotateCcw size={12} /> Reset
        </button>
      )}
    </div>
  );
}
