import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { listSwissTaxabilityRules, createSwissTaxabilityRule, approveSwissTaxabilityRule } from "../../../service/superAdminService";
import StatusPill from "../../StatusPill";
import { inputClass, labelClass } from "../constants";
import { CH_CANTON_CODES, CH_EARNING_TYPES, CH_TAXABILITY_COMPONENTS } from "./chComponentConfig";

const RULE_STATUS_PILL = { Draft: "pending", Approved: "approved" };

const EMPTY_FORM = {
  earningType: "base_salary", taxComponent: "ch_ahv", isTaxable: true, treatment: "",
  jurisdictionState: "", effectiveFrom: "", effectiveTo: "", sourceDocumentId: "", reason: "",
};

// CH earning classification (TaxabilityRule, platform rows). A rule only
// governs once Approved (service.get_taxability_classification filters CH
// reads on status == "Approved"); approving closes the previous Approved row
// for the same scope the day before. The G5 readiness gate checks these.
export default function CHTaxabilityTab({ addToast }) {
  const [rows, setRows] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [reason, setReason] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = () => {
    listSwissTaxabilityRules(statusFilter ? { status: statusFilter } : {})
      .then(setRows)
      .catch((e) => setError(e?.message || "Failed to load classification rules."));
  };
  useEffect(() => { load(); }, [statusFilter]);

  async function create() {
    setError(null);
    try {
      await createSwissTaxabilityRule({
        earningType: form.earningType, taxComponent: form.taxComponent, isTaxable: form.isTaxable,
        treatment: form.treatment || undefined, jurisdictionState: form.jurisdictionState || undefined,
        effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || undefined,
        sourceDocumentId: form.sourceDocumentId || undefined, reason: form.reason || undefined,
      });
      addToast?.("Classification created (Draft).", "success");
      setShowCreate(false); setForm(EMPTY_FORM); load();
    } catch (e) { setError(e?.message || "Create failed."); }
  }

  async function approve(rule) {
    setError(null);
    try {
      await approveSwissTaxabilityRule(rule.id, reason || null);
      addToast?.("Approved.", "success");
      setConfirming(null); setReason(""); load();
    } catch (e) { setError(e?.message || "Approval failed."); }
  }

  return (
    <section aria-labelledby="ch-class-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="ch-class-heading" className="text-sm font-semibold text-foreground">Earning classification (G5)</h3>
          <p className="text-xs text-foreground-muted">
            Which earnings count toward each CH obligation. Only Approved rows govern; the G5 readiness gate needs an
            Approved rule for every obligation except the wage floor. A changed classification is a new rule — approving
            it closes the overlapping Approved row for the same scope the day before.
          </p>
        </div>
        <button type="button" onClick={() => setShowCreate(true)}
          className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover">
          New rule
        </button>
      </div>

      <select className={inputClass + " w-auto"} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
        <option value="">All statuses</option>
        {["Draft", "Approved"].map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      {error && <p role="alert" className="text-xs text-error">{error}</p>}

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-foreground-muted">
              <th className="px-3 py-2 font-medium">Obligation</th>
              <th className="px-3 py-2 font-medium">Earning</th>
              <th className="px-3 py-2 font-medium">Taxable</th>
              <th className="px-3 py-2 font-medium">Treatment</th>
              <th className="px-3 py-2 font-medium">Scope / effective</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {rows.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-foreground-disabled">No classification rules yet.</td></tr>
            ) : rows.map((r) => (
              <tr key={r.id}>
                <td className="px-3 py-2 font-mono text-foreground">{r.taxComponent}</td>
                <td className="px-3 py-2 font-mono">{r.earningType}</td>
                <td className="px-3 py-2">{r.isTaxable ? <span className="text-success">included</span> : <span className="text-warning">excluded</span>}</td>
                <td className="px-3 py-2 font-mono text-foreground-muted">{r.treatment || "—"}</td>
                <td className="px-3 py-2 text-foreground-muted">
                  {r.jurisdictionState ? <span className="font-mono">{r.jurisdictionState}</span> : <span>CH-wide</span>}
                  <span> — {r.effectiveFrom}{r.effectiveTo ? ` → ${r.effectiveTo}` : ""}</span>
                </td>
                <td className="px-3 py-2"><StatusPill status={RULE_STATUS_PILL[r.status] || "pending"} label={r.status} /></td>
                <td className="px-3 py-2">
                  {r.status === "Draft" && (
                    <button type="button" onClick={() => setConfirming(r)}
                      className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 font-semibold text-foreground-secondary hover:bg-surface-muted">
                      <ShieldCheck size={12} /> Approve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <div className="rounded-xl border border-border p-4">
          <p className="mb-3 text-xs font-semibold text-foreground">New classification rule (Draft)</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass} htmlFor="cl-earn">Earning type</label>
              <select id="cl-earn" className={inputClass} value={form.earningType} onChange={(e) => setForm({ ...form, earningType: e.target.value })}>
                {CH_EARNING_TYPES.map(([v, l]) => <option key={v} value={v}>{v} — {l}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass} htmlFor="cl-comp">Obligation</label>
              <select id="cl-comp" className={inputClass} value={form.taxComponent} onChange={(e) => setForm({ ...form, taxComponent: e.target.value })}>
                {CH_TAXABILITY_COMPONENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass} htmlFor="cl-treat">Treatment (Lohnausweis box for ch_la)</label>
              <input id="cl-treat" className={inputClass} value={form.treatment} onChange={(e) => setForm({ ...form, treatment: e.target.value })} />
            </div>
            <div>
              <label className={labelClass} htmlFor="cl-state">Canton scope</label>
              <select id="cl-state" className={inputClass} value={form.jurisdictionState} onChange={(e) => setForm({ ...form, jurisdictionState: e.target.value })}>
                <option value="">CH-wide</option>
                {CH_CANTON_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div><label className={labelClass} htmlFor="cl-from">Effective from</label>
              <input id="cl-from" type="date" className={inputClass} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="cl-to">Effective to</label>
              <input id="cl-to" type="date" className={inputClass} value={form.effectiveTo} onChange={(e) => setForm({ ...form, effectiveTo: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="cl-src">Source artifact id (required to approve)</label>
              <input id="cl-src" type="number" className={inputClass} value={form.sourceDocumentId} onChange={(e) => setForm({ ...form, sourceDocumentId: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="cl-reason">Reason</label>
              <input id="cl-reason" className={inputClass} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></div>
            <label className="flex items-center gap-2 text-xs text-foreground-secondary sm:col-span-1">
              <input type="checkbox" className="h-4 w-4" checked={form.isTaxable} onChange={(e) => setForm({ ...form, isTaxable: e.target.checked })} />
              Earning counts toward the obligation
            </label>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button type="button" onClick={create} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover">Create</button>
            <button type="button" onClick={() => { setShowCreate(false); setError(null); setForm(EMPTY_FORM); }}
              className="rounded-lg border border-border px-3 py-2 text-xs text-foreground-muted hover:bg-surface-muted">Cancel</button>
          </div>
        </div>
      )}

      {confirming && (
        <div className="rounded-xl border border-warning/40 bg-warning-light p-4">
          <p className="text-xs font-semibold text-foreground">
            Approve {confirming.earningType} → {confirming.taxComponent}? A Super Admin other than its author must
            approve, and a source document is required.
          </p>
          <input className={inputClass + " mt-2"} placeholder="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="mt-3 flex items-center gap-2">
            <button type="button" onClick={() => approve(confirming)} className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">Confirm approve</button>
            <button type="button" onClick={() => { setConfirming(null); setReason(""); }}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-foreground-muted hover:bg-surface-muted">Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}