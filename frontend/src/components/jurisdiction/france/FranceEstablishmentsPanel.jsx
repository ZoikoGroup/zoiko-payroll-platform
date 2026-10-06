import { useState } from "react";
import { MapPin, Plus, Pencil, AlertTriangle } from "lucide-react";
import Modal from "../../Modal";
import StatusPill from "../../StatusPill";
import { useToast } from "../../../context/ToastContext";
import {
  listFranceEstablishments, createFranceEstablishment, updateFranceEstablishment,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass, labelClass } from "../constants";
import { useFranceOrgData } from "./useFranceOrgData";

const BLANK = { siret: "", name: "", address: "", communeInsee: "", workforceLocation: "", payrollIdentifier: "", isActive: true };

// SIRET establishment registry (FR §11 panel B, FR-002). AT/MP and
// versement mobilité rate periods attach to an establishment (Employer
// Rates section). A SIRET is immutable once registered; an establishment is
// deactivated, never deleted, so its rate history and filings keep resolving.
export default function FranceEstablishmentsPanel({ organizationId }) {
  const { addToast } = useToast() || {};
  const { data, error, loading, reload } = useFranceOrgData(organizationId, listFranceEstablishments);
  const [editing, setEditing] = useState(null); // { id?, form }
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const establishments = Array.isArray(data) ? data : [];

  async function save() {
    const form = editing.form;
    const siret = form.siret.replace(/\s/g, "");
    if (!/^\d{14}$/.test(siret)) return setFormError("SIRET must be exactly 14 digits (SIREN + 5-digit NIC).");
    const commune = form.communeInsee.trim().toUpperCase();
    if (commune && !/^(\d{5}|2[AB]\d{3})$/.test(commune)) {
      return setFormError("Commune INSEE code is 5 characters (e.g. 75056, or 2A004 / 2B033 for Corsica).");
    }
    setFormError("");
    setSaving(true);
    try {
      const payload = { ...form, siret, communeInsee: commune || null };
      if (editing.id) await updateFranceEstablishment(editing.id, payload, { organizationId });
      else await createFranceEstablishment(payload, { organizationId });
      addToast?.(editing.id ? "Establishment updated." : "Establishment registered.", "success");
      setEditing(null);
      reload();
    } catch (err) {
      setFormError(loadErrorText(describeLoadError(err)));
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(est) {
    try {
      await updateFranceEstablishment(est.id, { ...est, isActive: !est.isActive }, { organizationId });
      addToast?.(est.isActive ? "Establishment deactivated." : "Establishment reactivated.", "success");
      reload();
    } catch (err) {
      addToast?.(loadErrorText(describeLoadError(err)), "error");
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to manage its establishments.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
            <MapPin size={15} className="text-primary" /> Establishments (§11 panel B)
          </h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            Each SIRET the employer pays from. Employer rates (AT/MP, versement mobilité, FNAL/CFP) attach per establishment.
          </p>
        </div>
        <button
          onClick={() => { setEditing({ form: { ...BLANK } }); setFormError(""); }}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add establishment
        </button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading establishments…</p>
      ) : error ? (
        <p className="py-8 text-center text-xs text-foreground-muted"><AlertTriangle size={14} className="inline mr-1" /> {loadErrorText(error)}</p>
      ) : establishments.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted py-10 text-center">
          <p className="text-xs text-foreground-disabled">No establishment registered — France launch needs at least one active SIRET.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">SIRET</th>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Commune (INSEE)</th>
                <th className="px-3 py-2">Workforce location</th>
                <th className="px-3 py-2">Payroll id</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {establishments.map((e) => (
                <tr key={e.id} className="border-t border-border-light">
                  <td className="px-3 py-2 font-mono font-semibold">{e.siret}</td>
                  <td className="px-3 py-2">{e.name || "—"}</td>
                  <td className="px-3 py-2 font-mono">{e.communeInsee || "—"}</td>
                  <td className="px-3 py-2">{e.workforceLocation || "—"}</td>
                  <td className="px-3 py-2 font-mono">{e.payrollIdentifier || "—"}</td>
                  <td className="px-3 py-2"><StatusPill status={e.isActive ? "active" : "inactive"} label={e.isActive ? "Active" : "Inactive"} /></td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button
                      onClick={() => {
                        setEditing({ id: e.id, form: {
                          siret: e.siret, name: e.name || "", address: e.address || "", communeInsee: e.communeInsee || "",
                          workforceLocation: e.workforceLocation || "", payrollIdentifier: e.payrollIdentifier || "", isActive: e.isActive,
                        } });
                        setFormError("");
                      }}
                      className="mr-1 inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted"
                    >
                      <Pencil size={11} /> Edit
                    </button>
                    <button onClick={() => toggleActive(e)} className="rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
                      {e.isActive ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <Modal title={editing.id ? "Edit establishment" : "Add establishment"} onClose={() => setEditing(null)}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {[
              { key: "siret", label: "SIRET (14 digits) *", placeholder: "55210055400021", disabled: Boolean(editing.id) },
              { key: "name", label: "Name", placeholder: "Paris HQ" },
              { key: "communeInsee", label: "Commune INSEE code", placeholder: "75056" },
              { key: "workforceLocation", label: "Workforce location", placeholder: "Paris 8e" },
              { key: "payrollIdentifier", label: "Establishment payroll id", placeholder: "Internal id" },
              { key: "address", label: "Address", placeholder: "Street, postcode, city" },
            ].map((f) => (
              <div key={f.key}>
                <label className={labelClass}>{f.label}</label>
                <input
                  className={inputClass} value={editing.form[f.key]} placeholder={f.placeholder} disabled={f.disabled}
                  onChange={(ev) => setEditing((s) => ({ ...s, form: { ...s.form, [f.key]: ev.target.value } }))}
                />
              </div>
            ))}
          </div>
          {editing.id && <p className="mt-2 text-[11px] text-foreground-disabled">A SIRET cannot change — register a new establishment instead.</p>}
          {formError && <p className="mt-2 text-xs text-error">{formError}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setEditing(null)} disabled={saving} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
