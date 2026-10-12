import { useState } from "react";
import { Users, AlertTriangle, History } from "lucide-react";
import StatusPill from "../../StatusPill";
import { useToast } from "../../../context/ToastContext";
import {
  getFranceEmployerProfile, recordFranceEffectif, correctFranceEffectif,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass, labelClass } from "../constants";
import { EFFECTIF_SOURCES, effectifHistory, latestEffectif } from "./franceStatutoryConfig";
import { useFranceOrgData } from "./useFranceOrgData";

// Governed annual effectif with threshold history (FR-015/FR-036). A new
// year is RECORDED; an already-recorded year is CORRECTED with a reason, and
// the previous value stays in that year's history — never overwritten.
// Thresholds: 11+ (CFP class, versement mobilité) and 50+ (FNAL class,
// RGDU Tdelta, M5 due date).
export default function FranceEffectifPanel({ organizationId }) {
  const { addToast } = useToast() || {};
  const { data: profile, error, loading, setData } = useFranceOrgData(organizationId, getFranceEmployerProfile);
  const [form, setForm] = useState({ year: String(new Date().getFullYear() - 1), value: "", source: "DSN", reason: "" });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const history = effectifHistory(profile?.effectifState);
  const latest = latestEffectif(profile?.effectifState);
  const yearNumber = form.year === "" ? null : Number(form.year);
  const correcting = history.some((h) => h.year === yearNumber);

  async function submit() {
    if (yearNumber == null || !Number.isInteger(yearNumber) || yearNumber < 2000 || yearNumber > new Date().getFullYear() + 1) {
      return setFormError("Enter a plausible year.");
    }
    const value = Number(form.value);
    if (form.value === "" || !Number.isInteger(value) || value < 0) return setFormError("Effectif must be a whole number ≥ 0.");
    if (correcting && !form.reason.trim()) return setFormError("A correction needs a reason — it is kept in the history.");
    setFormError("");
    setSaving(true);
    try {
      const payload = { year: yearNumber, value, source: form.source };
      const updated = correcting
        ? await correctFranceEffectif({ ...payload, reason: form.reason.trim() }, { organizationId })
        : await recordFranceEffectif(payload, { organizationId });
      setData(updated);
      setForm((f) => ({ ...f, value: "", reason: "" }));
      addToast?.(correcting ? `Effectif ${yearNumber} corrected (previous value kept in history).` : "Effectif recorded.", "success");
    } catch (err) {
      setFormError(loadErrorText(describeLoadError(err)));
    } finally {
      setSaving(false);
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to manage its governed effectif.</p>;
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
          <Users size={15} className="text-primary" /> Governed effectif (FR-015/FR-036)
        </h2>
        <p className="mt-0.5 text-xs text-foreground-muted">
          Annual average headcount from a governed source. Drives the 11-employee (CFP, versement mobilité) and 50-employee
          (FNAL, RGDU, M5 filing) thresholds.
        </p>
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading effectif history…</p>
      ) : error ? (
        <p className="py-8 text-center text-xs text-foreground-muted"><AlertTriangle size={14} className="inline mr-1" /> {loadErrorText(error)}</p>
      ) : !profile ? (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted py-10 text-center">
          <p className="text-xs text-foreground-disabled">Set up the Employer Profile first — effectif is recorded on it.</p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className={labelClass}>Year *</label>
                <input type="number" min="2000" className={inputClass} value={form.year}
                  onChange={(e) => setForm((f) => ({ ...f, year: e.target.value }))} />
              </div>
              <div>
                <label className={labelClass}>Annual average effectif *</label>
                <input type="number" min="0" step="1" className={inputClass} value={form.value} placeholder="e.g. 47"
                  onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} />
              </div>
              <div>
                <label className={labelClass}>Governed source</label>
                <select className={inputClass} value={form.source} onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}>
                  {EFFECTIF_SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              {correcting && (
                <div className="md:col-span-3">
                  <label className={labelClass}>Reason for correction *</label>
                  <input className={inputClass} value={form.reason} placeholder="e.g. Urssaf recount notice of 12/03"
                    onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
                </div>
              )}
            </div>
            {correcting && (
              <p className="mt-3 flex items-center gap-1.5 text-[11px] font-semibold text-warning">
                <History size={13} /> {yearNumber} is already recorded — this saves a correction; the current value moves to that year&apos;s history.
              </p>
            )}
            <div className="mt-4 flex items-center gap-3">
              <button onClick={submit} disabled={saving}
                className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-bold text-white disabled:opacity-40">
                {saving ? "Saving…" : correcting ? "Save correction" : "Record effectif"}
              </button>
              {formError && <span className="inline-flex items-center gap-1 text-xs font-semibold text-error"><AlertTriangle size={13} /> {formError}</span>}
            </div>
          </div>

          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold text-foreground">Threshold history (newest first)</p>
              {latest && <span className="text-[11px] text-foreground-muted">Latest: {latest.year} · {latest.value} staff</span>}
            </div>
            {!history.length ? (
              <p className="mt-2 text-xs text-foreground-muted">No effectif recorded yet.</p>
            ) : (
              <table className="mt-2 w-full text-xs">
                <thead>
                  <tr className="text-left text-foreground-muted">
                    <th className="py-1 pr-3 font-semibold">Year</th>
                    <th className="py-1 pr-3 font-semibold">Effectif</th>
                    <th className="py-1 pr-3 font-semibold">Source</th>
                    <th className="py-1 pr-3 font-semibold">11+ (CFP / VM)</th>
                    <th className="py-1 pr-3 font-semibold">50+ (FNAL / M5)</th>
                    <th className="py-1 font-semibold">Corrections</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.year} className="border-t border-border align-top">
                      <td className="py-1.5 pr-3 tabular-nums text-foreground">{h.year}</td>
                      <td className="py-1.5 pr-3 font-mono tabular-nums">{h.value}</td>
                      <td className="py-1.5 pr-3 text-foreground-muted">{h.source}</td>
                      <td className="py-1.5 pr-3"><StatusPill status={h.value >= 11 ? "active" : "inactive"} label={h.value >= 11 ? "11+" : "Under 11"} /></td>
                      <td className="py-1.5 pr-3"><StatusPill status={h.value >= 50 ? "active" : "inactive"} label={h.value >= 50 ? "50+" : "Under 50"} /></td>
                      <td className="py-1.5 text-[11px] text-foreground-muted">
                        {h.history.length
                          ? h.history.map((c, i) => <div key={i}>was {c.value} ({c.source}) — {c.reason}</div>)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
