import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import {
  listCollectiveAgreements, setCollectiveAgreementStatus, upsertCollectiveAgreement,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { SE_CBA_MODULES, SE_CBA_TYPES } from "./seComponentConfig";

// Collective-agreement registry (spec §9/§13). Sweden has no statutory
// minimum wage and no national default agreement: an employer with no
// assignment resolves to an explicit NONE. Every agreement is a governed,
// versioned rule package — Draft → In Review → Approved → Active, with a
// distinct approver and a distinct activator (enforced server-side; the
// buttons below only send the request).
const NEXT = {
  Draft: [["In Review", "Submit for review"]],
  "In Review": [["Approved", "Approve"], ["Draft", "Return to Draft"]],
  Approved: [["Active", "Activate"], ["Draft", "Return to Draft"]],
  Active: [["Superseded", "Supersede"]],
  Superseded: [],
};

const EMPTY = {
  agreementCode: "", name: "", agreementType: "SECTOR", employerScope: "", employeeGroup: "",
  version: "1.0", effectiveFrom: "", effectiveTo: "", modules: [], sourceDocumentId: "", notes: "", reason: "",
};

function AgreementForm({ agreement, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState(() => (agreement ? {
    ...EMPTY, ...agreement, effectiveFrom: agreement.effectiveFrom || "", effectiveTo: agreement.effectiveTo || "",
    sourceDocumentId: agreement.sourceDocumentId ?? "", modules: agreement.modules || [], reason: "",
  } : EMPTY));
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const toggleModule = (m) => setForm((f) => ({
    ...f, modules: f.modules.includes(m) ? f.modules.filter((x) => x !== m) : [...f.modules, m],
  }));

  async function save() {
    if (!form.agreementCode.trim() || !form.name.trim()) {
      addToast?.("Agreement code and name are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCollectiveAgreement({
        id: agreement?.id, jurisdictionCountry: "SE", organizationId: null,
        agreementCode: form.agreementCode.trim(), name: form.name.trim(), agreementType: form.agreementType,
        employerScope: form.employerScope || null, employeeGroup: form.employeeGroup || null,
        version: form.version || "1.0",
        effectiveFrom: form.effectiveFrom || null, effectiveTo: form.effectiveTo || null,
        modules: form.modules, sourceDocumentId: form.sourceDocumentId === "" ? null : Number(form.sourceDocumentId),
        notes: form.notes || null, reason: form.reason || null,
      });
      addToast?.("Agreement saved as Draft.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save agreement.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`${agreement ? "Edit" : "New"} collective agreement`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div><label className={labelClass} htmlFor="cba-code">Agreement code</label>
            <input id="cba-code" className={inputClass} value={form.agreementCode} onChange={set("agreementCode")} placeholder="SE-SECTOR-TEKNIK-2026" /></div>
          <div><label className={labelClass} htmlFor="cba-version">Version</label>
            <input id="cba-version" className={inputClass} value={form.version} onChange={set("version")} /></div>
          <div><label className={labelClass} htmlFor="cba-type">Type</label>
            <select id="cba-type" className={inputClass} value={form.agreementType} onChange={set("agreementType")}>
              {SE_CBA_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ").toLowerCase()}</option>)}
            </select></div>
        </div>
        <div><label className={labelClass} htmlFor="cba-name">Name</label>
          <input id="cba-name" className={inputClass} value={form.name} onChange={set("name")} /></div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div><label className={labelClass} htmlFor="cba-scope">Employer scope</label>
            <input id="cba-scope" className={inputClass} value={form.employerScope || ""} onChange={set("employerScope")} /></div>
          <div><label className={labelClass} htmlFor="cba-group">Employee group</label>
            <input id="cba-group" className={inputClass} value={form.employeeGroup || ""} onChange={set("employeeGroup")} /></div>
          <div><label className={labelClass} htmlFor="cba-from">Effective from</label>
            <input id="cba-from" type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
          <div><label className={labelClass} htmlFor="cba-to">Effective to (optional)</label>
            <input id="cba-to" type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
          <div><label className={labelClass} htmlFor="cba-source">Source evidence artifact id</label>
            <input id="cba-source" className={inputClass} inputMode="numeric" value={form.sourceDocumentId} onChange={set("sourceDocumentId")} /></div>
        </div>
        <fieldset>
          <legend className={labelClass}>Configured modules (an agreement with none has no payroll effect)</legend>
          <div className="flex flex-wrap gap-2">
            {SE_CBA_MODULES.map((m) => (
              <label key={m} className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-xs text-foreground-secondary">
                <input type="checkbox" checked={form.modules.includes(m)} onChange={() => toggleModule(m)} />
                {m.replace(/_/g, " ")}
              </label>
            ))}
          </div>
        </fieldset>
        <div><label className={labelClass} htmlFor="cba-reason">Reason (recorded in the audit trail)</label>
          <textarea id="cba-reason" rows={2} className={inputClass} value={form.reason} onChange={set("reason")} /></div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-foreground-secondary hover:bg-surface-muted">Cancel</button>
          <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
            {saving ? "Saving…" : "Save Draft"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function SEAgreementsTab() {
  const { addToast } = useToast() || {};
  const [reloadKey, setReloadKey] = useState(0);
  const [result, setResult] = useState({ key: null, rows: [], error: null });
  const [editing, setEditing] = useState(null);   // null | {} (new) | agreement
  const load = () => setReloadKey((k) => k + 1);

  // Same pattern as useSgStatutorySummary: `loading` is derived from which
  // request the stored result belongs to, so the effect never sets state
  // synchronously.
  useEffect(() => {
    let live = true;
    listCollectiveAgreements({ country: "SE" })
      .then((data) => { if (live) setResult({ key: reloadKey, rows: data || [], error: null }); })
      .catch((e) => { if (live) setResult({ key: reloadKey, rows: [], error: e?.message || "Failed to load agreements." }); });
    return () => { live = false; };
  }, [reloadKey]);
  const loading = result.key !== reloadKey;
  const rows = loading ? [] : result.rows;

  async function move(row, status) {
    try {
      await setCollectiveAgreementStatus(row.id, status, null);
      addToast?.(`${row.agreementCode} v${row.version} → ${status}.`, "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Status change refused.", "error");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-foreground-muted">
          Sweden has no statutory minimum wage and no national default agreement. Wage floors, overtime, sickness
          and parental supplements, vacation enhancements, occupational pension and insurance come only from an
          agreement recorded here and assigned to an employer. Employers without one resolve to an explicit NONE.
        </p>
        <button onClick={() => setEditing({})}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> New agreement
        </button>
      </div>
      {loading ? (
        <p className="text-xs text-foreground-muted">Loading…</p>
      ) : result.error ? (
        <p role="alert" className="text-xs text-error">{result.error}</p>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">
          No collective agreements recorded. This is the correct state until a certified agreement is added.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr><th className="px-3 py-2">Code</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Effective</th><th className="px-3 py-2">Modules</th><th className="px-3 py-2">Status</th>
                <th className="px-3 py-2"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border-light align-top">
                  <td className="px-3 py-2 font-mono text-foreground">{r.agreementCode} v{r.version}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.name}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.agreementType}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.effectiveFrom || "—"} → {r.effectiveTo || "open"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{(r.modules || []).join(", ") || "none"}</td>
                  <td className="px-3 py-2 font-semibold text-foreground">{r.status}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      {r.status === "Draft" && (
                        <button onClick={() => setEditing(r)} className="text-primary hover:underline">Edit</button>
                      )}
                      {(NEXT[r.status] || []).map(([status, label]) => (
                        <button key={status} onClick={() => move(r, status)} className="text-primary hover:underline">{label}</button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <AgreementForm agreement={editing.id ? editing : null} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}
