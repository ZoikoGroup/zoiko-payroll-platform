import { useState } from "react";
import { Plus } from "lucide-react";
import ComplianceConfigModal from "../ComplianceConfigModal";
import CARateRow from "./CARateRow";

// Mirrors india/INTaxComponentsTab.jsx's role — the shared list-and-edit
// tab for a fixed set of known component keys. Every CA extraTab in
// CACompliancePage.jsx (CPP & EI, Federal Tax Parameters, Quebec,
// Territorial Payroll Tax) renders one of these, just with a different
// title/description/key list from caComponentConfig.js.
//
// `keys` is [{ key, label, shape }] — `shape` (rate_pair | rate_single |
// flat) is passed straight through to ComplianceConfigModal as
// componentKeyOptions, which is what lets the Add/Edit modal show only
// the fields that component actually has (Employee % alone for a
// single-sided rate like cpp2_rate, Flat Amount alone for a threshold
// like cpp_ympe, both % fields for a real employee/employer split like
// cpp/qpp) instead of every field for every row. Every key here is a
// real, engine-read key from engine/countries/canada.py and
// hardcoded_defaults.py; nothing here invents a new one.
export default function CARateGroupTab({ title, description, keys, pack, rates, onDeleteRate, onReload, addToast }) {
  const [modal, setModal] = useState(null); // { mode, initialData } | null
  const rows = keys.map((k) => rates.find((r) => r.componentKey === k.key)).filter(Boolean);

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-bold text-foreground">{title}</h4>
        {description && <p className="text-xs text-foreground-muted mt-0.5">{description}</p>}
      </div>
      <div className="flex justify-end">
        <button
          onClick={() => setModal({ mode: "add", initialData: null })}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center">
          <p className="text-xs text-foreground-disabled">Nothing configured yet.</p>
          <p className="mt-1 text-[10px] text-foreground-disabled">Expected: {keys.map((k) => k.label).join(", ")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {rows.map((r) => (
            <CARateRow key={r.id} row={r} onEdit={(row) => setModal({ mode: "edit", initialData: row })} onDelete={onDeleteRate} />
          ))}
        </div>
      )}
      {modal && (
        <ComplianceConfigModal
          mode={modal.mode} pack={pack} initialData={modal.initialData} componentKeyOptions={keys}
          addToast={addToast} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); onReload(); }}
        />
      )}
    </div>
  );
}
