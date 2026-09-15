import { useState, useEffect } from "react";
import { Plus, Trash2 } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { bulkImportStateTaxPack, getSourceArtifacts } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { US_FILING_STATUSES } from "./usaComponentConfig";

// "New State Import" (Production-Readiness Plan Phase 3) — a single-submit
// alternative to creating an empty pack (USANewPackModal) and then adding
// each bracket/standard-deduction row one at a time through
// USStateAccordionRow's per-component editor. Reuses the exact same
// Draft->Approved->Active JurisdictionPack lifecycle and publish gates
// every other US pack already goes through — this only replaces the DATA
// ENTRY step, not the review/publish workflow that follows it.

const EMPTY_BRACKET_ROW = { filingStatus: "", minAmount: "0", maxAmount: "", ratePct: "" };
const EMPTY_DEDUCTION_ROW = { filingStatus: "", label: "", flatAmount: "" };

export default function USAStateTaxBulkImportModal({ onClose, onImported }) {
  const { addToast } = useToast() || {};
  const [state, setState] = useState("");
  const [version, setVersion] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [sourceDocumentId, setSourceDocumentId] = useState("");
  const [sources, setSources] = useState([]);
  const [bracketRows, setBracketRows] = useState([{ ...EMPTY_BRACKET_ROW }]);
  const [deductionRows, setDeductionRows] = useState([{ ...EMPTY_DEDUCTION_ROW }]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSourceArtifacts().then(setSources).catch(() => setSources([]));
  }, []);

  function updateBracket(i, field, value) {
    setBracketRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }
  function updateDeduction(i, field, value) {
    setDeductionRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }

  async function save() {
    if (!state.trim()) { addToast?.("A state code is required.", "error"); return; }
    if (!version.trim()) { addToast?.("Version label is required.", "error"); return; }
    const cleanBrackets = bracketRows.filter((r) => r.minAmount !== "" && r.ratePct !== "");
    if (cleanBrackets.length === 0) { addToast?.("At least one bracket row (min amount + rate) is required.", "error"); return; }
    const cleanDeductions = deductionRows.filter((r) => r.flatAmount !== "");

    setSaving(true);
    try {
      const created = await bulkImportStateTaxPack({
        jurisdictionState: state.trim().toUpperCase(),
        version: version.trim(),
        effectiveFrom: effectiveFrom || null,
        sourceDocumentId: sourceDocumentId ? Number(sourceDocumentId) : null,
        bracketRows: cleanBrackets.map((r) => ({
          filingStatus: r.filingStatus || null,
          minAmount: r.minAmount,
          maxAmount: r.maxAmount === "" ? null : r.maxAmount,
          ratePct: r.ratePct,
        })),
        standardDeductionRows: cleanDeductions.map((r) => ({
          filingStatus: r.filingStatus || null,
          label: r.label || null,
          flatAmount: r.flatAmount,
        })),
      });
      addToast?.(`Draft pack created for ${created.jurisdictionState} — ${cleanBrackets.length} bracket row(s) imported.`, "success");
      onImported(created);
    } catch (err) {
      addToast?.(err.message || "Import failed.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="New State Import — Bulk Tax Data" onClose={onClose} maxWidth="max-w-4xl">
      <p className="mb-4 text-xs text-foreground-muted">
        Creates a brand-new Draft pack for this state, pre-populated with its full bracket table and standard
        deduction — the same Approve/Publish lifecycle and gates (source evidence, effective date, distinct
        approver, golden-test variance) still apply before it goes Active.
      </p>

      <div className="grid grid-cols-4 gap-3">
        <div>
          <label className={labelClass}>State</label>
          <input className={inputClass} value={state} onChange={(e) => setState(e.target.value.toUpperCase())} placeholder="e.g. KS" maxLength={2} />
        </div>
        <div>
          <label className={labelClass}>Version Label</label>
          <input className={inputClass} value={version} onChange={(e) => setVersion(e.target.value)} placeholder="e.g. 2026.1" />
        </div>
        <div>
          <label className={labelClass}>Effective From (set before Activate)</label>
          <input type="date" className={inputClass} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </div>
        <div>
          <label className={labelClass}>Source Evidence (optional)</label>
          <select className={inputClass} value={sourceDocumentId} onChange={(e) => setSourceDocumentId(e.target.value)}>
            <option value="">No source linked</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
          </select>
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <label className={labelClass}>Tax Brackets</label>
          <button onClick={() => setBracketRows((rs) => [...rs, { ...EMPTY_BRACKET_ROW }])} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-foreground-secondary hover:bg-surface-muted">
            <Plus size={12} /> Add Row
          </button>
        </div>
        <div className="max-h-56 space-y-2 overflow-y-auto">
          {bracketRows.map((r, i) => (
            <div key={i} className="grid grid-cols-12 items-center gap-1.5">
              <select className={inputClass + " col-span-3"} value={r.filingStatus} onChange={(e) => updateBracket(i, "filingStatus", e.target.value)}>
                <option value="">(any / not filing-status-specific)</option>
                {US_FILING_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <input className={inputClass + " col-span-2"} placeholder="Min amount" value={r.minAmount} onChange={(e) => updateBracket(i, "minAmount", e.target.value)} />
              <input className={inputClass + " col-span-2"} placeholder="Max amount (blank = and above)" value={r.maxAmount} onChange={(e) => updateBracket(i, "maxAmount", e.target.value)} />
              <input className={inputClass + " col-span-2"} placeholder="Rate %" value={r.ratePct} onChange={(e) => updateBracket(i, "ratePct", e.target.value)} />
              <button onClick={() => setBracketRows((rs) => rs.filter((_, idx) => idx !== i))} disabled={bracketRows.length === 1} className="col-span-1 rounded-md p-1.5 text-error hover:bg-error-light disabled:opacity-30">
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <label className={labelClass}>Standard Deduction (optional)</label>
          <button onClick={() => setDeductionRows((rs) => [...rs, { ...EMPTY_DEDUCTION_ROW }])} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-foreground-secondary hover:bg-surface-muted">
            <Plus size={12} /> Add Row
          </button>
        </div>
        <div className="max-h-40 space-y-2 overflow-y-auto">
          {deductionRows.map((r, i) => (
            <div key={i} className="grid grid-cols-12 items-center gap-1.5">
              <select className={inputClass + " col-span-3"} value={r.filingStatus} onChange={(e) => updateDeduction(i, "filingStatus", e.target.value)}>
                <option value="">(any / not filing-status-specific)</option>
                {US_FILING_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <input className={inputClass + " col-span-5"} placeholder="Label (optional)" value={r.label} onChange={(e) => updateDeduction(i, "label", e.target.value)} />
              <input className={inputClass + " col-span-3"} placeholder="Flat amount" value={r.flatAmount} onChange={(e) => updateDeduction(i, "flatAmount", e.target.value)} />
              <button onClick={() => setDeductionRows((rs) => rs.filter((_, idx) => idx !== i))} disabled={deductionRows.length === 1} className="col-span-1 rounded-md p-1.5 text-error hover:bg-error-light disabled:opacity-30">
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Importing…" : "Import as Draft"}</button>
      </div>
    </Modal>
  );
}
