import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { Plus, Pencil, Trash2 } from "lucide-react";
import Modal from "../../../Modal";
import ConfirmDialog from "../../../ConfirmDialog";
import { useToast } from "../../../../context/ToastContext";
import {
  getReportsOrganizations, getEmployerTaxProfiles,
  upsertEmployerTaxProfile, deleteEmployerTaxProfile, getSourceArtifacts,
} from "../../../../service/superAdminService";
import { inputClass, labelClass } from "../../constants";
import { toUsJurisdictionCode } from "./usStateAbbreviations";

// Mini, state-scoped view of SuiEmployerRatesPanel's data (that file itself
// untouched) — EmployerTaxProfile rows are org-scoped, not state-scoped, so
// an organization must still be picked first; results are then filtered
// client-side to this state's jurisdiction code. Full cross-state
// management stays reachable on the platform-wide "SUI Employer Rates" tab
// (linked below), per the "mini org-picker inside the row" decision.
export default function USStateSuiSection({ stateName }) {
  const { addToast } = useToast() || {};
  const [orgs, setOrgs] = useState([]);
  const [organizationId, setOrganizationId] = useState("");
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const code = toUsJurisdictionCode(stateName);

  useEffect(() => {
    getReportsOrganizations({ country: "US", limit: 200 })
      .then((res) => setOrgs(res.items || []))
      .catch(() => setOrgs([]));
  }, []);

  const loadProfiles = useCallback(() => {
    if (!organizationId) { setProfiles([]); return; }
    setLoading(true);
    getEmployerTaxProfiles({ organizationId }).then(setProfiles).finally(() => setLoading(false));
  }, [organizationId]);

  useEffect(() => { loadProfiles(); }, [loadProfiles]);

  const filtered = code ? profiles.filter((p) => p.jurisdictionId === code) : profiles;

  return (
    <div>
      <div className="mb-3 flex items-start justify-between gap-3 flex-wrap">
        <p className="text-xs text-foreground-muted">
          Tenant-specific, agency-assigned SUI/employer rates for {stateName} — pick an organization to view its rates.
        </p>
        <Link to="/super-admin/compliance/united-states?section=sui" className="shrink-0 text-xs font-semibold text-primary hover:underline">
          Manage all organizations →
        </Link>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <select className={inputClass + " w-auto min-w-[240px]"} value={organizationId} onChange={(e) => setOrganizationId(e.target.value)}>
          <option value="">Select an organization…</option>
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.organizationName} ({o.organizationCode})</option>)}
        </select>
        <button
          onClick={() => setShowForm(true)}
          disabled={!organizationId}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Plus size={13} /> Add Profile
        </button>
      </div>

      {!organizationId ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">Select an organization to view its {stateName} SUI/employer-specific rates.</p>
      ) : loading ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">No {stateName} employer-specific tax profile configured for this organization yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="px-3 py-2.5">Component</th>
                <th className="px-3 py-2.5">Wage Base</th>
                <th className="px-3 py-2.5">Employer Rate</th>
                <th className="px-3 py-2.5">Source</th>
                <th className="px-3 py-2.5">Effective</th>
                <th className="px-3 py-2.5">Agency Account</th>
                <th className="px-3 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.id} className="border-b border-border-light last:border-0">
                  <td className="px-3 py-2.5">{p.componentCode}</td>
                  <td className="px-3 py-2.5">{p.taxableWageBase}</td>
                  <td className="px-3 py-2.5">{p.employerRatePct}%</td>
                  <td className="px-3 py-2.5">{p.rateSource}</td>
                  <td className="px-3 py-2.5 text-foreground-muted">{p.effectiveFrom} → {p.effectiveTo || "open"}</td>
                  <td className="px-3 py-2.5 font-mono text-foreground-disabled">{p.agencyAccountId || "—"}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => setEditing(p)} className="rounded-md p-1.5 text-foreground-muted hover:bg-surface-muted"><Pencil size={13} /></button>
                      <button onClick={() => setDeleting(p)} className="rounded-md p-1.5 text-error hover:bg-error-light"><Trash2 size={13} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(showForm || editing) && (
        <USStateSuiProfileFormModal
          organizationId={organizationId} profile={editing} defaultJurisdictionId={code || "US-"}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); loadProfiles(); }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete Employer Tax Profile"
          message={`Delete the ${deleting.componentCode} profile for ${deleting.jurisdictionId}? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteEmployerTaxProfile(deleting.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeleting(null);
            loadProfiles();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

// Deliberately a local copy, not an import from SuiEmployerRatesPanel.jsx —
// that file's form modal is a private, unexported function and the file is
// on the "must not modify" list, so exporting it wasn't an option.
function USStateSuiProfileFormModal({ organizationId, profile, defaultJurisdictionId, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [sources, setSources] = useState([]);
  const [form, setForm] = useState({
    jurisdictionId: profile?.jurisdictionId || defaultJurisdictionId,
    componentCode: profile?.componentCode || "SUI",
    taxableWageBase: profile?.taxableWageBase ?? "",
    employerRatePct: profile?.employerRatePct ?? "",
    rateSource: profile?.rateSource || "EMPLOYER_NOTICE",
    effectiveFrom: profile?.effectiveFrom || "",
    effectiveTo: profile?.effectiveTo || "",
    agencyAccountId: profile?.agencyAccountId || "",
    reimbursableStatus: profile?.reimbursableStatus || "CONTRIBUTORY",
    sourceDocumentId: profile?.sourceDocumentId || "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  useEffect(() => { getSourceArtifacts().then(setSources).catch(() => setSources([])); }, []);

  async function save() {
    if (!form.jurisdictionId.trim() || form.taxableWageBase === "" || form.employerRatePct === "" || !form.effectiveFrom) {
      addToast?.("Jurisdiction, wage base, employer rate, and effective-from date are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertEmployerTaxProfile({
        id: profile?.id, organizationId: Number(organizationId),
        jurisdictionId: form.jurisdictionId, componentCode: form.componentCode,
        taxableWageBase: form.taxableWageBase, employerRatePct: form.employerRatePct,
        rateSource: form.rateSource, effectiveFrom: form.effectiveFrom,
        effectiveTo: form.effectiveTo || null, agencyAccountId: form.agencyAccountId || null,
        reimbursableStatus: form.reimbursableStatus,
        sourceDocumentId: form.sourceDocumentId ? Number(form.sourceDocumentId) : null,
      });
      addToast?.("Employer tax profile saved.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={profile ? "Edit Employer Tax Profile" : "Add Employer Tax Profile"} onClose={onClose} maxWidth="max-w-lg">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Jurisdiction</label><input className={inputClass} value={form.jurisdictionId} onChange={set("jurisdictionId")} placeholder="US-CA" /></div>
        <div><label className={labelClass}>Component</label>
          <select className={inputClass} value={form.componentCode} onChange={set("componentCode")}>
            <option value="SUI">SUI</option>
            <option value="ETT">ETT</option>
            <option value="WF">WF</option>
            <option value="JDA">JDA</option>
          </select>
        </div>
        <div><label className={labelClass}>Taxable Wage Base</label><input className={inputClass} value={form.taxableWageBase} onChange={set("taxableWageBase")} placeholder="7000" /></div>
        <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={form.employerRatePct} onChange={set("employerRatePct")} placeholder="3.40" /></div>
        <div><label className={labelClass}>Rate Source</label>
          <select className={inputClass} value={form.rateSource} onChange={set("rateSource")}>
            <option value="STATE_DEFAULT">State Default</option>
            <option value="NEW_EMPLOYER">New Employer</option>
            <option value="EMPLOYER_NOTICE">Employer Notice</option>
          </select>
        </div>
        <div><label className={labelClass}>Reimbursable Status</label>
          <select className={inputClass} value={form.reimbursableStatus} onChange={set("reimbursableStatus")}>
            <option value="CONTRIBUTORY">Contributory</option>
            <option value="REIMBURSING">Reimbursing</option>
          </select>
        </div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></div>
        <div><label className={labelClass}>Effective To (optional)</label><input type="date" className={inputClass} value={form.effectiveTo} onChange={set("effectiveTo")} /></div>
        <div className="col-span-2"><label className={labelClass}>Agency Account ID (from the rate notice)</label><input className={inputClass} value={form.agencyAccountId} onChange={set("agencyAccountId")} /></div>
        <div className="col-span-2">
          <label className={labelClass}>Source Evidence (optional)</label>
          <select className={inputClass} value={form.sourceDocumentId} onChange={set("sourceDocumentId")}>
            <option value="">No source linked</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
          </select>
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
