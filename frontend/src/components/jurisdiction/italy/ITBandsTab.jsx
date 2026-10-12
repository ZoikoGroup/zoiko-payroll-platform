import { useMemo, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import ITBandFormModal from "./ITBandFormModal";
import {
  COMUNE_TABLE_PREFIX, IT_BAND_RULES, IT_LAUNCH_COMMUNI, REGION_TABLE_PREFIX, comuneName, regionName, ruleMeta,
} from "./itComponentConfig";

const tableLabel = (table) => {
  if (table?.startsWith(REGION_TABLE_PREFIX)) {
    const code = table.slice(REGION_TABLE_PREFIX.length);
    return `${regionName(code) || "Region"} (${code})`;
  }
  if (table?.startsWith(COMUNE_TABLE_PREFIX)) {
    const code = table.slice(COMUNE_TABLE_PREFIX.length);
    return `${comuneName(code) || "Comune"} (${code})`;
  }
  return table || "—";
};

// `group` = "national" (§3/§4 IRPEF, detrazione, wedge) or "local" (§5
// surtax by tax domicile). The engine never interpolates or extends a band;
// a gap or overlap blocks the calculation.
export default function ITBandsTab({ group, pack, slabs, onReload, onDeleteSlab }) {
  const rules = useMemo(() => IT_BAND_RULES.filter((r) => r.group === group), [group]);
  const [rule, setRule] = useState(rules[0].rule);
  const [editing, setEditing] = useState(null);   // { slab?, initial? }
  const meta = ruleMeta(rule);

  const all = useMemo(() => (slabs || []).filter((s) => rules.some((r) => r.rule === s.ruleType)), [slabs, rules]);
  const rows = all.filter((s) => s.ruleType === rule).sort((a, b) =>
    String(a.taxTableNumber || "").localeCompare(String(b.taxTableNumber || "")) || Number(a.minAmount) - Number(b.minAmount));
  // Default national table code per rule = whatever this pack already uses.
  const defaultTables = useMemo(() => Object.fromEntries(
    IT_BAND_RULES.map((r) => [r.rule, (slabs || []).find((s) => s.ruleType === r.rule)?.taxTableNumber || ""])), [slabs]);
  const placeholders = all.filter((s) => (s.rateLabel || "").toLowerCase().includes("needs")).length;
  const editable = pack && pack.status !== "Active";

  const uncovered = group === "local"
    ? IT_LAUNCH_COMMUNI.filter(([code, , region]) =>
      !all.some((s) => s.ruleType === "IT_ADDREG" && s.taxTableNumber === `${REGION_TABLE_PREFIX}${region}`)
      || !all.some((s) => s.ruleType === "IT_ADDCOM" && s.taxTableNumber === `${COMUNE_TABLE_PREFIX}${code}`))
    : [];

  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        {group === "national"
          ? "Annual bands in EUR, (from, up to]. Detrazione lavoro and the wedge additional deduction are stored as a FIXED and a TAPERING row per band: amount = fixed + taper × (up to − income) / (up to − from)."
          : "Regional and municipal surtax by the employee's TAX DOMICILE — never the workplace (IT-013). Each region and comune needs its own brackets from the MEF database; a domicile with no bands blocks payroll rather than using a national rate (IT-012)."}
      </p>
      {group === "local" && uncovered.length > 0 && (
        <p role="status" className="rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-xs text-foreground-secondary">
          Launch communes with no regional or municipal brackets yet (payroll for workers domiciled there is blocked):{" "}
          {uncovered.map(([, name]) => name).join(", ")}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Band type" value={rule} onChange={(e) => setRule(e.target.value)}
          className="rounded-lg border border-border bg-background px-2 py-1 text-xs">
          {rules.map((r) => <option key={r.rule} value={r.rule}>{r.label}</option>)}
        </select>
        {placeholders > 0 && (
          <span className="text-xs text-warning">{placeholders} band(s) still marked as needing a source</span>
        )}
        {editable && (
          <button onClick={() => setEditing({ initial: { ruleType: rule } })}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
            <Plus size={13} /> Add band
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No bands of this type in this pack.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Table</th>
                <th className="px-3 py-2">From</th>
                <th className="px-3 py-2">Up to</th>
                <th className="px-3 py-2">{meta.value === "rate" ? "Rate" : "Amount"}</th>
                <th className="px-3 py-2">Label</th>
                <th className="px-3 py-2 w-16"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-t border-border-light">
                  <td className="px-3 py-2 text-foreground-secondary">{tableLabel(s.taxTableNumber)}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.minAmount}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{s.maxAmount ?? "and above"}</td>
                  <td className="px-3 py-2 font-medium text-foreground">
                    {meta.value === "rate" ? `${s.ratePct}%` : `EUR ${s.flatAmount ?? "—"}`}
                  </td>
                  <td className="px-3 py-2 text-foreground-muted">{s.rateLabel}</td>
                  <td className="px-3 py-2">
                    {editable && (
                      <div className="flex items-center gap-1">
                        <button aria-label="Edit band" onClick={() => setEditing({ slab: s })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                        <button aria-label="Delete band" onClick={() => onDeleteSlab(s)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <ITBandFormModal pack={pack} slab={editing.slab} initial={editing.initial} defaultTables={defaultTables}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onReload?.(); }} />
      )}
    </div>
  );
}
