import { useState } from "react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { upsertCanonicalTaxSlab } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { COMUNE_TABLE_PREFIX, IT_BAND_RULES, IT_REGIONS, REGION_TABLE_PREFIX, ruleMeta } from "./itComponentConfig";

// Add/Edit one Italian band. The generic SlabFormModal has no table-code or
// amount field and would clear flatAmount, so Italy has its own form writing
// through the SAME canonical upsertCanonicalTaxSlab endpoint.
//
// Bands are (from, up to]: "up to €28,000" includes €28,000 (§3). A rate band
// stores its percentage; an amount band (detrazione / deduction parts,
// exemption thresholds) stores EUR. The table code says WHICH table: a
// national code such as IRPEF26, or the tax domicile — REG_<ISTAT code> for a
// region, COM_<cadastral code> for a comune (IT-013).
const tableParts = (rule, table) => {
  const meta = ruleMeta(rule);
  if (meta?.table === "region") return table?.startsWith(REGION_TABLE_PREFIX) ? table.slice(REGION_TABLE_PREFIX.length) : "";
  if (meta?.table === "comune") return table?.startsWith(COMUNE_TABLE_PREFIX) ? table.slice(COMUNE_TABLE_PREFIX.length) : "";
  return table || "";
};

export default function ITBandFormModal({ pack, slab, initial = {}, defaultTables = {}, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const seed = { ...initial, ...(slab || {}) };
  const startRule = seed.ruleType || IT_BAND_RULES[0].rule;
  const [form, setForm] = useState({
    rule: startRule,
    table: tableParts(startRule, seed.taxTableNumber) || (ruleMeta(startRule)?.table === "national" ? defaultTables[startRule] || "" : ""),
    minAmount: seed.minAmount ?? "",
    maxAmount: seed.maxAmount ?? "",
    value: (ruleMeta(startRule)?.value === "amount" ? seed.flatAmount : seed.ratePct) ?? "",
    label: seed.rateLabel || "",
    reason: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const meta = ruleMeta(form.rule);
  const set = (field) => (e) => { setForm((f) => ({ ...f, [field]: e.target.value })); setError(null); };
  const changeRule = (e) => {
    const rule = e.target.value;
    const next = ruleMeta(rule);
    setForm((f) => ({ ...f, rule, table: next.table === "national" ? defaultTables[rule] || "" : (next.table === meta.table ? f.table : "") }));
  };

  async function save() {
    const problems = [];
    const table = form.table.trim().toUpperCase();
    if (meta.table === "region" && !IT_REGIONS.some(([c]) => c === table)) problems.push("Choose the region.");
    if (meta.table === "comune" && !/^[A-Z]\d{3}$/.test(table)) problems.push("Enter the comune's cadastral code (e.g. F205).");
    if (meta.table === "national" && !/^[A-Z0-9_]{1,10}$/.test(table)) problems.push("Enter the table code (up to 10 characters, e.g. IRPEF26).");
    if (form.minAmount === "") problems.push("Enter the band's lower bound.");
    if (form.value === "") problems.push(meta.value === "rate" ? "Enter the percentage." : "Enter the amount.");
    if (!form.reason.trim()) problems.push("A reason citing the source (MEF / law) is required.");
    if (problems.length) { setError(problems.join(" ")); return; }
    const taxTableNumber = meta.table === "region" ? `${REGION_TABLE_PREFIX}${table}`
      : meta.table === "comune" ? `${COMUNE_TABLE_PREFIX}${table}` : table;
    const label = (form.label.trim() || `${meta.label} — ${taxTableNumber} from ${form.minAmount}`).slice(0, 150);
    setSaving(true);
    try {
      await upsertCanonicalTaxSlab({
        id: slab?.id, jurisdictionPackId: pack.id, jurisdictionCountry: "IT", jurisdictionState: null,
        ruleType: form.rule, taxTableNumber, taxColumn: null,
        minAmount: form.minAmount, maxAmount: form.maxAmount === "" ? null : form.maxAmount,
        ratePct: meta.value === "rate" ? form.value : "0",
        flatAmount: meta.value === "amount" ? form.value : null,
        rateLabel: label, taxFormula: label, sortOrder: slab?.sortOrder ?? 0, reason: form.reason,
      });
      addToast?.("Band saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save the band.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`${slab ? "Edit" : "Add"} Italian tax band`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div><label className={labelClass} htmlFor="it-band-rule">Band type</label>
            <select id="it-band-rule" className={inputClass} value={form.rule} onChange={changeRule} disabled={Boolean(slab)}>
              {IT_BAND_RULES.map((r) => <option key={r.rule} value={r.rule}>{r.label}</option>)}
            </select></div>
          {meta.table === "region" ? (
            <div><label className={labelClass} htmlFor="it-band-region">Region (tax domicile)</label>
              <select id="it-band-region" className={inputClass} value={form.table} onChange={set("table")}>
                <option value="">Select…</option>
                {IT_REGIONS.map(([c, n]) => <option key={c} value={c}>{c} — {n}</option>)}
              </select></div>
          ) : (
            <div><label className={labelClass} htmlFor="it-band-table">{meta.table === "comune" ? "Comune cadastral code (tax domicile)" : "Table code"}</label>
              <input id="it-band-table" className={inputClass} value={form.table} onChange={set("table")}
                placeholder={meta.table === "comune" ? "F205" : "IRPEF26"} /></div>
          )}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div><label className={labelClass} htmlFor="it-band-min">From (EUR a year, exclusive)</label>
            <input id="it-band-min" className={inputClass} inputMode="decimal" value={form.minAmount} onChange={set("minAmount")} /></div>
          <div><label className={labelClass} htmlFor="it-band-max">Up to (EUR, inclusive; blank = no limit)</label>
            <input id="it-band-max" className={inputClass} inputMode="decimal" value={form.maxAmount} onChange={set("maxAmount")} /></div>
          <div><label className={labelClass} htmlFor="it-band-value">{meta.value === "rate" ? "Rate (%)" : "Amount (EUR)"}</label>
            <input id="it-band-value" className={inputClass} inputMode="decimal" value={form.value} onChange={set("value")} /></div>
        </div>
        <div><label className={labelClass} htmlFor="it-band-label">Label (optional)</label>
          <input id="it-band-label" className={inputClass} value={form.label} onChange={set("label")} /></div>
        <div><label className={labelClass} htmlFor="it-band-reason">Reason and source (recorded in the audit trail)</label>
          <textarea id="it-band-reason" rows={2} className={inputClass} value={form.reason} onChange={set("reason")}
            placeholder="e.g. MEF addizionale comunale database, Milano 2026 delibera" /></div>
        {error && <p role="alert" className="text-sm font-medium text-error">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-foreground-secondary hover:bg-surface-muted">Cancel</button>
          <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
