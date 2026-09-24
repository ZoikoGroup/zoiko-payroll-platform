import { useEffect, useState } from "react";
import { Users, CheckCircle2, AlertTriangle } from "lucide-react";
import { getFranceEmployerProfile, recordFranceEffectif } from "../../../../service/superAdminService";
import { describeLoadError } from "../../../../service/errorClassification";
import { effectifHistory } from "./franceOverviewSummaries";

// Governed annual effectif with threshold history (FR-015/FR-036). The
// 11-employee cut (santé reduced band, CFP class) and the 50-employee cut
// (FNAL class, M5 due-date class) are decided from the LATEST recorded year
// — recording a new year is what moves those governance thresholds.
export default function FranceEffectifTab({ organizationId }) {
  const [state, setState] = useState({ loading: true, profile: null, error: null });
  const [form, setForm] = useState({ year: String(new Date().getFullYear()), value: "", source: "DSN" });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    if (!organizationId) {
      setState({ loading: false, profile: null, error: null });
      return;
    }
    let cancelled = false;
    setState({ loading: true, profile: null, error: null });
    getFranceEmployerProfile({ organizationId })
      .then((p) => {
        if (!cancelled) setState({ loading: false, profile: p || null, error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ loading: false, error: describeLoadError(err), profile: null });
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  useEffect(() => {
    setSaved(false);
  }, [form.year, form.value, form.source]);

  async function record() {
    setSaving(true);
    setSaveError(null);
    try {
      const profile = await recordFranceEffectif(
        { year: Number(form.year), value: Number(form.value), source: form.source || "DSN" },
        { organizationId },
      );
      setState((s) => ({ ...s, profile }));
      setSaved(true);
    } catch (err) {
      setSaveError(describeLoadError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-sm text-foreground-muted">Select an organization to manage its governed effectif.</p>;
  }
  if (state.loading) {
    return <p className="py-10 text-sm text-foreground-disabled">Loading effectif history…</p>;
  }

  const history = effectifHistory(state.profile?.effectifState);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Users size={16} className="text-primary" />
        <h2 className="text-sm font-bold text-foreground">Governed effectif (FR-015/FR-036)</h2>
      </div>

      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Year</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.year}
              inputMode="numeric"
              onChange={(e) => setForm((f) => ({ ...f, year: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Average governed headcount</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.value}
              inputMode="numeric"
              onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Source</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.source}
              onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={record}
            disabled={saving || !form.year || !form.value}
            className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
          >
            {saving ? "Recording…" : "Record effectif"}
          </button>
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-600">
              <CheckCircle2 size={13} /> Recorded
            </span>
          )}
          {saveError && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600">
              <AlertTriangle size={13} /> {saveError}
            </span>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="text-xs font-bold text-foreground mb-2">Threshold history (newest first)</p>
        {!history.length ? (
          <p className="text-xs text-foreground-muted">No effectif recorded yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">Year</th>
                <th className="py-1 pr-3 font-semibold">Effectif</th>
                <th className="py-1 pr-3 font-semibold">≥11 santé band</th>
                <th className="py-1 font-semibold">≥50 FNAL / M5</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.year} className="border-t border-border">
                  <td className="py-1.5 pr-3">{h.year}</td>
                  <td className="py-1.5 pr-3">{h.value} <span className="text-foreground-disabled">({h.source})</span></td>
                  <td className="py-1.5 pr-3">{h.value >= 11 ? "11+" : "Under 11"}</td>
                  <td className="py-1.5">{h.value >= 50 ? "50+" : "Under 50"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}